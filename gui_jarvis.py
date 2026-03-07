# JARVIS Auto Renamer - Main Application
# 리팩토링된 메인 파일 (모듈화 적용됨)

import sys
import os

# Qt DPI 경고 해결: Qt가 DPI 인식 설정을 시도하기 전에 비활성화
# "SetProcessDpiAwarenessContext() failed" 경고 억제
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"
import json
import threading
import datetime
import subprocess
import keyboard  # 글로벌 단축키
import pyperclip  # 클립보드 + 붙여넣기

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QGridLayout,
                             QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QLineEdit, QTextEdit, QDialog,
                             QFileDialog, QMessageBox, QScrollArea, QGraphicsOpacityEffect,
                             QStackedWidget, QSizePolicy)
from PyQt6.QtCore import (Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, 
                          QPoint, QParallelAnimationGroup, QEvent)
from PyQt6.QtGui import QPixmap, QFont

# Internal Modules (Logic)
from auto_rename import AutoRenamer, check_single_instance, set_api_key, Archiver
from calendar_manager import LocalScheduleManager, WindowsNotifier

# Export Automation Modules
from export_mail_monitor import HanbiroMailMonitor
from export_excel_parser import ExportExcelParser
from readykorea_automation import ReadyKoreaAutomation, ExportInputData, AutomationStatus
from export_mail_sender import ExportMailSender, EmailConfig


# GUI Modules (Refactored)
from gui.styles import GLOBAL_STYLESHEET
from gui.utils import resource_path, get_run_dir
from gui.widgets import GlassFrame, NeonButton
from gui.mk3_widgets import MK3ScheduleOnlyWidget, MK3MemoOnlyWidget
from gui.dialogs import IntroWindow, GroupCard, MarkingPopup
from gui.panels import FileManagerWidget
from gui.jarvis_toast import get_toast_handler, show_custom_toast  # [NEW] Custom Toast Imports
from version import __version__, APP_NAME
from updater import check_for_update, download_update, apply_update



class JarvisGUI(QMainWindow):
    # Signals for thread-safe UI updates
    log_signal = pyqtSignal(str)
    merge_signal = pyqtSignal(dict)
    merge_complete_signal = pyqtSignal()  # 병합 완료 시 emit
    rename_trigger_signal = pyqtSignal()  # 파일 이름 변경 완료 시 emit (디바운싱 트리거)
    export_update_signal = pyqtSignal(object)  # 수출 자동화 UI 업데이트용
    marking_request_signal = pyqtSignal(str, str, str)  # 수출신고필증 마킹 요청 (company, invoice_id, filepath)
    update_check_done = pyqtSignal(dict)  # 업데이트 확인 완료 시그널

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TRADIS MH - Auto Renamer")
        self.resize(1700, 950)
        self.setMinimumSize(1280, 720)
        
        # Frameless & Rounded Corners
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.drag_pos = None # Initialize for window dragging
        
        # 디바운싱용 타이머
        self.debounce_timer = QTimer(self)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self._debounced_refresh)
        
        # Load Logic
        self.renamer = AutoRenamer(
            log_callback=self.emit_log, 
            merge_request_callback=self.handle_merge_request,
            rename_complete_callback=lambda: self.rename_trigger_signal.emit()
        )
        self.archiver = Archiver(import_root="", export_root="", log_callback=self.emit_log)
        
        # 수출신고필증 마킹 관련
        self.marking_queue = []  # 대기열: [(company, invoice_id, filepath), ...]
        self.marking_popup_active = False  # 현재 팝업 표시 중 여부
        self.marked_data = {}  # {invoice_id: [{'name': str, 'path': str, 'icon': str}, ...]}
        self.renamer.export_declaration_callback = self._on_export_declaration_renamed
        
        # 메일 모니터 초기화 (기능 제거됨)
        self.mail_monitor = None
        
        # ReadyKorea 자동화 초기화
        self.rk_automation = ReadyKoreaAutomation(on_status_change=self._on_rk_status_change)
        self.last_export_data = None  # 마지막 파싱된 수출 데이터 저장
        self.last_mail_info = None    # 마지막 수신 메일 정보 저장
        self.mail_sender = None       # 메일 발송기 (나중에 초기화)

        
        # 기존 config.json 민감정보를 keyring으로 마이그레이션
        self._migrate_credentials_to_keyring()

        # 라이선스 등급 (admin: 전체, standard: 통관/보고 제외)
        self.license_tier = self._load_license_tier()

        # Setup UI
        self.init_ui()
        self.load_background()
        self.load_settings()
        
        # Connect Signals
        self.log_signal.connect(self.append_log)
        self.merge_signal.connect(self._update_middle_panel)
        self.merge_complete_signal.connect(self._on_merge_complete)
        self.rename_trigger_signal.connect(self.trigger_debounced_refresh)
        self.marking_request_signal.connect(self._show_marking_popup)
        # 메일 모니터링 UI 자동 갱신 (기능 제거됨)
        # self.export_update_signal.connect(self._update_veronica_ui)
        
        # ReadyKorea 버튼 시그널 연결 (setup_right_panel에서 이미 연결됨 - 중복 제거)
        # 주의: rk_auto_input_clicked, send_mail_clicked는 setup_right_panel()에서 연결됨
        self.file_manager.item_deleted.connect(self._on_mail_item_deleted_reset) # 목록 삭제 시 초기화
        self.file_manager.admin_unlocked.connect(self._on_admin_unlocked)  # 관리자 잠금 해제
        
        # Everything 자동 시작 (검색 기능 활성화) - 비동기 실행으로 프리징 방지
        threading.Thread(target=self._start_everything, daemon=True).start()
        
        # 메일 모니터링 자동 시작 (기능 제거됨)
        # QTimer.singleShot(2000, self._start_mail_monitoring)

        # 창을 화면 중앙에 배치
        self._center_on_screen()
        
        # [NEW] 전역 토스트 핸들러 초기화 (메인 스레드 보장)
        # 이 호출은 반드시 메인 스레드(여기)에서 실행되어야 함
        get_toast_handler()
        self.emit_log("Notification System Initialized.")
        
        # [NEW] 글로벌 단축키 초기화
        self._setup_global_hotkeys()

        # [NEW] 앱 시작 시 자동 업데이트 확인 (3초 후, 비동기)
        self.update_check_done.connect(self._on_update_check_result)
        QTimer.singleShot(3000, self._check_update_async)

    
    def _migrate_credentials_to_keyring(self):
        """기존 config.json의 민감정보를 Windows Credential Manager로 이동 (최초 1회)"""
        try:
            import keyring
            cfg_path = os.path.join(get_run_dir(), "config.json")
            if not os.path.exists(cfg_path):
                return
            with open(cfg_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            changed = False

            # 이메일 비밀번호 마이그레이션
            hanbiro = data.get('hanbiro_mail', {})
            if 'password' in hanbiro and hanbiro['password']:
                if not keyring.get_password("TRADIS_MH", "email_password"):
                    keyring.set_password("TRADIS_MH", "email_password", hanbiro['password'])
                del hanbiro['password']
                data['hanbiro_mail'] = hanbiro
                changed = True

            # API 키 마이그레이션 (core/config.py에서도 처리하지만 여기서도 확인)
            if 'api_key' in data and data['api_key']:
                from core.config import _decode_api_key
                actual_key = _decode_api_key(data['api_key'])
                if actual_key and not keyring.get_password("TRADIS_MH", "gemini_api_key"):
                    keyring.set_password("TRADIS_MH", "gemini_api_key", actual_key)
                del data['api_key']
                changed = True

            if changed:
                with open(cfg_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception:
            pass  # 마이그레이션 실패 시 기존 동작 유지

    def _load_license_tier(self):
        """config.json에서 라이선스 등급 로드"""
        try:
            cfg_path = os.path.join(get_run_dir(), "config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get("license_tier", "standard")
        except (OSError, json.JSONDecodeError):
            pass
        return "standard"

    def _center_on_screen(self):
        """창을 화면 중앙에 배치"""
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        
    def init_ui(self):
        # Apply global stylesheet to the whole window
        self.setStyleSheet(GLOBAL_STYLESHEET)
        
        # Outer container for rounded corners
        self.outer_container = QFrame(self)
        self.outer_container.setObjectName("OuterContainer")
        self.setCentralWidget(self.outer_container)
        
        # Total Layout
        total_layout = QVBoxLayout(self.outer_container)
        total_layout.setContentsMargins(0, 0, 0, 10)
        total_layout.setSpacing(0)
        
        # 0. Custom Title Bar
        self.title_bar = QFrame()
        self.title_bar.setFixedHeight(50)
        self.title_bar.setStyleSheet("background: transparent; border: none;")
        tb_layout = QHBoxLayout(self.title_bar)
        tb_layout.setContentsMargins(20, 0, 20, 0)
        
        tb_layout.addStretch()
        
        # 최소화 버튼 (macOS 스타일 원형)
        self.btn_minimize = QPushButton("")
        self.btn_minimize.setFixedSize(14, 14)
        self.btn_minimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minimize.setStyleSheet("""
            QPushButton {
                background-color: #febc2e;
                border: none;
                border-radius: 7px;
            }
            QPushButton:hover {
                background-color: #e5a520;
            }
        """)
        self.btn_minimize.clicked.connect(self._show_mini_window)
        tb_layout.addWidget(self.btn_minimize)

        tb_layout.addSpacing(8)

        # 닫기 버튼 (macOS 스타일 원형)
        self.btn_close = QPushButton("")
        self.btn_close.setFixedSize(14, 14)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #ff5f57;
                border: none;
                border-radius: 7px;
            }
            QPushButton:hover {
                background-color: #e04640;
            }
        """)
        self.btn_close.clicked.connect(self.close)
        tb_layout.addWidget(self.btn_close)
        
        total_layout.addWidget(self.title_bar)
        
        # 1. Main Content Grid (3 Columns: LeftStack, Right, NavBar)
        content_widget = QWidget()
        self.main_layout = QGridLayout(content_widget)
        self.main_layout.setContentsMargins(2, 10, 2, 10)
        self.main_layout.setHorizontalSpacing(2)
        self.main_layout.setVerticalSpacing(20)

        self.main_layout.setColumnStretch(0, 15)  # Left content stack
        self.main_layout.setColumnStretch(1, 5)   # Right panel
        self.main_layout.setColumnStretch(2, 0)   # NavBar

        # --- LEFT CONTENT STACK (QStackedWidget) ---
        self.left_content_stack = QStackedWidget()

        # Page 0: 정산 (left_panel + middle_panel)
        mk1_page = QWidget()
        mk1_layout = QHBoxLayout(mk1_page)
        mk1_layout.setContentsMargins(0, 0, 0, 0)
        mk1_layout.setSpacing(2)

        self.left_panel = GlassFrame()
        self.setup_left_panel()
        mk1_layout.addWidget(self.left_panel)

        self.middle_panel = GlassFrame()
        self.setup_middle_panel()
        mk1_layout.addWidget(self.middle_panel, stretch=1)

        self.left_content_stack.addWidget(mk1_page)  # index 0
        self.main_layout.addWidget(self.left_content_stack, 0, 0)

        # --- RIGHT PANEL (FileManager) ---
        self.right_panel = GlassFrame()
        self.setup_right_panel()
        self.main_layout.addWidget(self.right_panel, 0, 1)

        # --- VERTICAL NAV BAR ---
        self._create_vertical_navbar()

        # file_manager.search_panel을 오버레이로 가져옴
        self.search_panel = self.file_manager.search_panel
        self.search_panel.setParent(self)
        self.search_panel.hide()
        self.search_panel.raise_()

        # file_manager의 탭 바 숨기기
        self.file_manager.tabs.tabBar().hide()

        # 콘텐츠 페이지 생성 (일정, 통관, REPORT, SETTINGS)
        self._create_content_pages()
        
        total_layout.addWidget(content_widget)
    
    def _create_vertical_navbar(self):
        """오른쪽 세로 NavBar 생성"""
        self.navbar = QWidget()
        self.navbar.setFixedWidth(40)
        navbar_layout = QVBoxLayout(self.navbar)
        navbar_layout.setContentsMargins(5, 10, 5, 10)
        navbar_layout.setSpacing(8)
        
        self.navbar.setStyleSheet("""
            QWidget#NavBar {
                background-color: rgba(5, 15, 30, 180);
                border: 1px solid rgba(0, 255, 255, 100);
                border-radius: 8px;
            }
            QPushButton { font-size: 9pt; font-weight: bold; padding: 0px; }
        """)
        self.navbar.setObjectName("NavBar")
        
        self.nav_buttons = {}
        tab_defs = [
            ("정산", "정\n산", "#00ffff"),
            ("일정", "일\n정", "#00ff88"),
            ("통관", "통\n관", "#ffa500"),
            ("REPORT", "보\n고", "#ff88ff"),
            ("SETTINGS", "설\n정", "#aaaaaa"),
        ]

        # admin 전용 탭
        admin_only_tabs = {"일정", "통관", "REPORT"}

        for tab_name, label, color in tab_defs:
            if tab_name in admin_only_tabs and self.license_tier != "admin":
                continue
            btn = QPushButton(label)
            btn.setFixedSize(30, 45)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("tab_name", tab_name)
            
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(5, 20, 35, 120);
                    border: 1px solid rgba(0, 255, 255, 80);
                    border-radius: 6px;
                    color: rgba(255, 255, 255, 200);
                    text-align: center;
                    padding-top: 2px;
                }}
                QPushButton:hover {{
                    background-color: rgba(0, 255, 255, 30);
                    border: 1px solid {color};
                    color: #ffffff;
                }}
                QPushButton:checked {{
                    background-color: rgba(0, 255, 255, 50);
                    border: 1px solid {color};
                    border-left: 3px solid {color};
                    color: {color};
                    font-weight: bold;
                }}
            """)
            
            btn.clicked.connect(lambda checked, name=tab_name: self._on_navbar_clicked(name))
            navbar_layout.addWidget(btn)
            self.nav_buttons[tab_name] = btn
        
        navbar_layout.addStretch()
        self.nav_buttons["정산"].setChecked(True)
        self.current_nav_tab = "정산"
        self.main_layout.addWidget(self.navbar, 0, 2)
    
    def _on_navbar_clicked(self, tab_name):
        for name, btn in self.nav_buttons.items():
            btn.setChecked(name == tab_name)
        self.current_nav_tab = tab_name

        # 1) QStackedWidget 페이지 전환
        page_idx = self.PAGE_INDEX.get(tab_name, 0)
        # 모든 페이지 sizePolicy를 Ignored로 → 현재 페이지만 Preferred로
        for i in range(self.left_content_stack.count()):
            w = self.left_content_stack.widget(i)
            if i == page_idx:
                w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            else:
                w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.left_content_stack.setCurrentIndex(page_idx)

        # 2) file_manager 탭 전환 (이름으로 찾기)
        for i in range(self.file_manager.tabs.count()):
            if self.file_manager.tabs.tabText(i) == tab_name:
                self.file_manager.tabs.setCurrentIndex(i)
                break

        # 3) 레이아웃 조정
        self.left_content_stack.setMaximumWidth(16777215)
        if tab_name == "REPORT":
            # REPORT: 전체화면 (right_panel 숨김)
            self.left_content_stack.show()
            self.right_panel.hide()
            self.main_layout.setColumnStretch(0, 1)
            self.main_layout.setColumnStretch(1, 0)
        elif tab_name == "SETTINGS":
            # SETTINGS: 빈 좌측 + 기존 크기 right_panel
            self.left_content_stack.show()
            self.right_panel.show()
            self.right_panel.setMaximumWidth(500)
            self.main_layout.setColumnStretch(0, 15)
            self.main_layout.setColumnStretch(1, 5)
        elif tab_name == "정산":
            # 정산: 좌측 넓게 + 우측 제한
            self.left_content_stack.show()
            self.right_panel.show()
            self.right_panel.setMaximumWidth(500)
            self.main_layout.setColumnStretch(0, 15)
            self.main_layout.setColumnStretch(1, 5)
        elif tab_name == "일정":
            # 일정: 캘린더 넓게 + 메모 제한
            self.left_content_stack.show()
            self.left_content_stack.setMaximumWidth(16777215)
            self.right_panel.show()
            self.right_panel.setMaximumWidth(600)
            self.main_layout.setColumnStretch(0, 1)
            self.main_layout.setColumnStretch(1, 0)
        else:
            # 통관: 좌측 넓게 + 우측 기존 크기
            self.left_content_stack.show()
            self.right_panel.show()
            self.right_panel.setMaximumWidth(500)
            self.main_layout.setColumnStretch(0, 12)
            self.main_layout.setColumnStretch(1, 6)
    
    # 페이지 인덱스 매핑
    PAGE_INDEX = {"정산": 0, "일정": 1, "통관": 2, "REPORT": 3, "SETTINGS": 4}

    def _create_content_pages(self):
        """QStackedWidget에 일정/통관/REPORT/SETTINGS 페이지 추가"""
        # --- 공유 리소스 (라이선스 무관하게 항상 생성) ---
        self.shared_schedule_manager = LocalScheduleManager()

        class CustomNotifierAdapter:
            def show_toast(self, title, message, duration=10, icon_path=None):
                return show_custom_toast(title, message, duration)

        self.shared_schedule_manager.notifier = CustomNotifierAdapter()
        self.shared_notifier = self.shared_schedule_manager.notifier

        # --- Page 1: 일정 (캘린더) ---
        mk3_page = GlassFrame()
        mk3_layout = QVBoxLayout(mk3_page)
        mk3_layout.setContentsMargins(15, 15, 15, 15)
        mk3_layout.setSpacing(10)
        self.mk3_schedule_widget = MK3ScheduleOnlyWidget(
            schedule_manager=self.shared_schedule_manager,
            notifier=self.shared_notifier
        )
        mk3_layout.addWidget(self.mk3_schedule_widget)
        self.left_content_stack.addWidget(mk3_page)  # index 1

        # 일정 메모 위젯 -> file_manager 내부 레이아웃에 추가
        self.mk3_memo_widget = MK3MemoOnlyWidget(
            schedule_manager=self.shared_schedule_manager
        )
        self.mk3_memo_widget.hotkey_settings_clicked.connect(self.show_hotkey_settings)
        if hasattr(self.file_manager, 'mk3_memo_layout'):
            self.file_manager.mk3_memo_layout.addWidget(self.mk3_memo_widget)

        # --- Page 2: 통관 (placeholder) ---
        veronica_page = GlassFrame()
        veronica_page_layout = QVBoxLayout(veronica_page)
        veronica_page_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_veronica = QLabel("통관 자동화\n\n(Coming Soon)")
        lbl_veronica.setStyleSheet("color: #ffa500; font-size: 16pt; font-weight: bold;")
        lbl_veronica.setAlignment(Qt.AlignmentFlag.AlignCenter)
        veronica_page_layout.addWidget(lbl_veronica)
        self.left_content_stack.addWidget(veronica_page)  # index 2

        # --- Page 3: REPORT ---
        from gui.report_panel import ReportPanel
        report_page = GlassFrame()
        report_layout = QVBoxLayout(report_page)
        report_layout.setContentsMargins(0, 0, 0, 0)
        self.report_widget = ReportPanel()
        self.report_widget.log_signal.connect(self.emit_log)
        report_layout.addWidget(self.report_widget)
        self.left_content_stack.addWidget(report_page)  # index 3

        # --- Page 4: SETTINGS (빈 페이지, right_panel만 사용) ---
        settings_page = QWidget()
        self.left_content_stack.addWidget(settings_page)  # index 4

        # 초기 탭 설정
        self.left_content_stack.setCurrentIndex(0)
        self._on_navbar_clicked("정산")
    

    def closeEvent(self, event):
        try:
            self.stop_monitoring()
            # 메모 강제 저장 (디바운스 타이머 만료 전 유실 방지)
            if hasattr(self, 'mk3_memo_widget'):
                self.mk3_memo_widget.save_all_memos()
            if hasattr(self, 'schedule_manager'):
                self.schedule_manager.stop_reminder_loop()
            self.save_settings()
            # 글로벌 단축키 해제
            keyboard.unhook_all()
            self._remove_snippet_hook()
        except Exception as e:
            print(f"Close event error: {e}")
        event.accept()

    # ========== 글로벌 단축키 & 텍스트 스니펫 ==========
    
    def _setup_global_hotkeys(self):
        """글로벌 단축키 초기화"""
        self.hotkey_settings = self._load_hotkey_settings()
        self._register_hotkeys()
        self.emit_log(f"Global Hotkeys Initialized: Memo={self.hotkey_settings.get('memo_hotkey', 'ctrl+shift+m')}")
    
    def _load_hotkey_settings(self):
        """단축키 설정 로드"""
        default_settings = {
            "memo_hotkey": "ctrl+shift+m",
            "snippets": [
                {"hotkey": "ctrl+1", "text": "[해도관세사무소]"},
                {"hotkey": "ctrl+2", "text": "확인 후 송금 부탁드립니다"},
                {"hotkey": "ctrl+3", "text": "잔액 보내드리겠습니다"},
                {"hotkey": "ctrl+4", "text": ""},
                {"hotkey": "ctrl+5", "text": ""},
                {"hotkey": "", "text": ""},
                {"hotkey": "", "text": ""},
                {"hotkey": "", "text": ""},
                {"hotkey": "", "text": ""}
            ]
        }
        try:
            cfg_path = os.path.join(get_run_dir(), "config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "hotkeys" in data:
                        return data["hotkeys"]
        except Exception as e:
            print(f"단축키 설정 로드 오류: {e}")
        return default_settings
    
    def _save_hotkey_settings(self):
        """단축키 설정 저장"""
        try:
            cfg_path = os.path.join(get_run_dir(), "config.json")
            data = {}
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            data["hotkeys"] = self.hotkey_settings
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"단축키 설정 저장 오류: {e}")
    
    def _register_hotkeys(self):
        """단축키 등록"""
        try:
            # 메모장 단축키
            memo_key = self.hotkey_settings.get("memo_hotkey", "ctrl+shift+m")
            if memo_key:
                keyboard.add_hotkey(memo_key, self._activate_memo, suppress=False)
            
            # 스니펫 단축키 - Win32 저수준 훅 사용 (Ctrl 키 미차단)
            self._install_snippet_hook()
        except Exception as e:
            print(f"단축키 등록 오류: {e}")
    
    def _unregister_hotkeys(self):
        """단축키 해제"""
        keyboard.unhook_all()
        self._remove_snippet_hook()
    
    def _activate_memo(self):
        """메모장 활성화 (다른 스레드에서 호출됨)"""
        QTimer.singleShot(0, self._show_memo_tab)
    
    def _show_memo_tab(self):
        """일정 메모 탭 표시 (메인 스레드)"""
        self.showNormal()
        self.activateWindow()
        self.raise_()
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except (ValueError, OSError):
            pass

        # navbar를 통해 일정 전환
        self._on_navbar_clicked("일정")

        if hasattr(self, 'mk3_memo_widget'):
            QTimer.singleShot(100, self.mk3_memo_widget.focus_current_memo)
        
        self.emit_log("📝 메모장 활성화됨")
    
    def _paste_snippet(self, text):
        """텍스트 스니펫 붙여넣기 (다른 스레드에서 호출됨)"""
        def do_paste():
            try:
                # 클립보드에 복사
                pyperclip.copy(text)
                # Ctrl+V 시뮬레이션
                keyboard.send('ctrl+v')
            except Exception as e:
                print(f"스니펫 붙여넣기 오류: {e}")
        
        # 약간의 딜레이 후 붙여넣기 (키 릴리스 대기)
        threading.Timer(0.05, do_paste).start()
    
    def _install_snippet_hook(self):
        """Win32 저수준 키보드 훅으로 스니펫 단축키 등록 (Ctrl 키 미차단)"""
        import ctypes
        import ctypes.wintypes
        
        # VK 코드 → 스니펫 텍스트 맵 구축
        self._vk_snippet_map = {}
        for snippet in self.hotkey_settings.get("snippets", []):
            hk = snippet.get("hotkey", "")
            text = snippet.get("text", "")
            if hk and text:
                parts = [p.strip().lower() for p in hk.split("+")]
                if "ctrl" in parts:
                    trigger_parts = [p for p in parts if p != "ctrl"]
                    if trigger_parts:
                        vk = self._key_to_vk(trigger_parts[0])
                        if vk is not None:
                            self._vk_snippet_map[vk] = text
        
        if not self._vk_snippet_map:
            self._snippet_hook_handle = None
            return
        
        user32 = ctypes.windll.user32
        
        # CallNextHookEx 인자 타입 명시 (64비트 lParam 오버플로 방지)
        user32.CallNextHookEx.argtypes = [
            ctypes.wintypes.HHOOK, ctypes.c_int,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
        ]
        user32.CallNextHookEx.restype = ctypes.wintypes.LPARAM
        
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, ctypes.c_void_p,
            ctypes.wintypes.HINSTANCE, ctypes.wintypes.DWORD
        ]
        user32.SetWindowsHookExW.restype = ctypes.wintypes.HHOOK
        
        WH_KEYBOARD_LL = 13
        WM_KEYDOWN = 0x0100
        WM_SYSKEYDOWN = 0x0104
        HC_ACTION = 0
        VK_CONTROL = 0x11
        
        HOOKPROC = ctypes.CFUNCTYPE(
            ctypes.c_long, ctypes.c_int,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
        )
        
        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", ctypes.wintypes.DWORD),
                ("scanCode", ctypes.wintypes.DWORD),
                ("flags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]
        
        vk_map = self._vk_snippet_map
        paste_fn = self._paste_snippet
        
        @HOOKPROC
        def hook_proc(nCode, wParam, lParam):
            if nCode == HC_ACTION and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.vkCode in vk_map:
                    # Ctrl 키가 눌려있는지 확인
                    if user32.GetAsyncKeyState(VK_CONTROL) & 0x8000:
                        text = vk_map[kb.vkCode]
                        threading.Timer(0.05, lambda: paste_fn(text)).start()
                        return 1  # 숫자 키만 차단 (Ctrl은 이미 OS에 전달됨)
            return user32.CallNextHookEx(None, nCode, wParam, lParam)
        
        # GC 방지를 위해 참조 유지
        self._hook_proc_ref = hook_proc
        self._snippet_hook_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, hook_proc, None, 0
        )
        
        if self._snippet_hook_handle:
            print(f"✅ Win32 스니펫 훅 설치 완료 (매핑: {len(vk_map)}개)")
        else:
            print("❌ Win32 스니펫 훅 설치 실패")
    
    def _remove_snippet_hook(self):
        """Win32 스니펫 키보드 훅 제거"""
        if hasattr(self, '_snippet_hook_handle') and self._snippet_hook_handle:
            import ctypes
            ctypes.windll.user32.UnhookWindowsHookEx(self._snippet_hook_handle)
            self._snippet_hook_handle = None
            self._hook_proc_ref = None
    
    def _key_to_vk(self, key_str):
        """키 문자열을 Windows VK 코드로 변환"""
        key = key_str.strip().lower()
        if len(key) == 1:
            if key.isdigit():
                return 0x30 + int(key)  # VK_0(0x30) ~ VK_9(0x39)
            elif key.isalpha():
                return ord(key.upper())  # VK_A(0x41) ~ VK_Z(0x5A)
        return None
    
    def show_hotkey_settings(self):
        """단축키 설정 다이얼로그 표시 - Nano Banana Style"""
        from gui.widgets import GlassFrame, NeonButton
        
        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setFixedSize(750, 580)
        
        # 메인 컨테이너 (네온 테두리)
        container = QFrame(dlg)
        container.setGeometry(0, 0, 750, 580)
        container.setStyleSheet("""
            QFrame {
                background-color: rgba(8, 15, 25, 245);
                border: 2px solid #00ffcc;
                border-radius: 15px;
            }
        """)
        
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(25, 20, 25, 20)
        main_layout.setSpacing(15)
        
        # ===== 제목 =====
        header = QLabel("⌨️ 단축키 및 텍스트 스니펫 설정")
        header.setStyleSheet("color: #00ffcc; font-size: 14pt; font-weight: bold;")
        main_layout.addWidget(header)
        
        # ===== 메모장 단축키 섹션 =====
        memo_frame = QFrame()
        memo_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 30, 45, 150);
                border: 1px solid #00aaaa;
                border-radius: 12px;
            }
        """)
        memo_layout = QHBoxLayout(memo_frame)
        memo_layout.setContentsMargins(15, 12, 15, 12)
        memo_layout.setSpacing(15)
        
        memo_label = QLabel("메모장 열기:")
        memo_label.setStyleSheet("color: #00cccc; font-size: 10pt; font-weight: bold; border: none;")
        memo_label.setFixedWidth(100)
        memo_layout.addWidget(memo_label)
        
        memo_input = QLineEdit(self.hotkey_settings.get("memo_hotkey", "ctrl+shift+m"))
        memo_input.setFixedHeight(36)
        memo_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(10, 25, 40, 200);
                border: 2px solid #00aaaa;
                border-radius: 18px;
                color: #00ffff;
                padding: 5px 15px;
                font-size: 11pt;
                font-weight: bold;
            }
            QLineEdit:focus { 
                border: 2px solid #00ffcc;
                background-color: rgba(15, 35, 55, 220);
            }
        """)
        memo_layout.addWidget(memo_input, 1)
        main_layout.addWidget(memo_frame)
        
        # ===== 열 헤더: HOTKEY | SNIPPET TEXT =====
        col_header = QWidget()
        col_header.setStyleSheet("background: transparent;")
        col_header_layout = QHBoxLayout(col_header)
        col_header_layout.setContentsMargins(15, 5, 15, 5)
        col_header_layout.setSpacing(0)
        
        lbl_hotkey = QLabel("HOTKEY")
        lbl_hotkey.setStyleSheet("color: #88aacc; font-size: 9pt; font-weight: bold;")
        lbl_hotkey.setFixedWidth(130)
        col_header_layout.addWidget(lbl_hotkey)
        
        col_header_layout.addSpacing(30)
        
        lbl_snippet = QLabel("SNIPPET TEXT")
        lbl_snippet.setStyleSheet("color: #88aacc; font-size: 9pt; font-weight: bold;")
        col_header_layout.addWidget(lbl_snippet, 1)
        
        main_layout.addWidget(col_header)
        
        # ===== 스크롤 영역 =====
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea { 
                border: none; 
                background: transparent; 
            }
            QScrollBar:vertical { 
                width: 8px; 
                background: rgba(0, 50, 70, 100);
                border-radius: 4px;
            }
            QScrollBar::handle:vertical { 
                background: #00aaaa; 
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #00ffcc; }
        """)
        
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(0, 0, 8, 0)
        scroll_layout.setSpacing(8)
        
        snippet_inputs = []
        snippets = self.hotkey_settings.get("snippets", [])
        
        # Nano Banana 입력 필드 스타일
        hotkey_style = """
            QLineEdit {
                background-color: rgba(10, 25, 40, 200);
                border: 2px solid #00aaaa;
                border-radius: 15px;
                color: #00ffff;
                padding: 5px 12px;
                font-size: 10pt;
                font-weight: bold;
            }
            QLineEdit:hover {
                border: 2px solid #00cccc;
                background-color: rgba(15, 35, 55, 200);
            }
            QLineEdit:focus { 
                border: 2px solid #00ffcc;
                background-color: rgba(20, 45, 65, 220);
                color: #ffffff;
            }
        """
        
        text_style = """
            QTextEdit {
                background-color: rgba(10, 25, 40, 200);
                border: 2px solid #00aaaa;
                border-radius: 15px;
                color: #ffffff;
                padding: 8px 12px;
                font-size: 10pt;
            }
            QTextEdit:hover {
                border: 2px solid #00cccc;
                background-color: rgba(15, 35, 55, 200);
            }
            QTextEdit:focus { 
                border: 2px solid #00ffcc;
                background-color: rgba(20, 45, 65, 220);
            }
        """
        
        for i in range(9):
            row_widget = QWidget()
            row_widget.setStyleSheet("background: transparent;")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(5, 0, 5, 0)
            row_layout.setSpacing(10)
            
            # 단축키 입력
            hk = snippets[i].get("hotkey", "") if i < len(snippets) else ""
            hotkey_input = QLineEdit(hk)
            hotkey_input.setFixedWidth(120)
            hotkey_input.setFixedHeight(38)
            hotkey_input.setPlaceholderText(f"Ctrl+{i+1}")
            hotkey_input.setStyleSheet(hotkey_style)
            row_layout.addWidget(hotkey_input)
            
            # 화살표
            arrow = QLabel("→")
            arrow.setStyleSheet("color: #00ffcc; font-size: 14pt; font-weight: bold;")
            arrow.setFixedWidth(25)
            arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_layout.addWidget(arrow)
            
            # 텍스트 입력
            txt = snippets[i].get("text", "") if i < len(snippets) else ""
            text_input = QTextEdit()
            text_input.setPlainText(txt)
            text_input.setPlaceholderText("붙여넣을 텍스트...")
            text_input.setStyleSheet(text_style)
            text_input.setTabChangesFocus(True)
            
            # 자동 높이 조절
            def adjust_height(editor=text_input):
                doc_height = editor.document().size().height()
                # 기본 38px, 여유분 포함하여 늘리기
                new_height = max(38, int(doc_height + 15))
                editor.setFixedHeight(new_height)
            
            text_input.textChanged.connect(lambda ed=text_input: adjust_height(ed))
            # 초기 높이 설정
            adjust_height(text_input)
            
            row_layout.addWidget(text_input, 1)
            
            snippet_inputs.append((hotkey_input, text_input))
            scroll_layout.addWidget(row_widget)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll, 1)
        
        # ===== 버튼: SAVE / CANCEL =====
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(20)
        btn_layout.addStretch()
        
        # SAVE 버튼
        btn_save = QPushButton("SAVE")
        btn_save.setFixedSize(100, 40)
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 60, 80, 200);
                border: 2px solid #00ffcc;
                border-radius: 20px;
                color: #00ffcc;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(0, 100, 120, 220);
                border: 2px solid #ffffff;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: rgba(0, 150, 170, 250);
            }
        """)
        
        def save_and_close():
            self._unregister_hotkeys()
            self.hotkey_settings["memo_hotkey"] = memo_input.text().strip()
            new_snippets = []
            for hk_input, txt_input in snippet_inputs:
                new_snippets.append({
                    "hotkey": hk_input.text().strip(),
                    "text": txt_input.toPlainText()
                })
            self.hotkey_settings["snippets"] = new_snippets
            self._save_hotkey_settings()
            self._register_hotkeys()
            self.emit_log("⌨️ 단축키 설정 저장됨")
            dlg.accept()
        
        btn_save.clicked.connect(save_and_close)
        btn_layout.addWidget(btn_save)
        
        # CANCEL 버튼
        btn_cancel = QPushButton("CANCEL")
        btn_cancel.setFixedSize(100, 40)
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 60, 80, 200);
                border: 2px solid #00aaaa;
                border-radius: 20px;
                color: #00aaaa;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(80, 40, 40, 220);
                border: 2px solid #ff6666;
                color: #ff6666;
            }
            QPushButton:pressed {
                background-color: rgba(120, 50, 50, 250);
            }
        """)
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)
        
        dlg.exec()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.pos().y() < 50:
                self.drag_pos = event.globalPosition().toPoint()
                event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_pos is not None:
            delta = event.globalPosition().toPoint() - self.drag_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    def load_background(self):
        self.bg_pixmap = None
        bg_path = resource_path("jarvis_bg.png")
        if os.path.exists(bg_path):
            self.bg_pixmap = QPixmap(bg_path)
            if not hasattr(self, 'bg_label'):
                self.bg_label = QLabel(self.outer_container)
                self.bg_label.lower()
                self.bg_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                self.bg_effect = QGraphicsOpacityEffect(self.bg_label)
                self.bg_label.setGraphicsEffect(self.bg_effect)
                self.bg_anim = QPropertyAnimation(self.bg_effect, b"opacity")
                self.bg_anim.setDuration(12000)
                self.bg_anim.setStartValue(0.0)
                self.bg_anim.setEndValue(1.0)
                self.bg_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.bg_effect.setOpacity(0.0)

    def start_bg_animation(self):
        if hasattr(self, 'bg_anim'):
            self.bg_anim.start()
            self._update_bg_label()
        else:
            self.outer_container.setStyleSheet("#OuterContainer { background-color: #0d1117; border: 3px solid #00ffff; border-radius: 30px; }")

    def _update_bg_label(self):
        if hasattr(self, 'bg_label') and self.bg_pixmap:
            scaled = self.bg_pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            self.bg_label.setPixmap(scaled)
            x_pos = (self.width() - scaled.width()) // 2
            y_pos = (self.height() - scaled.height()) // 2
            x_offset = -15
            self.bg_label.setGeometry(x_pos + x_offset, y_pos, scaled.width(), scaled.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_bg_label()
        if hasattr(self, 'file_manager'):
            self.file_manager.reposition_search_panel()

    def setup_left_panel(self):
        self.left_panel.setFixedWidth(330)
        layout = QVBoxLayout(self.left_panel)
        layout.setContentsMargins(10, 15, 10, 15)
        layout.setSpacing(10)
        
        # Header
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        lbl_title = QLabel("TRADIS MH")
        lbl_title.setStyleSheet("color: #00ffff; font-family: Impact; font-size: 38pt; letter-spacing: 3px;")
        title_box.addWidget(lbl_title)

        lbl_by = QLabel("by M.H. Choi")
        lbl_by.setStyleSheet("color: #447799; font-size: 11pt; font-style: italic; letter-spacing: 1px; background: transparent; margin-left: 2px;")
        title_box.addWidget(lbl_by)
        layout.addLayout(title_box)

        # Subtitle
        lbl_sub = QLabel("AUTO RENAMER")
        lbl_sub.setStyleSheet("color: #005577; font-weight: bold; letter-spacing: 4px;")
        layout.addWidget(lbl_sub)
        layout.addSpacing(10)
        
        # Target Directory
        layout.addWidget(QLabel("TARGET DIRECTORY"))
        path_layout = QHBoxLayout()
        self.line_path = QLineEdit()
        self.line_path.setReadOnly(True)
        self.line_path.setPlaceholderText("C:/Users/User/Desktop/...")
        
        self.btn_browse = NeonButton("SELECT")
        self.btn_browse.clicked.connect(self.browse_directory)
        self.btn_browse.setFixedWidth(90)
        
        path_layout.addWidget(self.line_path)
        path_layout.addWidget(self.btn_browse)
        layout.addLayout(path_layout)
        layout.addSpacing(10)
        
        # API Settings - HUD 스타일 컨테이너
        api_container = QFrame()
        api_container.setStyleSheet("""
            QFrame {
                background-color: rgba(5, 15, 30, 150);
                border: 1px solid rgba(0, 255, 255, 100);
                border-radius: 8px;
            }
        """)
        api_container_layout = QVBoxLayout(api_container)
        api_container_layout.setContentsMargins(12, 10, 12, 10)
        api_container_layout.setSpacing(6)
        
        # 상단: 상태 + 버튼
        top_row = QHBoxLayout()
        self.lbl_api_status = QLabel("● AI STATUS: CHECKING...")
        self.lbl_api_status.setStyleSheet("color: #888; font-size: 9pt; font-weight: bold; background: transparent;")
        top_row.addWidget(self.lbl_api_status)
        top_row.addStretch()
        
        self.btn_api_settings = NeonButton("API", color="cyan")
        self.btn_api_settings.setFixedSize(45, 24)
        self.btn_api_settings.clicked.connect(self.open_api_settings)
        top_row.addWidget(self.btn_api_settings)
        api_container_layout.addLayout(top_row)
        
        # 하단: 모델 버전
        self.lbl_api_version = QLabel("Model: Gemini 3 Flash Preview")
        self.lbl_api_version.setStyleSheet("color: #00aaaa; font-size: 8pt; background: transparent;")
        api_container_layout.addWidget(self.lbl_api_version)

        # 앱 버전
        self.lbl_app_version = QLabel(f"{APP_NAME} v{__version__}")
        self.lbl_app_version.setStyleSheet("color: #00aaaa; font-size: 9pt; font-weight: bold; background: transparent;")
        api_container_layout.addWidget(self.lbl_app_version)
        
        layout.addWidget(api_container)
        layout.addSpacing(10)
        
        # 초기 API 상태 확인
        from auto_rename import api_key
        self.update_api_status(bool(api_key))
        
        # Monitoring
        layout.addWidget(QLabel("MONITORING"))
        act_layout = QHBoxLayout()
        self.btn_start = NeonButton("START")
        self.btn_start.clicked.connect(self.start_monitoring)
        self.btn_stop = NeonButton("STOP", color="orange")
        self.btn_stop.clicked.connect(self.stop_monitoring)
        self.btn_stop.setEnabled(False)
        
        act_layout.addWidget(self.btn_start)
        act_layout.addWidget(self.btn_stop)
        layout.addLayout(act_layout)
        layout.addStretch()
        
        # Logs
        layout.addWidget(QLabel("SYSTEM LOGS"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMinimumHeight(400)
        layout.addWidget(self.log_area)

    def setup_middle_panel(self):
        layout = QVBoxLayout(self.middle_panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        lbl_title = QLabel("FOLDER FILE MANAGEMENT & MERGE")
        lbl_title.setStyleSheet("font-size: 16pt; font-weight: bold; color: #00ffff; letter-spacing: 1px;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)
        
        info_row = QHBoxLayout()
        self.lbl_location = QLabel("Location: (Not Selected)")
        self.lbl_location.setStyleSheet("color: #aaa; font-size: 10pt;")
        info_row.addWidget(self.lbl_location)
        info_row.addStretch()
        
        btn_rescan = NeonButton("RESCAN FOLDER", color="cyan")
        btn_rescan.setFixedSize(140, 32)
        btn_rescan.clicked.connect(self.run_intelligent_merge)
        info_row.addWidget(btn_rescan)
        layout.addLayout(info_row)
        
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #00aaaa;")
        layout.addWidget(line)
        
        lbl_sec = QLabel("■ ID CLASSIFIED FILES (B/L, Invoice No.)")
        lbl_sec.setStyleSheet("color: #ddd; font-weight: bold; margin-top: 10px;")
        layout.addWidget(lbl_sec)
        
        self.merge_scroll = QScrollArea()
        self.merge_scroll.setWidgetResizable(True)
        self.merge_scroll.setStyleSheet("background: transparent; border: none;")
        
        self.merge_container = QWidget()
        self.merge_container.setStyleSheet("background: transparent;")
        self.merge_layout = QVBoxLayout(self.merge_container)
        self.merge_layout.setSpacing(15)
        self.merge_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.merge_scroll.setWidget(self.merge_container)
        layout.addWidget(self.merge_scroll)
        
        self.lbl_hint = QLabel("Waiting for Analysis...")
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_hint.setStyleSheet("color: #555; font-size: 14pt;")
        self.merge_layout.addWidget(self.lbl_hint)

    def setup_right_panel(self):
        # self.right_panel.setMaximumWidth(380) # 동적 제어를 위해 제거
        layout = QVBoxLayout(self.right_panel)
        self.file_manager = FileManagerWidget(path_callback=lambda: self.line_path.text(), archiver=self.archiver, license_tier=self.license_tier)
        # 통관 (수출 자동화) 시그널 연결
        self.file_manager.rk_auto_input_clicked.connect(self._run_readykorea_automation)
        self.file_manager.rk_test_clicked.connect(self._test_readykorea_connection)
        self.file_manager.send_mail_clicked.connect(self._send_reply_email)
        # 메일 모니터링 기능 제거됨 
        # self.file_manager.start_monitoring_clicked.connect(self._start_mail_monitoring)
        # self.file_manager.stop_monitoring_clicked.connect(self._stop_mail_monitoring)
        
        layout.addWidget(self.file_manager)

    def emit_log(self, msg):
        self.log_signal.emit(msg)
        
    def append_log(self, msg):
        MAX_LOG_LINES = 200  # 성능 최적화를 위해 로그 보관 줄 수 축소 (1000 -> 200)
        
        self.log_area.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
        
        # 로그가 너무 길어지면 오래된 로그 삭제 (메모리 안정화)
        if self.log_area.document().blockCount() > MAX_LOG_LINES:
            cursor = self.log_area.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, 100)
            cursor.removeSelectedText()
            cursor.deletePreviousChar()  # 남은 빈 줄 제거
        
        # 자동 스크롤: 맨 아래로 이동
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())
        
    def handle_merge_request(self, report):
        self.emit_log("UI received analysis report (Emitting Signal).")
        try:
            self.merge_signal.emit(report)
        except Exception as e:
            self.emit_log(f"Signal Emit Error: {e}")
        
    def _update_middle_panel(self, report):
        try:
            if hasattr(self, 'file_manager'):
                self.file_manager.refresh_targets()
            while self.merge_layout.count():
                child = self.merge_layout.takeAt(0)
                if child.widget(): child.widget().deleteLater()
                
            groups = report.get('groups', {})
            unclassified = report.get('unclassified', [])
            directory = report.get('directory', '')
            self.emit_log(f"Scan Report: {len(groups)} Groups, {len(unclassified)} Unclassified")
            
            if directory: self.lbl_location.setText(f"Location: {directory}")
            
            if not groups and not unclassified:
                lbl = QLabel("No files to process.")
                lbl.setStyleSheet("color: #777; font-size: 11pt;")
                self.merge_layout.addWidget(lbl)
                return

            for text_id, data in groups.items():
                docs = data.get('docs', {})
                has_statement = '자금정산서' in docs or '정산서' in docs
                is_export = any('수출신고필증' in v for v in docs.values())
                if not has_statement and not is_export:
                    self.emit_log(f"[건너뜀] {text_id}: 자금정산서/수출신고필증 없음")
                    continue
                try:
                    card = GroupCard(self, self.renamer, directory, text_id, data, unclassified)
                    self.merge_layout.addWidget(card)
                except Exception as e: self.emit_log(f"Error creating card for {text_id}: {e}")
                
            if unclassified:
                self.merge_layout.addWidget(QLabel("UNCLASSIFIED FILES"))
                lbl_u = QLabel(", ".join(unclassified))
                lbl_u.setWordWrap(True)
                lbl_u.setStyleSheet("color: #aaaaaa;")
                self.merge_layout.addWidget(lbl_u)
            self.merge_layout.addStretch()
        except Exception as e: self.emit_log(f"Critical error updating UI: {e}")

    def _on_merge_complete(self):
        self.emit_log("[상태] 병합 완료. 파일 이동 리스트를 갱신합니다.")
        if hasattr(self, 'file_manager'):
            self.file_manager.refresh_targets()

    def _debounced_refresh(self):
        # 불필요한 반복 로그 제거 (상태 갱신 시마다 로그가 찍혀 리소스 낭비)
        path = self.line_path.text()
        if path: self.renamer.trigger_intelligent_merge(path)
            
    def trigger_debounced_refresh(self):
        self.debounce_timer.stop()
        self.debounce_timer.start(2000)

    def open_api_settings(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit
        from gui.dialogs import JarvisMessageBox
        from gui.widgets import GlassFrame # Assuming GlassFrame is in gui.widgets
        from PyQt6.QtCore import Qt
        
        # 현재 저장된 키 로드 (keyring에서)
        from core.config import get_api_key
        current_key = get_api_key()

        # 커스텀 HUD 스타일 다이얼로그 생성
        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setFixedWidth(400)
        
        # 컨테이너 (GlassFrame 스타일)
        container = GlassFrame(dlg)
        main_layout = QVBoxLayout(dlg)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)
        
        inner_layout = QVBoxLayout(container)
        inner_layout.setContentsMargins(20, 20, 20, 20)
        inner_layout.setSpacing(15)
        
        # 헤더
        lbl_title = QLabel("🔑 API SETUP")
        lbl_title.setStyleSheet("color: #00ffff; font-size: 16pt; font-weight: bold; background: transparent;")
        inner_layout.addWidget(lbl_title)
        
        # 입력 필드
        lbl_desc = QLabel("Enter Gemini API Key:")
        lbl_desc.setStyleSheet("color: #ffffff; font-size: 10pt; background: transparent;")
        inner_layout.addWidget(lbl_desc)
        
        line_key = QLineEdit()
        line_key.setText(current_key)
        line_key.setEchoMode(QLineEdit.EchoMode.Password)  # 키 숨김
        line_key.setStyleSheet("""
            QLineEdit {
                background-color: rgba(5, 15, 30, 200);
                border: 1px solid #00aaaa;
                border-radius: 5px;
                color: #ffffff;
                padding: 8px;
                font-size: 11pt;
            }
            QLineEdit:focus {
                border: 2px solid #00ffff;
            }
        """)
        inner_layout.addWidget(line_key)
        
        # 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_cancel = NeonButton("취소", color="orange")
        btn_cancel.setFixedHeight(35)
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addWidget(btn_cancel)
        
        btn_save = NeonButton("저장", color="cyan")
        btn_save.setFixedHeight(35)
        btn_save.clicked.connect(dlg.accept)
        btn_layout.addWidget(btn_save)
        
        inner_layout.addLayout(btn_layout)
        
        # 다이얼로그 중앙 배치
        dlg.adjustSize()
        screen = QApplication.primaryScreen().geometry()
        dlg.move((screen.width() - dlg.width()) // 2, (screen.height() - dlg.height()) // 2)
        
        if dlg.exec() == QDialog.DialogCode.Accepted:
            key = line_key.text().strip()
            if key:
                try:
                    set_api_key(key)
                    self.update_api_status(True)
                    JarvisMessageBox.information(self, "성공", "API Key가 저장되었습니다.")
                except Exception as e:
                    self.update_api_status(False)
                    JarvisMessageBox.critical(self, "오류", f"저장 실패: {e}")

    def browse_directory(self):
        d = QFileDialog.getExistingDirectory(self, "Select Target")
        if d:
            self.line_path.setText(d)
            self.file_manager.base_path = d
            self.file_manager.refresh_targets()
            self.save_settings()
            self.run_intelligent_merge()

    def start_monitoring(self):
        from auto_rename import api_key
        if not api_key:
            QMessageBox.critical(self, "API 키 누락", "모니터링을 사용하려면 API 키가 필요합니다.")
            return
        path = self.line_path.text()
        if not path: return
        self.renamer.start(path)
        self.btn_start.setEnabled(False)
        self.btn_start.setText("RUNNING..")
        self.btn_stop.setEnabled(True)
        self.emit_log("Monitoring Started...")
        self.run_intelligent_merge()

    def stop_monitoring(self):
        self.renamer.stop()
        self.btn_start.setEnabled(True)
        self.btn_start.setText("START")
        self.btn_stop.setEnabled(False)
        self.emit_log("Monitoring Stopped.")

    def update_api_status(self, connected: bool):
        if hasattr(self, 'lbl_api_status'):
            if connected:
                self.lbl_api_status.setText("● AI STATUS: CONNECTED")
                self.lbl_api_status.setStyleSheet("color: #00ff00; font-size: 8pt; font-weight: bold;")
            else:
                self.lbl_api_status.setText("● AI STATUS: API KEY REQUIRED")
                self.lbl_api_status.setStyleSheet("color: #ff3333; font-size: 8pt; font-weight: bold;")

    def run_intelligent_merge(self):
        if hasattr(self, 'is_analyzing') and self.is_analyzing: return
        from auto_rename import api_key
        if not api_key:
            QMessageBox.critical(self, "API 키 누락", "API 키가 필요합니다.")
            return
        path = self.line_path.text()
        if not path: return
        self.is_analyzing = True
        self.emit_log("Starting Intelligent Analysis...")
        try:
            while self.merge_layout.count():
                child = self.merge_layout.takeAt(0)
                if child.widget(): child.widget().deleteLater()
            self.lbl_hint = QLabel("Scanning & Analyzing...")
            self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lbl_hint.setStyleSheet("color: #555; font-size: 14pt;")
            self.merge_layout.addWidget(self.lbl_hint)
        except Exception as e:
            print(f"UI clear error: {e}")
        
        def _run_wrapper():
            try: self.renamer.trigger_intelligent_merge(path)
            except Exception as e: self.emit_log(f"Analysis Failed: {e}")
            finally: self.is_analyzing = False
        threading.Thread(target=_run_wrapper, daemon=True).start()

    def load_settings(self):
        cfg = os.path.join(get_run_dir(), "config.json")
        if os.path.exists(cfg):
            try:
                with open(cfg, 'r', encoding='utf-8') as f: data = json.load(f)
                if "target_path" in data: 
                    path = data["target_path"]
                    self.line_path.setText(path)
                    self.file_manager.base_path = path
                    self.file_manager.refresh_targets()
                    QTimer.singleShot(1000, self.run_intelligent_merge)
                if "import_root" in data:
                    self.archiver.import_root = data["import_root"]
                    self.file_manager.lbl_imp_root.setText(data["import_root"])
                if "export_root" in data:
                    self.archiver.export_root = data["export_root"]
                    self.file_manager.lbl_exp_root.setText(data["export_root"])
                if "export_docs_root" in data:
                    self.archiver.export_docs_root = data["export_docs_root"]
                    self.file_manager.lbl_exp_docs_root.setText(data["export_docs_root"])
                # API 키는 keyring에서 로드 (core/config.py에서 자동 처리)
                from core.config import api_key as loaded_api_key
                self.emit_log("API Key loaded." if loaded_api_key else "API Key missing.")
                if "browser_home_path" in data:
                    self.file_manager.browser_home_path = data["browser_home_path"]
                # 미니 윈도우 위치 로드
                if "mini_window_pos" in data:
                    self.mini_window_saved_pos = data["mini_window_pos"]
                else:
                    self.mini_window_saved_pos = None
            except Exception as e: print(f"Settings Load Error: {e}")

    def save_settings(self):
        cfg = os.path.join(get_run_dir(), "config.json")
        try:
            if os.path.exists(cfg):
                with open(cfg, 'r', encoding='utf-8') as f: data = json.load(f)
            else: data = {}
            data["target_path"] = self.line_path.text()
            if self.archiver.import_root: data["import_root"] = self.archiver.import_root
            if self.archiver.export_root: data["export_root"] = self.archiver.export_root
            if self.archiver.export_docs_root: data["export_docs_root"] = self.archiver.export_docs_root
            if hasattr(self.file_manager, 'browser_home_path') and self.file_manager.browser_home_path:
                data["browser_home_path"] = self.file_manager.browser_home_path
            # 미니 윈도우 위치 저장
            if hasattr(self, 'mini_window_saved_pos') and self.mini_window_saved_pos:
                data["mini_window_pos"] = self.mini_window_saved_pos
            with open(cfg, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Settings save error: {e}")
    
    def _show_mini_window(self):
        if hasattr(self, 'mini_window') and self.mini_window: self.mini_window.close()
        self.mini_window = QWidget()
        # Tool 플래그 제거 - 메인 윈도우가 숨겨져도 미니윈도우가 유지되도록
        self.mini_window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.mini_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.mini_window.setFixedSize(130, 36)
        
        # JARVIS HUD 스타일 프레임 (더 컴팩트)
        frame = QFrame(self.mini_window)
        frame.setGeometry(0, 0, 130, 36)
        frame.setStyleSheet("""
            QFrame { 
                background-color: rgba(5, 15, 30, 230); 
                border: 1px solid #00ffff; 
                border-radius: 8px;
            }
        """)
        
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(4)
        
        # JARVIS 라벨 (컴팩트 HUD 스타일)
        lbl = QLabel("TRADIS MH")
        lbl.setStyleSheet("""
            color: #00ffff; 
            font-weight: bold; 
            font-size: 8pt; 
            background: transparent;
            letter-spacing: 0px;
        """)
        layout.addWidget(lbl)
        layout.addStretch()
        
        # 복원 버튼 (macOS 스타일 원형 - 초록)
        btn_restore = QPushButton("")
        btn_restore.setFixedSize(12, 12)
        btn_restore.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_restore.setToolTip("복원")
        btn_restore.setStyleSheet("""
            QPushButton {
                background-color: #28c840;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #1fa834;
            }
        """)
        btn_restore.clicked.connect(self._restore_from_mini)
        layout.addWidget(btn_restore)

        # 닫기 버튼 (macOS 스타일 원형 - 빨강)
        btn_close = QPushButton("")
        btn_close.setFixedSize(12, 12)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setToolTip("종료")
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #ff5f57;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #e04640;
            }
        """)
        btn_close.clicked.connect(self._close_from_mini)
        layout.addWidget(btn_close)
        
        # 드래그 이벤트 핸들러
        self.mini_window.drag_pos = None
        def mini_mouse_press(e):
             if e.button() == Qt.MouseButton.LeftButton: self.mini_window.drag_pos = e.globalPosition().toPoint()
        def mini_mouse_move(e):
             if self.mini_window.drag_pos:
                 delta = e.globalPosition().toPoint() - self.mini_window.drag_pos
                 self.mini_window.move(self.mini_window.pos() + delta)
                 self.mini_window.drag_pos = e.globalPosition().toPoint()
        
        def mini_mouse_release(e):
            self.mini_window.drag_pos = None
            # 드래그 후 위치 저장 (화면 밖으로만 안 나가도록)
            pos = self.mini_window.pos()
            screen = QApplication.primaryScreen().geometry()
            available = QApplication.primaryScreen().availableGeometry()
            # 화면 밖으로 나가지 않도록 보정 (작업 표시줄과 격치게 놓을 수 있음)
            x = max(0, min(pos.x(), screen.width() - 130))
            y = max(0, min(pos.y(), screen.height() - 36))
            self.mini_window.move(x, y)
            self.mini_window_saved_pos = {"x": x, "y": y}
        
        self.mini_window.mousePressEvent = mini_mouse_press
        self.mini_window.mouseMoveEvent = mini_mouse_move
        self.mini_window.mouseReleaseEvent = mini_mouse_release
        
        # 저장된 위치 또는 기본 위치에 배치
        screen = QApplication.primaryScreen().geometry()
        available = QApplication.primaryScreen().availableGeometry()
        if hasattr(self, 'mini_window_saved_pos') and self.mini_window_saved_pos:
            x = self.mini_window_saved_pos["x"]
            y = self.mini_window_saved_pos["y"]
            # 화면 밖으로 나가지 않도록 보정
            x = max(0, min(x, screen.width() - 130))
            y = max(0, min(y, screen.height() - 36))
            self.mini_window.move(x, y)
        else:
            self.mini_window.move(available.right() - 145, available.bottom() - 50)
        self.hide()
        self.mini_window.show()
    
    def _restore_from_mini(self):
        if hasattr(self, 'mini_window') and self.mini_window:
            self.mini_window.close()
            self.mini_window = None
        self.show()
        self.activateWindow()
    
    def _close_from_mini(self):
        """미니 윈도우에서 앱 완전 종료"""
        if hasattr(self, 'mini_window') and self.mini_window:
            self.mini_window.close()
            self.mini_window = None
        # 설정 저장 및 모니터링 중지
        try:
            self.stop_monitoring()
            self.save_settings()
        except Exception:
            pass
        # 앱 전체 종료
        QApplication.quit()

    def _start_everything(self):
        try:
            result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Everything.exe"], capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            if "Everything.exe" in result.stdout: return
            
            everything_paths = [
                os.path.join(get_run_dir(), "Everything.exe"),
                r"C:\Program Files\Everything\Everything.exe",
                r"C:\Program Files (x86)\Everything\Everything.exe",
            ]
            for path in everything_paths:
                if os.path.exists(path):
                    subprocess.Popen([path, "-startup"], creationflags=subprocess.CREATE_NO_WINDOW)
                    return
        except (FileNotFoundError, OSError): pass

    # 메일 모니터링 기능 완전히 제거됨
    
    # 메일 모니터링 기능(VERONICA UI 업데이트) 제거됨
    def _on_rk_status_change(self, status: AutomationStatus, message: str):
        """ReadyKorea 자동화 상태 변경 콜백 (스레드 안전)"""
        # QTimer.singleShot을 사용하여 메인 스레드에서 UI 업데이트
        def update_ui():
            if hasattr(self.file_manager, 'rk_automation_status'):
                status_text = f"● {status.value}"
                color = "#888"
                
                if status == AutomationStatus.COMPLETED:
                    color = "#00ff00"
                elif status == AutomationStatus.ERROR:
                    color = "#ff3333"
                elif status in [AutomationStatus.CONNECTING, AutomationStatus.SEARCHING, 
                               AutomationStatus.SELECTING, AutomationStatus.EDITING_HEADER,
                               AutomationStatus.EDITING_DETAIL]:
                    color = "#00ddff"
                
                self.file_manager.rk_automation_status.setText(status_text)
                self.file_manager.rk_automation_status.setStyleSheet(f"color: {color}; font-weight: bold;")
            
            # 로그 추가
            self._add_rk_log(f"[{status.value}] {message}")
        
        QTimer.singleShot(0, update_ui)
    
    def _add_rk_log(self, message: str):
        """ReadyKorea 자동화 로그 추가"""
        if hasattr(self.file_manager, 'rk_log'):
            import datetime
            timestamp = datetime.datetime.now().strftime('%H:%M:%S')
            self.file_manager.rk_log.append(f"[{timestamp}] {message}")
            self.file_manager.rk_log.verticalScrollBar().setValue(
                self.file_manager.rk_log.verticalScrollBar().maximum()
            )
    
    def _run_readykorea_automation(self):
        """ReadyKorea 자동 입력 실행"""
        # 버튼이 활성화되지 않은 상태인지 확인
        if not getattr(self.file_manager, '_rk_button_enabled', False):
            from gui.dialogs import JarvisMessageBox
            JarvisMessageBox.warning(self, "데이터 없음", "파싱된 수출 데이터가 없습니다.\n먼저 메일을 감지하거나 테스트를 실행하세요.")
            return
        
        if not self.last_export_data:
            from gui.dialogs import JarvisMessageBox
            JarvisMessageBox.warning(self, "데이터 없음", "파싱된 수출 데이터가 없습니다.\n먼저 메일을 감지하거나 테스트를 실행하세요.")
            return
        
        # ExportData를 ExportInputData로 변환
        input_data = ExportInputData.from_export_data(self.last_export_data)
        
        self._add_rk_log("자동 입력 시작...")
        
        def run_automation():
            try:
                result = self.rk_automation.run_automation(input_data)
                if result:
                    QTimer.singleShot(0, lambda: self._add_rk_log("✅ 자동 입력 완료!"))
                else:
                    QTimer.singleShot(0, lambda: self._add_rk_log("❌ 자동 입력 실패"))
            except Exception as e:
                error_msg = str(e)
                QTimer.singleShot(0, lambda: self._add_rk_log(f"❌ 오류: {error_msg}"))
            finally:
                QTimer.singleShot(0, lambda: self.file_manager.btn_rk_auto_input.setEnabled(True))
        
        threading.Thread(target=run_automation, daemon=True).start()
    
    def _test_readykorea_connection(self):
        """ReadyKorea 연결 테스트"""
        self._add_rk_log("ReadyKorea 연결 테스트 중...")
        
        def test_connection():
            result = self.rk_automation.connect()
            if result:
                QTimer.singleShot(0, lambda: self._add_rk_log("✅ ReadyKorea 연결 성공!"))
            else:
                QTimer.singleShot(0, lambda: self._add_rk_log("❌ ReadyKorea를 찾을 수 없습니다. 프로그램이 실행 중인지 확인하세요."))
        
        threading.Thread(target=test_connection, daemon=True).start()
    
    def _send_reply_email(self):
        """수출신고필증 첨부 답장 메일 발송"""
        self.emit_log("[Mail] _send_reply_email called")  # 디버그 로그
        from gui.dialogs import JarvisMessageBox
        
        # 1. 데이터 확인
        if not self.last_mail_info:
            self.emit_log("[Mail] last_mail_info is None")  # 디버그 로그
            JarvisMessageBox.warning(self, "메일 정보 없음", "답장할 메일 정보가 없습니다.")
            return
        
        if not self.last_export_data:
            JarvisMessageBox.warning(self, "데이터 없음", "파싱된 수출 데이터가 없습니다.")
            return
        
        # 2. config에서 한비로 설정 로드
        try:
            config_path = os.path.join(get_run_dir(), 'config.json')
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            hanbiro = config.get('hanbiro_mail', {})
            email_addr = hanbiro.get('email', '')
            # 이메일 비밀번호는 keyring에서 로드
            import keyring
            email_pw = keyring.get_password("TRADIS_MH", "email_password") or ''
            if not email_addr or not email_pw:
                JarvisMessageBox.warning(self, "설정 오류", "한비로 메일 설정이 없습니다.")
                return

            # 사용자 요청에 따라 발신자 주소 동적 생성 (ID + @ihaedo.com)
            user_id = email_addr.split('@')[0]

            email_config = EmailConfig(
                smtp_server=hanbiro.get('smtp_server', 'raeon.hanbiro.net'),
                smtp_port=int(hanbiro.get('smtp_port', 465)),
                imap_server=hanbiro.get('imap_server', 'raeon.hanbiro.net'),
                imap_port=int(hanbiro.get('imap_port', 993)),
                email=email_addr,
                password=email_pw,
                sender_email=f"{user_id}@ihaedo.com"
            )
        except Exception as e:
            JarvisMessageBox.critical(self, "설정 오류", f"설정 로드 실패: {e}")
            return
        
        # 3. 수출신고필증 파일 찾기 (자동 이름변경 폴더에서)
        folder_path = self.line_path.text()
        if not folder_path:
            JarvisMessageBox.warning(self, "폴더 없음", "감시 폴더가 설정되지 않았습니다.")
            return
        
        # 송품장 번호 = 오늘 날짜 (YYYY.MM.DD) → 수출신고필증 ID
        from datetime import datetime
        identifier = datetime.now().strftime("%Y.%m.%d")
        
        self.mail_sender = ExportMailSender(email_config, log_callback=self.emit_log)
        attachment_path = self.mail_sender.find_export_declaration(folder_path, identifier)
        
        if not attachment_path:
            JarvisMessageBox.warning(self, "파일 없음", f"수출신고필증을 찾을 수 없습니다.\n폴더: {folder_path}\nID: {identifier}")
            return
        
        # 4. 답장 메일 발송
        # ExportMailInfo에는 'sender' 필드에 발신자 정보가 있음 ("이름 <이메일>" 또는 "이메일")
        to_email = getattr(self.last_mail_info, 'sender', '')
        original_to = getattr(self.last_mail_info, 'to', '')  # 원본 메일의 받는 사람
        original_cc = getattr(self.last_mail_info, 'cc', '')  # 원본 메일의 참조
        subject = getattr(self.last_mail_info, 'subject', '수출 요청')
        message_id = getattr(self.last_mail_info, 'message_id', None)
        
        if not to_email:
            JarvisMessageBox.warning(self, "수신자 없음", "답장할 이메일 주소가 없습니다.")
            return
        
        # CC 조합: 원본 To + 원본 CC (중복 제거)
        from email.utils import getaddresses
        cc_candidates = []
        if original_to:
            cc_candidates.append(original_to)
        if original_cc:
            cc_candidates.append(original_cc)
        
        # 이메일 주소만 추출 (이름 제외)
        all_cc_addrs = getaddresses(cc_candidates)
        unique_emails = []
        seen = set()
        for name, addr in all_cc_addrs:
            addr_lower = addr.lower()
            # 중복 제거 + 발신자(to_email) 본인은 CC에서 제외
            if addr_lower and addr_lower not in seen:
                # to_email에서도 이메일 주소만 추출하여 비교
                to_addrs = getaddresses([to_email])
                to_email_only = to_addrs[0][1].lower() if to_addrs else ''
                if addr_lower != to_email_only:
                    unique_emails.append(f"{name} <{addr}>" if name else addr)
                    seen.add(addr_lower)
        
        cc_email = ", ".join(unique_emails)
        
        log_msg = f"{to_email} (CC: {cc_email})" if cc_email else to_email
        self.emit_log(f"[Mail] 답장 메일 발송 시작: {log_msg}")
        self._add_rk_log(f"📧 답장 메일 발송 중... → {log_msg}")
        
        def send_mail():
            try:
                result = self.mail_sender.send_reply(
                    to_email=to_email,
                    subject=subject,
                    attachment_path=attachment_path,
                    original_message_id=message_id,
                    cc=cc_email
                )
                if result:
                    QTimer.singleShot(0, lambda: self._add_rk_log("✅ 답장 메일 발송 완료!"))
                    QTimer.singleShot(0, lambda: JarvisMessageBox.information(self, "성공", "답장 메일이 발송되었습니다."))
                else:
                    QTimer.singleShot(0, lambda: self._add_rk_log("❌ 답장 메일 발송 실패"))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._add_rk_log(f"❌ 메일 발송 오류: {e}"))
        
        threading.Thread(target=send_mail, daemon=True).start()

    def _on_mail_item_deleted_reset(self):
        """항목 삭제 시 관련 데이터 및 UI 초기화"""
        self.emit_log("[상태] 목록 항목 삭제 -> 데이터 초기화")
        
        # 1. 데이터 초기화
        self.last_export_data = None
        self.last_mail_info = None
        
        # 2. 버튼 비활성화 및 스타일 초기화 (회색)
        disabled_style = """
            QPushButton {
                background-color: rgba(30, 30, 30, 150);
                border: 1px solid #333;
                border-radius: 10px;
                color: #444;
            }
        """
        
        if hasattr(self.file_manager, 'btn_rk_auto_input'):
            self.file_manager.btn_rk_auto_input.setEnabled(False)
            self.file_manager.btn_rk_auto_input.setStyleSheet(disabled_style)
            self.file_manager._rk_button_enabled = False
            
        if hasattr(self.file_manager, 'btn_send_mail'):
            self.file_manager.btn_send_mail.setEnabled(False)
            self.file_manager.btn_send_mail.setStyleSheet(disabled_style)
            
        # 3. 파싱 결과창 클리어
        if hasattr(self.file_manager, 'export_parse_result'):
            self.file_manager.export_parse_result.clear()
            self.file_manager.export_parse_result.setText("") # 확실하게
            
        self._add_rk_log("❌ 사용자에 의해 항목 삭제됨 (초기화)")

    # ──────────── 수출신고필증 마킹 ────────────

    def _on_export_declaration_renamed(self, company, invoice_id, filepath):
        """수출신고필증 이름변경 콜백 (워커 스레드에서 호출됨)"""
        # 시그널로 메인 스레드에 전달
        self.marking_request_signal.emit(company, invoice_id, filepath)

    def _show_marking_popup(self, company, invoice_id, filepath):
        """마킹 팝업 표시 (메인 스레드)"""
        # 대기열에 추가
        self.marking_queue.append((company, invoice_id, filepath))
        self.emit_log(f"[마킹] 대기열 추가: {company}({invoice_id})")
        
        # 현재 팝업이 없으면 바로 표시
        if not self.marking_popup_active:
            self._process_next_marking()

    def _process_next_marking(self):
        """대기열의 다음 마킹 팝업 처리"""
        if not self.marking_queue:
            self.marking_popup_active = False
            # 모든 마킹 완료 → 카드 새로고침 (marked_data 반영)
            if self.marked_data:
                self.rename_trigger_signal.emit()
            return
        
        self.marking_popup_active = True
        company, invoice_id, filepath = self.marking_queue.pop(0)
        
        export_docs_root = getattr(self.archiver, 'export_docs_root', '') or ''
        
        popup = MarkingPopup(
            parent=self,
            company=company,
            invoice_id=invoice_id,
            filepath=filepath,
            export_docs_root=export_docs_root
        )
        
        result = popup.exec()
        
        if result and not popup.was_skipped and popup.marked_files:
            self.marked_data[invoice_id] = popup.marked_files
            file_names = [f['name'] for f in popup.marked_files]
            self.emit_log(f"[마킹] {company}({invoice_id}) → {len(popup.marked_files)}개 파일 마킹: {', '.join(file_names)}")
        else:
            self.emit_log(f"[마킹] {company}({invoice_id}) → 건너뜀")
        
        # 대기열에 다음 항목이 있으면 처리
        QTimer.singleShot(300, self._process_next_marking)

    # ── 관리자 모드 ──────────────────────────────────────────

    def _on_admin_unlocked(self):
        """관리자 잠금 해제 → navbar에 일정/통관/보고 버튼 추가"""
        self.license_tier = "admin"
        self._save_license_tier("admin")

        # navbar에 버튼 추가 (SETTINGS 앞에 삽입)
        admin_tabs = [
            ("일정", "일\n정", "#00ff88"),
            ("통관", "통\n관", "#ffa500"),
            ("REPORT", "보\n고", "#ff88ff"),
        ]
        navbar_layout = self.navbar.layout()
        navbar_layout.takeAt(navbar_layout.count() - 1)  # stretch 제거
        settings_item = navbar_layout.takeAt(navbar_layout.count() - 1)
        settings_btn = settings_item.widget()

        for tab_name, label, color in admin_tabs:
            if tab_name in self.nav_buttons:
                continue
            btn = QPushButton(label)
            btn.setFixedSize(30, 45)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("tab_name", tab_name)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(5, 20, 35, 120);
                    border: 1px solid rgba(0, 255, 255, 80);
                    border-radius: 6px;
                    color: rgba(255, 255, 255, 200);
                    text-align: center;
                    padding-top: 2px;
                }}
                QPushButton:hover {{
                    background-color: rgba(0, 255, 255, 30);
                    border: 1px solid {color};
                    color: #ffffff;
                }}
                QPushButton:checked {{
                    background-color: rgba(0, 255, 255, 50);
                    border: 1px solid {color};
                    border-left: 3px solid {color};
                    color: {color};
                    font-weight: bold;
                }}
            """)
            btn.clicked.connect(lambda checked, name=tab_name: self._on_navbar_clicked(name))
            navbar_layout.addWidget(btn)
            self.nav_buttons[tab_name] = btn

        navbar_layout.addWidget(settings_btn)
        navbar_layout.addStretch()
        self.emit_log("[관리자] 일정/통관/보고 탭이 활성화되었습니다.")

    def _save_license_tier(self, tier):
        """config.json에 라이선스 등급 저장"""
        try:
            cfg = os.path.join(get_run_dir(), "config.json")
            if os.path.exists(cfg):
                with open(cfg, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {}
            data["license_tier"] = tier
            with open(cfg, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"License tier save error: {e}")

    # ── 자동 업데이트 ──────────────────────────────────────────

    def _check_update_async(self):
        """백그라운드에서 업데이트 확인"""
        def _check():
            result = check_for_update()
            self.update_check_done.emit(result)
        threading.Thread(target=_check, daemon=True).start()

    def _on_update_check_result(self, result):
        """업데이트 확인 결과 처리 (메인 스레드)"""
        if not result.get("available"):
            self.emit_log(f"[업데이트] 최신 버전입니다. (v{__version__})")
            return

        new_ver = result["version"]
        notes = result.get("notes", "")
        download_url = result["download_url"]

        from gui.dialogs import JarvisMessageBox
        msg = f"새 버전 v{new_ver}이 있습니다.\n\n{notes[:200]}\n\n업데이트하시겠습니까?"
        if not JarvisMessageBox.question(self, "업데이트 알림", msg):
            self.emit_log(f"[업데이트] v{new_ver} 업데이트를 건너뛰었습니다.")
            return

        self._start_download(download_url, new_ver)

    def _start_download(self, url, new_ver):
        """업데이트 다운로드 시작 (진행 다이얼로그)"""
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import Qt

        self._update_progress = QProgressDialog(
            f"TRADIS MH v{new_ver} 다운로드 중...", "취소", 0, 100, self
        )
        self._update_progress.setWindowTitle("업데이트")
        self._update_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._update_progress.setMinimumWidth(350)
        self._update_progress.setAutoClose(False)
        self._update_progress.show()

        self._download_url = url
        self._new_ver = new_ver

        def _do_download():
            def on_progress(downloaded, total):
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    # 메인 스레드에서 UI 업데이트
                    QTimer.singleShot(0, lambda p=pct: self._update_download_progress(p))

            path = download_update(url, progress_callback=on_progress)
            QTimer.singleShot(0, lambda: self._on_download_complete(path))

        threading.Thread(target=_do_download, daemon=True).start()

    def _update_download_progress(self, pct):
        """다운로드 진행률 업데이트"""
        if hasattr(self, '_update_progress') and self._update_progress:
            if self._update_progress.wasCanceled():
                return
            self._update_progress.setValue(pct)

    def _on_download_complete(self, tmp_path):
        """다운로드 완료 처리"""
        if hasattr(self, '_update_progress') and self._update_progress:
            self._update_progress.close()
            self._update_progress = None

        if not tmp_path:
            from gui.dialogs import JarvisMessageBox
            JarvisMessageBox.warning(self, "업데이트 실패", "다운로드에 실패했습니다.\n다음에 다시 시도해주세요.")
            return

        self.emit_log(f"[업데이트] v{self._new_ver} 다운로드 완료. 재시작합니다...")

        if apply_update(tmp_path):
            # EXE 교체 bat가 시작됨 → 현재 앱 종료
            QApplication.quit()
        else:
            from gui.dialogs import JarvisMessageBox
            JarvisMessageBox.warning(self, "업데이트", "개발 모드에서는 자동 업데이트가 지원되지 않습니다.")



if __name__ == "__main__":
    instance_socket = check_single_instance()
    if not instance_socket:
        temp_app = QApplication(sys.argv)
        QMessageBox.warning(None, "중복 실행", "TRADIS MH가 이미 실행 중입니다.")
        sys.exit(0)

    app = QApplication(sys.argv)
    SKIP_INTRO = True 
    
    if SKIP_INTRO:
        window = JarvisGUI()
        window.show()
        window.start_bg_animation()
        window._instance_lock = instance_socket
    else:
        intro = IntroWindow()
        intro.show()
        window = JarvisGUI()
        intro.finished.connect(window.show)
        intro.finished.connect(window.start_bg_animation)
        window._instance_lock = instance_socket
    
    sys.exit(app.exec())
