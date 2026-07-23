# JARVIS Auto Renamer - Main Application
# 리팩토링된 메인 파일 (모듈화 적용됨)

import sys
import os

# Qt DPI 경고 해결: Qt가 DPI 인식 설정을 시도하기 전에 비활성화
# "SetProcessDpiAwarenessContext() failed" 경고 억제
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"

# Chrome/Edge 메모리 누수 방지: PyQt의 Windows UI Automation 접근성 비활성화
# PyQt6 앱이 실행되면 Windows가 UI Automation 제공자로 등록하고,
# 같은 세션의 Chrome이 접근성 이벤트를 수신하여 내부 Accessibility Tree가
# 지속적으로 확장되며 메모리가 증가하는 현상을 차단합니다.
os.environ["QT_ACCESSIBILITY"] = "0"
import json
import threading
import datetime
import subprocess
# keyboard, pyperclip: 지연 로딩 (_setup_global_hotkeys에서 import)

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QGridLayout,
                             QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QFrame, QLineEdit, QTextEdit, QDialog,
                             QFileDialog, QMessageBox, QScrollArea, QGraphicsOpacityEffect,
                             QStackedWidget, QSizePolicy)
from PyQt6.QtCore import (Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve,
                          QPoint, QParallelAnimationGroup, QEvent, QSize)
from PyQt6.QtGui import QPixmap, QFont, QIcon, QColor

# Internal Modules (Logic)
from auto_rename import AutoRenamer, check_single_instance, set_api_key, Archiver
# calendar_manager: 지연 로딩 (init_ui에서 import)
from core.config import get_config_path

# Export Automation Modules: 지연 로딩 (관리자 전용 기능)


# GUI Modules (Refactored)
from gui.styles import GLOBAL_STYLESHEET
from gui.claude_theme import C as CT, APP_STYLESHEET, SIDE_TAB_STYLE
from gui.utils import resource_path, get_run_dir
from gui.widgets import GlassFrame, NeonButton
from gui.mk3_widgets import MK3ScheduleOnlyWidget, MK3MemoOnlyWidget
from gui.dialogs import IntroWindow, GroupCard
from gui.panels import FileManagerWidget
from gui.jarvis_toast import get_toast_handler, show_custom_toast  # [NEW] Custom Toast Imports
from version import __version__, APP_NAME
from updater import check_for_update, download_update, apply_update



class JarvisGUI(QMainWindow):
    # Signals for thread-safe UI updates
    log_signal = pyqtSignal(str)
    merge_signal = pyqtSignal(dict)
    merge_complete_signal = pyqtSignal()  # 병합 완료 시 emit
    shipping_search_signal = pyqtSignal(str, str)  # 선적서류 검색 (bl_number, target_folder)
    merge_verify_signal = pyqtSignal(object)  # 병합 검증 실패 팝업 요청
    move_failed_signal = pyqtSignal(list)  # 파일 이동 실패 알림 [(name, reason)]
    undo_toast_signal = pyqtSignal(object)  # 정리 완료 → 되돌리기 토스트 {id, folder_name, kind, file_count}
    rename_trigger_signal = pyqtSignal()  # 파일 이름 변경 완료 시 emit (디바운싱 트리거)
    export_update_signal = pyqtSignal(object)  # 수출 자동화 UI 업데이트용
    update_check_done = pyqtSignal(dict)  # 업데이트 확인 완료 시그널
    download_progress_signal = pyqtSignal(int)  # 다운로드 진행률 시그널
    download_complete_signal = pyqtSignal(object)  # 다운로드 완료 시그널 (path or None)

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
        
        # 카드 [파일 추가] 버튼이 사용하는 첨부 데이터 저장소
        self.marked_data = {}  # {invoice_id: [{'name': str, 'path': str, 'icon': str}, ...]}
        
        # 메일 모니터 초기화 (기능 제거됨)
        self.mail_monitor = None
        
        # ReadyKorea 자동화 초기화 (지연 로딩)
        self.rk_automation = None
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
        self.shipping_search_signal.connect(self._on_shipping_search)
        self.merge_verify_signal.connect(self._on_merge_verify_failed)
        self.move_failed_signal.connect(self._on_move_failed)
        self.undo_toast_signal.connect(self._show_undo_toast)
        self.rename_trigger_signal.connect(self.trigger_debounced_refresh)
        # 메일 모니터링 UI 자동 갱신 (기능 제거됨)
        # self.export_update_signal.connect(self._update_veronica_ui)
        
        # ReadyKorea 버튼 시그널 연결 (setup_right_panel에서 이미 연결됨 - 중복 제거)
        # 주의: rk_auto_input_clicked, send_mail_clicked는 setup_right_panel()에서 연결됨
        self.file_manager.item_deleted.connect(self._on_mail_item_deleted_reset) # 목록 삭제 시 초기화
        self.file_manager.admin_unlocked.connect(self._on_admin_unlocked)  # 관리자 잠금 해제
        self.file_manager.settings_changed.connect(self.save_settings)  # 폴더 설정 변경 즉시 저장
        self.file_manager.startup_guide_requested.connect(self._show_startup_guide)  # 시작 가이드 재표시
        
        # Everything 자동 시작 (검색 기능 활성화) - 비동기 실행으로 프리징 방지
        threading.Thread(target=self._start_everything, daemon=True).start()

        # 되돌리기 백업 자동 정리 (7일 경과분 휴지통 이동, 백그라운드)
        try:
            from core.merge_history import cleanup_old_async
            cleanup_old_async(log=self.emit_log)
        except Exception:
            pass
        
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
        self.download_progress_signal.connect(self._update_download_progress)
        self.download_complete_signal.connect(self._on_download_complete)
        QTimer.singleShot(3000, self._check_update_async)

        # 첫 실행 가이드 (UI 초기화 완료 후)
        QTimer.singleShot(1500, self._show_startup_guide_if_needed)

    def _show_startup_guide_if_needed(self):
        """guide_completed 플래그 확인 후 가이드 표시"""
        from core.config import load_config
        config = load_config()
        if config.get("guide_completed"):
            return
        self._show_startup_guide()

    def _show_startup_guide(self):
        """첫 실행 시작 가이드 다이얼로그"""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                     QLabel, QWidget, QGraphicsDropShadowEffect)
        from PyQt6.QtGui import QFont

        pages = [
            # === 1/4 소개 & 초기 설정 ===
            {
                "title": "TRADIS MH 소개 & 초기 설정",
                "content": (
                    "수입/수출 통관 서류를 AI로 자동 분석·분류·병합\n"
                    "PDF 투입 → AI 분석 → BL별 매칭 → 합치기 → 서버 이동\n\n"
                    "━━━ 최초 1회 설정 ━━━\n\n"
                    "① API 키\n"
                    "   상단 헤더 오른쪽 [AI] 표시 클릭\n"
                    "   → Gemini API 키 입력 (관리자 발급)\n\n"
                    "② 감시 폴더\n"
                    "   상단 헤더의 경로 표시 클릭\n"
                    "   → PDF 넣으면 자동 분석·이름 변경\n\n"
                    "③ 서버 / 선적서류 경로\n"
                    "   [설정] 탭 → 수입·수출 서버, 선적서류 폴더 지정"
                ),
            },
            # === 2/4 자동 분류 설정 ===
            {
                "title": "자동 분류 설정  ★",
                "content": (
                    "[설정] 탭에서 관리\n\n"
                    "━━━ 제외 키워드 ━━━\n"
                    "키워드 포함 파일은 AI 이름 변경 건너뜀\n"
                    "• 예: '월별납부' → 해당 파일 제외\n"
                    "• 시스템 내장: '10.', '미분류_', BL 포함 파일\n\n"
                    "━━━ 월납업체 ━━━\n"
                    "월납 계약 업체의 매출 수수료를 '해당없음'으로 표시\n"
                    "• 대상: 통관/검역/요건대행/폐기수수료, 원산지증명서 등\n"
                    "• 효과: 금액 불일치 경고 없음, 카드 완료(녹색)\n"
                    "• 업체명 부분 매칭 ('메가마트' → '(주)메가마트' 매칭)\n\n"
                    "━━━ 징수형태 ━━━\n"
                    "AI가 수입신고필증에서 자동 추출·적용\n"
                    "• 11 자진신고납부: 관/부가세 없으면 납부고지서 불필요\n"
                    "• 14 수시부과: 수입세금계산서 불필요\n"
                    "• 43 사후납부: 수입세금계산서 + 납부고지서 불필요\n"
                    "• 수동 토글: 체크리스트 항목 클릭 (BL별 저장)"
                ),
            },
            # === 3/4 사용 흐름 ===
            {
                "title": "사용 흐름",
                "content": (
                    "━━━ ① 파일 분석 ━━━\n"
                    "1. 상단 헤더의 T 로고 클릭 → 모니터링 ON (파랗게 점화)\n"
                    "2. 감시 폴더에 PDF 넣기\n"
                    "3. AI 자동 분석 → 이름 변경 → BL별 카드 생성\n\n"
                    "━━━ ② 합치기 / 폴더 정리 ━━━\n"
                    "1. 카드 헤더 클릭 → 펼치기\n"
                    "2. 서류 확인 줄 보기\n"
                    "   ● 녹색: 있음  ○ 빨강: 누락  ─ 회색: 해당없음\n"
                    "3. [합치기 실행] 또는 [폴더 정리]\n"
                    "합치기 후 선적서류 자동 검색, 더블클릭으로 열기\n\n"
                    "━━━ ③ 서버 이동 ━━━\n"
                    "우측 [Target Folders]에서 폴더 선택\n"
                    "→ [↓ 수입] / [↑ 수출] 버튼 → 자동 이동"
                ),
            },
            # === 4/4 편의 기능 ===
            {
                "title": "편의 기능",
                "content": (
                    "• 실행 로그\n"
                    "   → data\\logs 폴더에 일자별 파일로 저장\n\n"
                    "• 카드 파일 더블클릭\n"
                    "   → 기본 프로그램으로 열기\n\n"
                    "• 체크리스트 항목 클릭\n"
                    "   → 해당/해당없음 수동 토글\n\n"
                    "• 카드 우클릭 → 카드 전체 삭제\n\n"
                    "• 파일 우클릭\n"
                    "   → 경로 복사 / 이름 변경 / 삭제\n\n"
                    "• ESC 키 → 미니 윈도우 전환\n\n"
                    "• [검색] 버튼 → 파일 탐색기 (Everything)"
                ),
            },
        ]

        current_page = [0]

        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setFixedWidth(480)

        container = QWidget(dlg)
        container.setObjectName("guide_dlg")
        container.setStyleSheet("""
            #guide_dlg {
                background-color: rgba(45, 50, 60, 235);
                border: 1px solid #40464e;
                border-radius: 20px;
            }
        """)
        shadow = QGraphicsDropShadowEffect(dlg)
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(Qt.GlobalColor.black)
        container.setGraphicsEffect(shadow)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 30, 30, 24)
        layout.setSpacing(15)

        # 페이지 번호
        lbl_page = QLabel("1/5")
        lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_page.setFont(QFont("Segoe UI", 9))
        lbl_page.setStyleSheet("color: rgba(255,255,255,0.4); background: transparent;")
        layout.addWidget(lbl_page)

        # 타이틀
        lbl_title = QLabel("")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #00ffff; background: transparent;")
        layout.addWidget(lbl_title)

        # 내용
        lbl_content = QLabel("")
        lbl_content.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_content.setFont(QFont("Segoe UI", 11))
        lbl_content.setStyleSheet("color: rgba(255,255,255,0.85); background: transparent; line-height: 1.5;")
        lbl_content.setWordWrap(True)
        layout.addWidget(lbl_content)

        layout.addSpacing(10)

        # 버튼
        from PyQt6.QtWidgets import QPushButton
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        _btn_style_gray = """
            QPushButton { background-color: rgba(100,105,115,180); border: 1px solid #585c64;
                border-radius: 12px; color: #fff; padding: 8px 20px; }
            QPushButton:hover { background-color: rgba(120,125,135,200); }
        """
        _btn_style_cyan = """
            QPushButton { background-color: rgba(30,35,45,200); border: 2px solid #00d4ff;
                border-radius: 12px; color: #00d4ff; padding: 8px 20px; }
            QPushButton:hover { background-color: rgba(0,212,255,40); border-color: #00ffff; color: #00ffff; }
        """

        btn_skip = QPushButton("건너뛰기")
        btn_skip.setFixedHeight(40)
        btn_skip.setFont(QFont("Segoe UI", 10))
        btn_skip.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_skip.setStyleSheet(_btn_style_gray)
        btn_row.addWidget(btn_skip)

        btn_prev = QPushButton("이전")
        btn_prev.setFixedHeight(40)
        btn_prev.setFont(QFont("Segoe UI", 10))
        btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_prev.setStyleSheet(_btn_style_gray)
        btn_row.addWidget(btn_prev)

        btn_next = QPushButton("다음")
        btn_next.setFixedHeight(40)
        btn_next.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_next.setStyleSheet(_btn_style_cyan)
        btn_row.addWidget(btn_next)

        layout.addLayout(btn_row)

        def update_page():
            p = pages[current_page[0]]
            lbl_page.setText(f"{current_page[0]+1}/{len(pages)}")
            lbl_title.setText(p["title"])
            lbl_content.setText(p["content"])
            btn_prev.setVisible(current_page[0] > 0)
            if current_page[0] == len(pages) - 1:
                btn_next.setText("완료")
            else:
                btn_next.setText("다음")

        def on_next():
            if current_page[0] >= len(pages) - 1:
                _save_guide_completed()
                dlg.accept()
            else:
                current_page[0] += 1
                update_page()

        def on_prev():
            if current_page[0] > 0:
                current_page[0] -= 1
                update_page()

        def on_skip():
            _save_guide_completed()
            dlg.reject()

        def _save_guide_completed():
            try:
                cfg_path = get_config_path()
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                else:
                    data = {}
                data["guide_completed"] = True
                tmp = cfg_path + ".tmp"
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                os.replace(tmp, cfg_path)
            except Exception:
                pass

        btn_next.clicked.connect(on_next)
        btn_prev.clicked.connect(on_prev)
        btn_skip.clicked.connect(on_skip)

        update_page()
        dlg.exec()
        dlg.deleteLater()  # 닫힌 뒤 메인 창 자식으로 남지 않게 정리

    def _migrate_credentials_to_keyring(self):
        """기존 config.json의 민감정보를 Windows Credential Manager로 이동 (최초 1회)"""
        try:
            import keyring
            cfg_path = get_config_path()
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
            cfg_path = get_config_path()
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
        # Apply global stylesheet to the whole window (기존 JARVIS 베이스)
        # Claude Design warm-dark 오버라이드는 #OuterContainer에 직접 적용한다.
        self.setStyleSheet(GLOBAL_STYLESHEET + f"""
            #OuterContainer {{
                background-color: {CT["bg_0"]};
                border: 1px solid {CT["border_soft"]};
                border-radius: 14px;
            }}

            /* 스크롤바 — Claude Design (레거시 네온 그라데이션 오버라이드) */
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(106, 110, 118, 90);
                border-radius: 4px;
                min-height: 36px;
            }}
            QScrollBar:vertical:hover {{ background: transparent; }}
            QScrollBar::handle:vertical:hover {{ background: rgba(158, 161, 168, 140); }}
            QScrollBar::handle:vertical:pressed {{ background: rgba(158, 161, 168, 180); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px; background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                border: none;
                background: transparent;
                height: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: rgba(106, 110, 118, 90);
                border-radius: 4px;
                min-width: 36px;
            }}
            QScrollBar:horizontal:hover {{ background: transparent; }}
            QScrollBar::handle:horizontal:hover {{ background: rgba(158, 161, 168, 140); }}
            QScrollBar::handle:horizontal:pressed {{ background: rgba(158, 161, 168, 180); }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px; background: none;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """)

        # Shadow wrapper: 중앙 위젯을 감싸고 외곽에 패딩을 둬서 drop shadow가 렌더될 공간 확보
        _shadow_wrapper = QWidget(self)
        _shadow_wrapper.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        _wrap_layout = QVBoxLayout(_shadow_wrapper)
        _wrap_layout.setContentsMargins(22, 22, 22, 22)
        _wrap_layout.setSpacing(0)

        # Outer container for rounded corners (컨텐츠 루트)
        self.outer_container = QFrame()
        self.outer_container.setObjectName("OuterContainer")
        self.outer_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _wrap_layout.addWidget(self.outer_container)
        self.setCentralWidget(_shadow_wrapper)

        # 드롭 섀도 (맥 스타일 — 테두리 대신 부드러운 외곽 그림자)
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtGui import QColor
        _shadow = QGraphicsDropShadowEffect(self.outer_container)
        _shadow.setBlurRadius(40)
        _shadow.setOffset(0, 6)
        _shadow.setColor(QColor(0, 0, 0, 200))
        self.outer_container.setGraphicsEffect(_shadow)
        
        # Total Layout
        total_layout = QVBoxLayout(self.outer_container)
        total_layout.setContentsMargins(0, 0, 0, 10)
        total_layout.setSpacing(0)
        
        # 0. Custom Title Bar — macOS 트래픽 라이트 (좌측 정렬: close|min|max)
        self.title_bar = QFrame()
        self.title_bar.setFixedHeight(38)
        self.title_bar.setStyleSheet(f"""
            background-color: {CT["bg_1"]};
            border: none;
            border-bottom: 1px solid {CT["border_soft"]};
        """)
        tb_layout = QHBoxLayout(self.title_bar)
        tb_layout.setContentsMargins(18, 0, 18, 0)
        tb_layout.setSpacing(8)

        # 닫기 (빨간색)
        self.btn_close = QPushButton("")
        self.btn_close.setFixedSize(13, 13)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet("""
            QPushButton { background-color: #ff5f57; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #e04640; }
        """)
        self.btn_close.clicked.connect(self.close)
        self.btn_close.setToolTip("닫기")
        tb_layout.addWidget(self.btn_close)

        # 최소화 (노란색)
        self.btn_minimize = QPushButton("")
        self.btn_minimize.setFixedSize(13, 13)
        self.btn_minimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minimize.setStyleSheet("""
            QPushButton { background-color: #febc2e; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #e5a520; }
        """)
        self.btn_minimize.clicked.connect(self._show_mini_window)
        self.btn_minimize.setToolTip("최소화")
        tb_layout.addWidget(self.btn_minimize)

        # 최대화/복원 (녹색)
        self.btn_maximize = QPushButton("")
        self.btn_maximize.setFixedSize(13, 13)
        self.btn_maximize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_maximize.setStyleSheet("""
            QPushButton { background-color: #28c840; border: none; border-radius: 6px; }
            QPushButton:hover { background-color: #1fa030; }
        """)
        self.btn_maximize.clicked.connect(self._toggle_maximize)
        self.btn_maximize.setToolTip("최대화/복원")
        tb_layout.addWidget(self.btn_maximize)

        tb_layout.addStretch(1)

        # 중앙 TRADIS 타이틀 (Claude Design)
        self.lbl_titlebar_brand = QLabel("TRADIS")
        self.lbl_titlebar_brand.setStyleSheet(f"""
            color: {CT['fg_1']};
            font-size: 9pt;
            font-weight: 600;
            letter-spacing: 3px;
            background: transparent;
            border: none;
        """)
        self.lbl_titlebar_brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tb_layout.addWidget(self.lbl_titlebar_brand)

        tb_layout.addStretch(1)

        # 우측 균형을 위해 더미 스페이서 (traffic lights 3개 폭 + 간격 만큼)
        _rspacer = QWidget()
        _rspacer.setFixedWidth(13 * 3 + 8 * 2)
        tb_layout.addWidget(_rspacer)

        total_layout.addWidget(self.title_bar)
        
        # 1. Main Content Grid (3 Columns: LeftStack, Right, NavBar) — Claude Design 3-col
        content_widget = QWidget()
        self.main_layout = QGridLayout(content_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setHorizontalSpacing(0)
        self.main_layout.setVerticalSpacing(0)

        self.main_layout.setColumnStretch(0, 15)  # Left content stack
        self.main_layout.setColumnStretch(1, 5)   # Right panel
        self.main_layout.setColumnStretch(2, 0)   # NavBar

        # --- LEFT CONTENT STACK (QStackedWidget) ---
        self.left_content_stack = QStackedWidget()

        # Page 0: 정산 (left_panel + middle_panel)
        mk1_page = QWidget()
        mk1_layout = QHBoxLayout(mk1_page)
        mk1_layout.setContentsMargins(0, 0, 0, 0)
        mk1_layout.setSpacing(0)

        # Claude Design warm dark 2컬럼 — main / targets (사이드바 제거, 내용은 중앙 헤더로 이동)
        _main_style = f"""
            QFrame#MainPanel {{
                background-color: {CT["bg_0"]};
                border: none;
            }}
        """
        _targets_style = f"""
            QFrame#TargetsPanel {{
                background-color: {CT["bg_1"]};
                border: none;
                border-left: 1px solid {CT["border_soft"]};
            }}
        """

        # 호환용 숨김 위젯 + 로그 영역 생성 (구 사이드바 잔여 역할)
        self.setup_left_panel()

        self.middle_panel = QFrame()
        self.middle_panel.setObjectName("MainPanel")
        self.middle_panel.setStyleSheet(_main_style)
        self.setup_middle_panel()
        mk1_layout.addWidget(self.middle_panel, stretch=1)

        self.left_content_stack.addWidget(mk1_page)  # index 0
        self.main_layout.addWidget(self.left_content_stack, 0, 0)

        # --- RIGHT PANEL (FileManager / Targets) ---
        self.right_panel = QFrame()
        self.right_panel.setObjectName("TargetsPanel")
        self.right_panel.setStyleSheet(_targets_style)
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
        """오른쪽 세로 NavBar — Claude Design (icon above label, 세로 스택)"""
        from gui.claude_icons import pixmap as _icpx
        from PyQt6.QtCore import QSize
        from PyQt6.QtWidgets import QToolButton

        self.navbar = QWidget()
        self.navbar.setFixedWidth(58)
        navbar_layout = QVBoxLayout(self.navbar)
        navbar_layout.setContentsMargins(0, 6, 0, 14)
        navbar_layout.setSpacing(4)

        self.navbar.setObjectName("NavBar")
        self.navbar.setStyleSheet(f"""
            QWidget#NavBar {{
                background-color: {CT["bg_1"]};
                border-left: 1px solid {CT["border_soft"]};
                border-right: none;
                border-top: none;
                border-bottom: none;
                border-radius: 0px;
            }}
        """)

        # NAV 헤더 라벨
        # 디자인 .side-tabs::before — NAV 라벨, opacity 0.5
        _nav_header = QLabel("NAV")
        _nav_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _nav_header.setStyleSheet(f"""
            color: rgba(106, 110, 118, 128);
            font-size: 7.5pt;
            font-weight: 700;
            letter-spacing: 3.5px;
            background: transparent;
            border: none;
            padding: 6px 0 10px 0;
        """)
        navbar_layout.addWidget(_nav_header)

        self.nav_buttons = {}
        tab_defs = [
            ("정산",     "정산", "Zap"),
            ("일정",     "일정", "Calendar"),
            ("통관",     "통관", "Layers"),
            ("REPORT",   "보고", "Book"),
            ("SETTINGS", "설정", "Cog"),
        ]

        admin_only_tabs = {"일정", "통관", "REPORT"}

        # 디자인 .side-tab: padding 14px 4px, border-radius 10, font 11.5px, letter-spacing 0.02em
        _nav_btn_css = f"""
            QToolButton#SideTab {{
                background-color: transparent;
                color: {CT['fg_2']};
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 12px 4px 10px 4px;
                font-size: 8.6pt;
                font-weight: 600;
                letter-spacing: 0.4px;
            }}
            QToolButton#SideTab:hover {{
                background-color: {CT['bg_2']};
                color: {CT['fg_0']};
                border: 1px solid {CT['border_soft']};
            }}
            QToolButton#SideTab:checked {{
                background-color: {CT['accent_bg']};
                color: {CT['accent_hi']};
                border: 1px solid {CT['accent_border']};
            }}
        """

        # 디자인 .side-tab.active::before — 외부 좌측 2.5px 스트라이프 + accent glow
        # QSS는 :before 미지원 → 각 버튼 옆에 QFrame 스트라이프 위젯을 수동 배치
        for tab_name, label, icon_name in tab_defs:
            if tab_name in admin_only_tabs and self.license_tier != "admin":
                continue
            btn = QToolButton()
            btn.setText(label)
            btn.setObjectName("SideTab")
            btn.setFixedSize(44, 64)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("tab_name", tab_name)
            btn.setProperty("icon_name", icon_name)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            btn.setStyleSheet(_nav_btn_css)
            btn.setIcon(QIcon(_icpx(icon_name, size=20, color=CT['fg_2'])))
            btn.setIconSize(QSize(20, 20))
            btn.clicked.connect(lambda checked, name=tab_name: self._on_navbar_clicked(name))

            # active 스트라이프 (탭 왼쪽 외부 2.5px)
            _stripe = QFrame()
            _stripe.setFixedSize(3, 28)
            _stripe.setStyleSheet(f"""
                background-color: transparent;
                border: none;
                border-radius: 1.5px;
            """)
            btn._stripe = _stripe  # 참조 보관해 클릭 시 표시/숨김 제어

            _row = QHBoxLayout()
            _row.setContentsMargins(0, 0, 0, 0)
            _row.setSpacing(2)
            _row.addWidget(_stripe)
            _row.addWidget(btn)
            # 우측 여백 (stripe 너비 보정)
            _right_spacer = QWidget()
            _right_spacer.setFixedWidth(3)
            _row.addWidget(_right_spacer)
            navbar_layout.addLayout(_row)
            self.nav_buttons[tab_name] = btn
        
        navbar_layout.addStretch()
        self.nav_buttons["정산"].setChecked(True)
        # 초기 active 탭 아이콘을 accent 색으로 표시 + 스트라이프 활성화
        _icon_name = self.nav_buttons["정산"].property("icon_name")
        if _icon_name:
            self.nav_buttons["정산"].setIcon(QIcon(_icpx(_icon_name, size=20, color=CT['accent_hi'])))
            self.nav_buttons["정산"].setIconSize(QSize(20, 20))
        if hasattr(self.nav_buttons["정산"], '_stripe'):
            self.nav_buttons["정산"]._stripe.setStyleSheet(f"""
                background-color: {CT['accent']};
                border: none;
                border-radius: 1.5px;
            """)
        self.current_nav_tab = "정산"
        self.main_layout.addWidget(self.navbar, 0, 2)
    
    def _on_navbar_clicked(self, tab_name):
        from gui.claude_icons import pixmap as _icpx
        from PyQt6.QtCore import QSize
        for name, btn in self.nav_buttons.items():
            is_active = (name == tab_name)
            btn.setChecked(is_active)
            # 아이콘 색상도 active/idle에 맞춰 갱신
            icon_name = btn.property("icon_name")
            if icon_name:
                color = CT['accent_hi'] if is_active else CT['fg_2']
                btn.setIcon(QIcon(_icpx(icon_name, size=20, color=color)))
                btn.setIconSize(QSize(20, 20))
            # 좌측 스트라이프 (active 일 때만 accent 색, 그외 투명)
            if hasattr(btn, '_stripe'):
                if is_active:
                    btn._stripe.setStyleSheet(f"""
                        background-color: {CT['accent']};
                        border: none;
                        border-radius: 1.5px;
                    """)
                else:
                    btn._stripe.setStyleSheet("""
                        background-color: transparent;
                        border: none;
                    """)
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
        from calendar_manager import LocalScheduleManager
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
    

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._show_mini_window()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        try:
            self.stop_monitoring()
            # 메모 강제 저장 (디바운스 타이머 만료 전 유실 방지)
            if hasattr(self, 'mk3_memo_widget'):
                self.mk3_memo_widget.save_all_memos()
            if hasattr(self, 'schedule_manager'):
                self.schedule_manager.stop_reminder_loop()
            self.save_settings()
            # 보내기 트레이 정리 (위치 저장 포함)
            if getattr(self, 'send_tray', None):
                self.send_tray.hide_tray()
                self.send_tray.close()
            # 메모 트레이 정리 (위치·메모 저장 포함)
            # ※ 메인 메모 save_all_memos(위) 이후에 실행되어야
            #   트레이에서 수정한 최신 내용이 마지막에 저장됨
            if getattr(self, 'memo_tray', None):
                self.memo_tray.hide_tray()
                self.memo_tray.close()
            # 글로벌 단축키 해제
            self._remove_snippet_hook()
            # [PERF] 잔류 토스트 위젯 강제 정리
            from gui.jarvis_toast import JarvisToast
            for toast in list(JarvisToast._active_toasts):
                toast.hide()
                toast.deleteLater()
            JarvisToast._active_toasts.clear()
        except Exception as e:
            print(f"Close event error: {e}")
        event.accept()

    # ========== 글로벌 단축키 & 텍스트 스니펫 ==========
    
    def _setup_global_hotkeys(self):
        """글로벌 단축키 초기화"""
        self.hotkey_settings = self._load_hotkey_settings()
        self._register_hotkeys()
        self.emit_log(f"Global Hotkeys Initialized: Memo={self.hotkey_settings.get('memo_hotkey', 'ctrl+shift+m')}, Tray={self.hotkey_settings.get('tray_hotkey', 'ctrl+g')}, MemoTray={self.hotkey_settings.get('memo_tray_hotkey', 'ctrl+m')}")
    
    def _load_hotkey_settings(self):
        """단축키 설정 로드"""
        default_settings = {
            "memo_hotkey": "ctrl+shift+m",
            "tray_hotkey": "ctrl+g",
            "memo_tray_hotkey": "ctrl+m",
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
            cfg_path = get_config_path()
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
            cfg_path = get_config_path()
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
        """단축키 등록 — 단일 Win32 훅으로 메모+스니펫 통합"""
        try:
            self._install_snippet_hook()
        except Exception as e:
            print(f"단축키 등록 오류: {e}")

    def _unregister_hotkeys(self):
        """단축키 해제"""
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
    
    def _activate_send_tray(self):
        """보내기 트레이 토글 (훅 스레드에서 호출됨)"""
        QTimer.singleShot(0, self._toggle_send_tray)

    def _toggle_send_tray(self):
        """보내기 트레이 표시/숨김 (메인 스레드)"""
        try:
            if not getattr(self, 'send_tray', None):
                from gui.send_tray import SendTrayWindow
                self.send_tray = SendTrayWindow(path_callback=lambda: self.line_path.text())
            self.send_tray.toggle()
            if self.send_tray.isVisible():
                self.emit_log("📤 보내기 트레이 열림")
        except Exception as e:
            print(f"보내기 트레이 오류: {e}")

    def _activate_memo_tray(self):
        """메모 트레이 토글 (훅 스레드에서 호출됨)"""
        QTimer.singleShot(0, self._toggle_memo_tray)

    def _toggle_memo_tray(self):
        """메모 트레이 표시/숨김 (메인 스레드)"""
        try:
            if not getattr(self, 'memo_tray', None):
                from gui.memo_tray import MemoTrayWindow
                self.memo_tray = MemoTrayWindow(
                    schedule_manager=self.shared_schedule_manager,
                    on_hidden=self._on_memo_tray_hidden)
                self.memo_tray.memo.hotkey_settings_clicked.connect(self.show_hotkey_settings)
            if not self.memo_tray.isVisible() and hasattr(self, 'mk3_memo_widget'):
                # 메인 메모의 미저장(디바운스 대기) 내용을 먼저 반영
                # → 트레이가 표시 직전 저장소 기준으로 다시 읽음
                self.mk3_memo_widget.save_all_memos()
            self.memo_tray.toggle()
            if self.memo_tray.isVisible():
                self.emit_log("📝 메모 트레이 열림")
        except Exception as e:
            print(f"메모 트레이 오류: {e}")

    def _on_memo_tray_hidden(self):
        """트레이에서 수정한 메모를 메인 메모 위젯에 반영"""
        try:
            if hasattr(self, 'mk3_memo_widget'):
                self.mk3_memo_widget.reload_memos()
        except Exception as e:
            print(f"메모 동기화 오류: {e}")

    def _paste_snippet(self, text):
        """텍스트 스니펫 붙여넣기 (다른 스레드에서 호출됨)"""
        def do_paste():
            try:
                import pyperclip
                import ctypes
                import ctypes.wintypes
                user32 = ctypes.windll.user32
                VK_CONTROL = 0x11
                # 물리 Ctrl 키가 릴리스될 때까지 대기 (최대 500ms)
                for _ in range(50):
                    if not (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000):
                        break
                    import time; time.sleep(0.01)
                # 클립보드에 복사
                pyperclip.copy(text)
                # Win32 API로 Ctrl+V 시뮬레이션 (keyboard 라이브러리 불필요)
                VK_V = 0x56
                KEYEVENTF_KEYUP = 0x0002
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_V, 0, 0, 0)
                user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            except Exception as e:
                print(f"스니펫 붙여넣기 오류: {e}")

        # 약간의 딜레이 후 붙여넣기 (키 릴리스 대기)
        threading.Timer(0.05, do_paste).start()
    
    def _install_snippet_hook(self):
        """단일 Win32 저수준 훅으로 메모+스니펫 통합 (전용 스레드 + GetMessageW 블로킹)"""
        import ctypes
        import ctypes.wintypes

        # --- 메모 단축키 파싱 ---
        memo_key = self.hotkey_settings.get("memo_hotkey", "ctrl+shift+m")
        self._memo_vk_combo = self._parse_hotkey_combo(memo_key)

        # --- 보내기 트레이 단축키 파싱 (기본: Ctrl+G) ---
        tray_key = self.hotkey_settings.get("tray_hotkey", "ctrl+g")
        self._tray_vk_combo = self._parse_hotkey_combo(tray_key)

        # --- 메모 트레이 단축키 파싱 (기본: Ctrl+M) ---
        memo_tray_key = self.hotkey_settings.get("memo_tray_hotkey", "ctrl+m")
        self._memo_tray_vk_combo = self._parse_hotkey_combo(memo_tray_key)

        # --- VK 코드 → 스니펫 텍스트 맵 구축 ---
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

        if (not self._vk_snippet_map and not self._memo_vk_combo
                and not self._tray_vk_combo and not self._memo_tray_vk_combo):
            self._snippet_hook_handle = None
            self._snippet_hook_thread = None
            return

        vk_map = self._vk_snippet_map
        memo_combo = self._memo_vk_combo
        tray_combo = self._tray_vk_combo
        memo_tray_combo = self._memo_tray_vk_combo
        paste_fn = self._paste_snippet
        activate_memo_fn = self._activate_memo
        activate_tray_fn = self._activate_send_tray
        activate_memo_tray_fn = self._activate_memo_tray
        self._hook_thread_id = None

        def hook_thread_func():
            """전용 스레드: 단일 훅 + 블로킹 GetMessageW 메시지 펌프"""
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32

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
            WM_QUIT = 0x0012
            VK_CONTROL = 0x11
            VK_SHIFT = 0x10
            VK_MENU = 0x12  # Alt

            HOOKPROC = ctypes.CFUNCTYPE(
                ctypes.wintypes.LPARAM, ctypes.c_int,
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

            @HOOKPROC
            def hook_proc(nCode, wParam, lParam):
                try:
                    if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                        ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
                        shift_down = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
                        alt_down = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
                        mods = (ctrl_down, alt_down, shift_down)

                        # 메모 단축키 체크 (예: Ctrl+Shift+M, F11)
                        if memo_combo:
                            need_ctrl, need_alt, need_shift, trigger_vk = memo_combo
                            if kb.vkCode == trigger_vk and mods == (need_ctrl, need_alt, need_shift):
                                activate_memo_fn()
                                return 1

                        # 보내기 트레이 단축키 체크 (예: Ctrl+G)
                        if tray_combo:
                            need_ctrl, need_alt, need_shift, trigger_vk = tray_combo
                            if kb.vkCode == trigger_vk and mods == (need_ctrl, need_alt, need_shift):
                                activate_tray_fn()
                                return 1

                        # 메모 트레이 단축키 체크 (예: Ctrl+M)
                        if memo_tray_combo:
                            need_ctrl, need_alt, need_shift, trigger_vk = memo_tray_combo
                            if kb.vkCode == trigger_vk and mods == (need_ctrl, need_alt, need_shift):
                                activate_memo_tray_fn()
                                return 1

                        # 스니펫 단축키 체크 (예: Ctrl+1~9)
                        if ctrl_down and not shift_down and kb.vkCode in vk_map:
                            text = vk_map[kb.vkCode]
                            threading.Timer(0.05, lambda: paste_fn(text)).start()
                            return 1
                except Exception:
                    pass
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            # GC 방지용 참조
            self._hook_proc_ref = hook_proc

            hook_handle = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, hook_proc, None, 0
            )
            self._snippet_hook_handle = hook_handle

            # 이 스레드의 ID 저장 (종료 시 WM_QUIT 전송용)
            self._hook_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

            total = (len(vk_map) + (1 if memo_combo else 0) + (1 if tray_combo else 0)
                     + (1 if memo_tray_combo else 0))
            if hook_handle:
                print(f"✅ 통합 키보드 훅 설치 완료 (단축키 {total}개, 전용 스레드)")
            else:
                print("❌ 통합 키보드 훅 설치 실패")
                return

            # 블로킹 GetMessageW 메시지 펌프 — CPU 사용률 0%
            # WM_QUIT 수신 시 자동 종료
            msg = ctypes.wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            # 정리
            user32.UnhookWindowsHookEx(hook_handle)
            self._snippet_hook_handle = None
            self._hook_proc_ref = None
            self._hook_thread_id = None
            print("🔓 통합 키보드 훅 제거됨")

        self._snippet_hook_thread = threading.Thread(
            target=hook_thread_func, daemon=True, name="HotkeyThread"
        )
        self._snippet_hook_thread.start()

    def _parse_hotkey_combo(self, hotkey_str):
        """단축키 문자열 → (need_ctrl, need_alt, need_shift, trigger_vk) 튜플로 파싱

        문자/숫자 키는 Ctrl 또는 Alt가 반드시 포함되어야 함
        (Shift+문자 단독은 일반 타이핑을 가로채므로 거부). F키는 단독 허용.
        """
        if not hotkey_str:
            return None
        parts = [p.strip().lower() for p in hotkey_str.split("+")]
        need_ctrl = "ctrl" in parts
        need_alt = "alt" in parts
        need_shift = "shift" in parts
        trigger_parts = [p for p in parts if p not in ("ctrl", "shift", "alt")]
        if not trigger_parts:
            return None
        vk = self._key_to_vk(trigger_parts[0])
        if vk is None:
            return None
        is_fkey = 0x70 <= vk <= 0x87  # VK_F1~F24
        if not is_fkey and not (need_ctrl or need_alt):
            return None
        return (need_ctrl, need_alt, need_shift, vk)

    def _remove_snippet_hook(self):
        """키보드 훅 제거 — WM_QUIT로 스레드 안전 종료"""
        if hasattr(self, '_hook_thread_id') and self._hook_thread_id:
            import ctypes
            # WM_QUIT를 훅 스레드에 전송 → GetMessageW가 0 반환 → 루프 종료
            ctypes.windll.user32.PostThreadMessageW(
                self._hook_thread_id, 0x0012, 0, 0  # WM_QUIT
            )
        if hasattr(self, '_snippet_hook_thread') and self._snippet_hook_thread:
            self._snippet_hook_thread.join(timeout=2)
            self._snippet_hook_thread = None
    
    def _key_to_vk(self, key_str):
        """키 문자열을 Windows VK 코드로 변환"""
        key = key_str.strip().lower()
        if len(key) == 1:
            if key.isdigit():
                return 0x30 + int(key)  # VK_0(0x30) ~ VK_9(0x39)
            elif key.isalpha():
                return ord(key.upper())  # VK_A(0x41) ~ VK_Z(0x5A)
        elif key.startswith("f") and key[1:].isdigit():
            n = int(key[1:])
            if 1 <= n <= 24:
                return 0x70 + n - 1  # VK_F1(0x70) ~ VK_F24(0x87)
        return None
    
    def show_hotkey_settings(self):
        """단축키 설정 다이얼로그 표시 - Nano Banana Style"""
        from gui.widgets import GlassFrame, NeonButton
        
        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setFixedSize(750, 710)

        # 메인 컨테이너 (네온 테두리)
        container = QFrame(dlg)
        container.setGeometry(0, 0, 750, 710)
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

        # ===== 보내기 트레이 단축키 섹션 =====
        tray_frame = QFrame()
        tray_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 30, 45, 150);
                border: 1px solid #00aaaa;
                border-radius: 12px;
            }
        """)
        tray_layout = QHBoxLayout(tray_frame)
        tray_layout.setContentsMargins(15, 12, 15, 12)
        tray_layout.setSpacing(15)

        tray_label = QLabel("보내기 트레이:")
        tray_label.setStyleSheet("color: #00cccc; font-size: 10pt; font-weight: bold; border: none;")
        tray_label.setFixedWidth(100)
        tray_layout.addWidget(tray_label)

        tray_input = QLineEdit(self.hotkey_settings.get("tray_hotkey", "ctrl+g"))
        tray_input.setFixedHeight(36)
        tray_input.setPlaceholderText("ctrl+g")
        tray_input.setStyleSheet(memo_input.styleSheet())
        tray_layout.addWidget(tray_input, 1)
        main_layout.addWidget(tray_frame)

        # ===== 메모 트레이 단축키 섹션 =====
        memo_tray_frame = QFrame()
        memo_tray_frame.setStyleSheet(tray_frame.styleSheet())
        memo_tray_layout = QHBoxLayout(memo_tray_frame)
        memo_tray_layout.setContentsMargins(15, 12, 15, 12)
        memo_tray_layout.setSpacing(15)

        memo_tray_label = QLabel("메모 트레이:")
        memo_tray_label.setStyleSheet("color: #00cccc; font-size: 10pt; font-weight: bold; border: none;")
        memo_tray_label.setFixedWidth(100)
        memo_tray_layout.addWidget(memo_tray_label)

        memo_tray_input = QLineEdit(self.hotkey_settings.get("memo_tray_hotkey", "ctrl+m"))
        memo_tray_input.setFixedHeight(36)
        memo_tray_input.setPlaceholderText("ctrl+m")
        memo_tray_input.setStyleSheet(memo_input.styleSheet())
        memo_tray_layout.addWidget(memo_tray_input, 1)
        main_layout.addWidget(memo_tray_frame)
        
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
            # 유효성 검사: 잘못된 조합(단독 문자, shift+문자 등)은 저장 전에 거부
            for name, val in (("메모장", memo_input.text().strip()),
                              ("보내기 트레이", tray_input.text().strip()),
                              ("메모 트레이", memo_tray_input.text().strip())):
                if val and self._parse_hotkey_combo(val) is None:
                    from gui.dialogs import JarvisMessageBox
                    JarvisMessageBox.warning(
                        dlg, "단축키 오류",
                        f"'{val}' 은(는) 사용할 수 없는 {name} 단축키입니다.\n"
                        "Ctrl 또는 Alt를 포함한 조합(예: ctrl+g, ctrl+shift+m, alt+t)이나 "
                        "F키(예: f11)만 가능합니다."
                    )
                    return
            self._unregister_hotkeys()
            self.hotkey_settings["memo_hotkey"] = memo_input.text().strip()
            self.hotkey_settings["tray_hotkey"] = tray_input.text().strip()
            self.hotkey_settings["memo_tray_hotkey"] = memo_tray_input.text().strip()
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
        dlg.deleteLater()

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

    def mouseDoubleClickEvent(self, event):
        """타이틀바 더블클릭 시 최대화/복원 (맥 스타일)"""
        if event.pos().y() < 50 and event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
            event.accept()

    def _toggle_maximize(self):
        """창 최대화/복원 토글"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def load_background(self):
        # Iron Man 배경 비활성화 — 깔끔한 단색 배경 사용
        self.bg_pixmap = None

    def start_bg_animation(self):
        # Iron Man 배경 비활성화 — 전역 GLOBAL_STYLESHEET의 #OuterContainer radial gradient 사용
        # 이전에 cyan 경계로 덮어쓰던 로직 제거
        if hasattr(self, 'bg_anim'):
            self.bg_anim.start()
            self._update_bg_label()

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
        """(구 사이드바) 호환용 숨김 위젯 + 로그 영역만 생성.
        T 로고 토글·AI·Logs 칩은 setup_middle_panel 헤더로 이동했다."""
        _mono = "'JetBrains Mono','Consolas',monospace"

        # ═══════════════════════════════════════
        # HIDDEN COMPATIBILITY WIDGETS
        # (기존 코드 호환을 위한 더미 - 레이아웃에 추가하지 않음)
        # ═══════════════════════════════════════
        self.line_path = QLineEdit()
        self.line_path.setReadOnly(True)
        self.line_path.hide()

        self.btn_browse = QPushButton()
        self.btn_browse.clicked.connect(self.browse_directory)
        self.btn_browse.hide()

        self.btn_api_settings = QPushButton()
        self.btn_api_settings.clicked.connect(self.open_api_settings)
        self.btn_api_settings.hide()

        self.btn_start = QPushButton()
        self.btn_start.clicked.connect(self.start_monitoring)
        self.btn_start.hide()

        self.btn_stop = QPushButton()
        self.btn_stop.clicked.connect(self.stop_monitoring)
        self.btn_stop.setEnabled(False)
        self.btn_stop.hide()

        # log_area: floating panel 으로 이동하므로 여기서는 QTextEdit 만 생성 (parent=None)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setObjectName("ClaudeLogArea")
        self.log_area.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_area.setStyleSheet(f"""
            QTextEdit#ClaudeLogArea {{
                background-color: {CT['logs_bg']} !important;
                color: {CT['fg_1']} !important;
                border: none;
                font-family: {_mono};
                font-size: 8.5pt;
                padding: 8px 10px;
            }}
        """)

        # 호환 dummy
        self.lbl_api_version = QLabel("")
        self.lbl_api_version.hide()
        self.lbl_app_version = QLabel(f"{APP_NAME} v{__version__}")
        self.lbl_app_version.hide()


    # ─────────────────────────────────────────
    # 사이드바 이벤트 핸들러 (handoff_2)
    # ─────────────────────────────────────────
    def _on_circle_toggle(self):
        """T 로고 클릭 → monitoring 상태 전환."""
        if getattr(self, '_monitor_on', False):
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def _update_watch_chip(self, path: str):
        """감시 폴더 경로 표시 갱신 — 중앙 헤더의 경로 라벨 (긴 경로는 앞을 줄임)."""
        if hasattr(self, 'lbl_location') and path:
            short = path
            if len(short) > 55:
                short = "..." + short[-52:]
            self.lbl_location.setText(short)
            self.lbl_location.setToolTip(path)

    def _brand_glow_set(self, v):
        """T 로고 글로우 알파값 적용."""
        from PyQt6.QtGui import QColor
        self._brand_glow.setColor(QColor(170, 225, 255, int(v)))

    def _brand_anim_stop(self):
        """진행 중인 T 로고 애니메이션 정지."""
        anim = getattr(self, '_brand_anim', None)
        if anim is not None:
            try:
                anim.stop()
            except RuntimeError:
                pass
        self._brand_anim = None

    def _brand_ignite(self):
        """점화 연출 — 순간 번쩍(0→255, 0.15초) → 안정 글로우 정착 → 느린 호흡."""
        from PyQt6.QtCore import QVariantAnimation, QEasingCurve, QSequentialAnimationGroup
        self._brand_anim_stop()
        seq = QSequentialAnimationGroup(self)

        ignite = QVariantAnimation(seq)
        ignite.setDuration(150)
        ignite.setStartValue(getattr(self, '_BRAND_STANDBY_ALPHA', 0))
        ignite.setEndValue(255)
        ignite.setEasingCurve(QEasingCurve.Type.OutQuad)
        ignite.valueChanged.connect(self._brand_glow_set)
        seq.addAnimation(ignite)

        # 점화 후 고정 글로우로 정착 — 호흡(주기적 밝기 변화) 애니메이션은
        # 체감이 거의 없는데 블러 재렌더를 계속 유발해 제거 (유휴 CPU 0)
        settle = QVariantAnimation(seq)
        settle.setDuration(550)
        settle.setStartValue(255)
        settle.setEndValue(225)
        settle.setEasingCurve(QEasingCurve.Type.InOutQuad)
        settle.valueChanged.connect(self._brand_glow_set)
        seq.addAnimation(settle)

        def _steady():
            self._brand_anim = None
        seq.finished.connect(_steady)
        seq.start()
        self._brand_anim = seq

    def _update_state_ui(self, monitoring: bool):
        """감시 상태 → T 타일 점등/소등 + 워드마크·상태 줄 연동."""
        self._monitor_on = monitoring
        if not hasattr(self, 'brand_mark'):
            return
        from PyQt6.QtGui import QColor as _QColor
        if monitoring:
            self.brand_mark.setStyleSheet(self._brand_css_on)
            if hasattr(self, 'lbl_brand'):
                self.lbl_brand.setText(self._wordmark_html_on)
                self._wordmark_glow.setColor(_QColor(94, 189, 255, 130))
            if hasattr(self, 'lbl_brand_status'):
                self.lbl_brand_status.setText(self._status_html_on)
            self._brand_ignite()
        else:
            self._brand_anim_stop()
            self._brand_glow_set(getattr(self, '_BRAND_STANDBY_ALPHA', 0))
            self.brand_mark.setStyleSheet(self._brand_css_off)
            if hasattr(self, 'lbl_brand'):
                self.lbl_brand.setText(self._wordmark_html_off)
                self._wordmark_glow.setColor(_QColor(94, 189, 255, 0))
            if hasattr(self, 'lbl_brand_status'):
                self.lbl_brand_status.setText(self._status_html_off)

    def _btn_primary_css(self):
        return f"""
            QPushButton {{
                background-color: {CT['accent']};
                color: #ffffff;
                border: 1px solid {CT['accent_hi']};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 9.5pt;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: {CT['accent_hi']}; }}
            QPushButton:pressed {{ background-color: {CT['accent_lo']}; }}
            QPushButton:disabled {{
                background-color: {CT['bg_2']};
                color: {CT['fg_3']};
                border: 1px solid {CT['border_soft']};
            }}
        """

    def _btn_secondary_css(self):
        return f"""
            QPushButton {{
                background-color: {CT['bg_2']};
                color: {CT['fg_1']};
                border: 1px solid {CT['border_soft']};
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 9.5pt;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {CT['bg_3']};
                color: {CT['fg_0']};
                border: 1px solid {CT['border']};
            }}
            QPushButton:disabled {{ color: {CT['fg_3']}; }}
        """

    def _btn_icon_css(self):
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {CT['fg_2']};
                border: 1px solid transparent;
                border-radius: 6px;
                font-size: 13pt;
                padding: 0;
            }}
            QPushButton:hover {{
                background-color: {CT['bg_3']};
                color: {CT['fg_0']};
            }}
        """

    def setup_middle_panel(self):
        """Claude Design warm dark 중앙 패널.
        title + breadcrumbs + filter chips + group card scroll."""
        layout = QVBoxLayout(self.middle_panel)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(0)

        _mono = "'JetBrains Mono','Consolas',monospace"

        # ── 1) BRAND BAR — T 토글(점화) + TRADIS 워드마크 + 상태 + AI/Logs ──
        brand_row = QHBoxLayout()
        brand_row.setSpacing(14)
        brand_row.setContentsMargins(0, 0, 0, 0)

        from PyQt6.QtWidgets import QGraphicsDropShadowEffect as _QShadow
        from PyQt6.QtGui import QColor as _QColor

        # T 타일 — 평상시 딥블루 대기 전력, 클릭 시 점화
        self._BRAND_STANDBY_ALPHA = 55
        self.brand_mark = QLabel("T")
        brand_mark = self.brand_mark
        brand_mark.setFixedSize(52, 52)
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setCursor(Qt.CursorShape.PointingHandCursor)
        # 꺼짐: 딥블루 그라데이션 (대기 전력이 흐르는 느낌)
        self._brand_css_off = """
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 #2e5f96,
                stop:1 #16324f
            );
            color: #cfe6ff;
            border: 1px solid #335671;
            font-weight: 700;
            font-size: 24pt;
            border-radius: 14px;
            letter-spacing: -0.6px;
        """
        # 켜짐: 흰빛에 가까운 발광 타일 + 짙은 파랑 T
        self._brand_css_on = """
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 #e6f7ff,
                stop:1 #6cbcff
            );
            color: #0a3b6e;
            border: 1px solid #bfe6ff;
            font-weight: 700;
            font-size: 24pt;
            border-radius: 14px;
            letter-spacing: -0.6px;
        """
        brand_mark.setStyleSheet(self._brand_css_off)

        self._brand_glow = _QShadow(brand_mark)
        self._brand_glow.setBlurRadius(46)
        self._brand_glow.setOffset(0, 0)
        self._brand_glow.setColor(_QColor(170, 225, 255, self._BRAND_STANDBY_ALPHA))
        brand_mark.setGraphicsEffect(self._brand_glow)
        self._brand_anim = None

        def _brand_click(ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                self._on_circle_toggle()
        brand_mark.mousePressEvent = _brand_click
        self._monitor_on = False
        brand_row.addWidget(brand_mark)

        # 워드마크 (TRADIS) + 상태 줄
        _wm_col = QVBoxLayout()
        _wm_col.setSpacing(2)
        _wm_col.setContentsMargins(0, 0, 0, 0)

        self._wordmark_html_off = (
            f'<span style="color:{CT["accent_hi"]};">T</span>'
            f'<span style="color:{CT["fg_0"]};">RADIS</span>'
        )
        self._wordmark_html_on = f'<span style="color:{CT["accent_hi"]};">TRADIS</span>'
        self.lbl_brand = QLabel(self._wordmark_html_off)
        self.lbl_brand.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_brand.setStyleSheet("font-size: 15pt; font-weight: 700; background: transparent;")
        _wm_font = self.lbl_brand.font()
        _wm_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4.0)
        self.lbl_brand.setFont(_wm_font)
        # 감시 중일 때 워드마크에 은은한 파란 글로우
        self._wordmark_glow = _QShadow(self.lbl_brand)
        self._wordmark_glow.setBlurRadius(18)
        self._wordmark_glow.setOffset(0, 0)
        self._wordmark_glow.setColor(_QColor(94, 189, 255, 0))
        self.lbl_brand.setGraphicsEffect(self._wordmark_glow)
        _wm_col.addWidget(self.lbl_brand)

        self._status_html_off = (
            f'<span style="color:{CT["fg_3"]};">● 감시 중지됨 · by M.H. Choi</span>'
        )
        self._status_html_on = (
            f'<span style="color:{CT["accent_hi"]};">● 감시 중</span>'
            f'<span style="color:{CT["fg_3"]};"> · by M.H. Choi</span>'
        )
        self.lbl_brand_status = QLabel(self._status_html_off)
        self.lbl_brand_status.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_brand_status.setStyleSheet("font-size: 8.5pt; background: transparent;")
        _wm_col.addWidget(self.lbl_brand_status)

        brand_row.addLayout(_wm_col)
        brand_row.addStretch()
        # (AI/Logs 칩은 아래에서 생성 후 brand_row 오른쪽에 추가됨)
        layout.addLayout(brand_row)

        # 브랜드 바 ↔ 도구 줄 구분선
        layout.addSpacing(12)
        _brand_sep = QFrame()
        _brand_sep.setFixedHeight(1)
        _brand_sep.setStyleSheet(f"background-color: {CT['border_soft']}; border: none;")
        layout.addWidget(_brand_sep)
        layout.addSpacing(10)

        # ── 2) TOOL ROW — 경로 + 그룹 수 + 뷰 전환 + 재스캔 ──
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.setContentsMargins(0, 0, 0, 0)

        from gui.claude_icons import pixmap as _icpx0
        _crumbs_folder = QLabel()
        _crumbs_folder.setFixedSize(16, 16)
        _crumbs_folder.setPixmap(_icpx0("Folder", size=15, color=CT['fg_2']))
        _crumbs_folder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _crumbs_folder.setStyleSheet("background: transparent; border: none;")
        title_row.addWidget(_crumbs_folder)

        # 경로 라벨 — 클릭하면 감시 폴더 변경
        self.lbl_location = QLabel("폴더를 선택하세요")
        self.lbl_location.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_location.setStyleSheet(f"""
            color: {CT['fg_1']};
            background-color: {CT['bg_2']};
            border: 1px solid {CT['border_soft']};
            border-radius: 6px;
            padding: 5px 10px;
            font-family: {_mono};
            font-size: 9pt;
        """)
        def _loc_click(ev):
            if ev.button() == Qt.MouseButton.LeftButton:
                self.browse_directory()
        self.lbl_location.mousePressEvent = _loc_click
        title_row.addWidget(self.lbl_location)

        # 그룹 수
        self.current_card_filter = 'all'
        self.group_cards = []
        self.filter_btns = {}  # 레거시 호환 (칩 제거됨)
        self.lbl_section_hint = QLabel("그룹 0")
        self.lbl_section_hint.setStyleSheet(f"color: {CT['fg_3']}; font-size: 9pt; font-weight: 500; background: transparent;")
        title_row.addWidget(self.lbl_section_hint)
        title_row.addStretch()

        # ── AI 상태 칩 + 로그 칩 (브랜드 바 오른쪽, 테두리 없는 조용한 스타일) ──
        _chip_css = f"""
            QPushButton#headerChip {{
                background-color: transparent;
                color: {CT['fg_1']};
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 5px 10px;
                font-size: 9pt;
                text-align: left;
            }}
            QPushButton#headerChip:hover {{
                background-color: {CT['bg_2']};
                color: {CT['fg_0']};
            }}
            QPushButton#headerChip:checked {{
                background-color: {CT['accent_bg']};
                color: {CT['accent_hi']};
            }}
        """

        # AI chip (클릭 시 API 설정)
        self.btn_ai_chip = QPushButton()
        self.btn_ai_chip.setObjectName("headerChip")
        self.btn_ai_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_chip.setFixedHeight(30)
        self.btn_ai_chip.setMinimumWidth(160)
        self.btn_ai_chip.setStyleSheet(_chip_css)
        self.btn_ai_chip.clicked.connect(self.open_api_settings)
        _ai_inner = QHBoxLayout(self.btn_ai_chip)
        _ai_inner.setContentsMargins(10, 3, 10, 3)
        _ai_inner.setSpacing(7)
        self._ai_dot = QLabel()
        self._ai_dot.setFixedSize(6, 6)
        self._ai_dot.setStyleSheet(f"background-color: {CT['fg_3']}; border-radius: 3px;")
        _ai_inner.addWidget(self._ai_dot)
        self.lbl_api_status = QLabel("AI Offline")
        self.lbl_api_status.setStyleSheet(f"color: {CT['fg_1']}; font-size: 9pt; background: transparent;")
        _ai_inner.addWidget(self.lbl_api_status)
        self._ai_version_tag = QLabel(f"v{__version__}")
        self._ai_version_tag.setStyleSheet(
            f"color: {CT['fg_3']}; font-family: {_mono}; font-size: 8pt; background: transparent;"
        )
        _ai_inner.addWidget(self._ai_version_tag)
        brand_row.addWidget(self.btn_ai_chip)

        # (로그 칩은 제거됨 — 로그는 하단 로그 영역/파일에서 확인)

        # ── 중앙 뷰 전환: [그룹] 카드 / [파일] 브라우저 ──
        seg = QFrame()
        seg.setStyleSheet(f"QFrame {{ background-color: {CT['bg_2']}; border: 1px solid {CT['border_soft']}; border-radius: 9px; }}")
        seg_layout = QHBoxLayout(seg)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(3)
        seg_css = f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 6px;
                color: {CT['fg_2']}; font-size: 9pt; font-weight: 600;
                padding: 5px 16px;
            }}
            QPushButton:hover {{ color: {CT['fg_0']}; }}
            QPushButton:checked {{ background-color: {CT['bg_4']}; color: {CT['fg_0']}; }}
        """
        self.btn_view_groups = QPushButton("그룹")
        self.btn_view_files = QPushButton("파일")
        for _b in (self.btn_view_groups, self.btn_view_files):
            _b.setCheckable(True)
            _b.setCursor(Qt.CursorShape.PointingHandCursor)
            _b.setStyleSheet(seg_css)
            seg_layout.addWidget(_b)
        self.btn_view_groups.setChecked(True)
        self.btn_view_groups.clicked.connect(lambda: self._set_center_view('groups'))
        self.btn_view_files.clicked.connect(lambda: self._set_center_view('files'))
        title_row.addWidget(seg)

        from gui.claude_icons import pixmap as _icpx
        from PyQt6.QtCore import QSize as _QSize
        btn_rescan = QPushButton()
        btn_rescan.setIcon(QIcon(_icpx("Refresh", size=15, color=CT['fg_1'])))
        btn_rescan.setIconSize(_QSize(15, 15))
        btn_rescan.setFixedSize(32, 30)
        btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rescan.setStyleSheet(self._btn_secondary_css())
        btn_rescan.clicked.connect(self.run_intelligent_merge)
        title_row.addWidget(btn_rescan)

        # 파일 합치기 기록 (합치기/폴더 정리 되돌리기) — 시안대로 파란 액센트
        btn_history = QPushButton()
        btn_history.setIcon(QIcon(_icpx("History", size=15, color=CT['accent_hi'])))
        btn_history.setIconSize(_QSize(15, 15))
        btn_history.setFixedSize(32, 30)
        btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_history.setToolTip("파일 합치기 기록 — 합치기/폴더 정리 되돌리기")
        btn_history.setStyleSheet(f"""
            QPushButton {{
                background-color: {CT['accent_bg']};
                border: 1px solid {CT['accent_border']};
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background-color: rgba(75, 163, 247, 90);
                border: 1px solid {CT['accent_hi']};
            }}
        """)
        btn_history.clicked.connect(self.open_merge_history)
        title_row.addWidget(btn_history)
        layout.addLayout(title_row)

        # ── 2) 구분선 ──
        layout.addSpacing(12)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {CT['border_soft']}; border: none;")
        layout.addWidget(line)

        # ── 4) GROUP CARD SCROLL ──
        layout.addSpacing(12)
        self.merge_scroll = QScrollArea()
        self.merge_scroll.setWidgetResizable(True)
        self.merge_scroll.setStyleSheet("background: transparent; border: none;")
        self.merge_scroll.setFrameShape(QFrame.Shape.NoFrame)
        # 가로 스크롤 비활성화 — 콘텐츠가 컬럼 폭에 맞춰 wrap되도록
        self.merge_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.merge_container = QWidget()
        self.merge_container.setStyleSheet("background: transparent;")
        self.merge_layout = QVBoxLayout(self.merge_container)
        self.merge_layout.setContentsMargins(0, 0, 0, 0)
        self.merge_layout.setSpacing(8)
        self.merge_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.merge_scroll.setWidget(self.merge_container)

        # ── 중앙 스택: 0=그룹 카드 스크롤, 1=파일 브라우저 ──
        from gui.file_browser import FileBrowserWidget
        self.center_file_browser = FileBrowserWidget(path_callback=lambda: self.line_path.text())
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self.merge_scroll)
        self.center_stack.addWidget(self.center_file_browser)
        layout.addWidget(self.center_stack, stretch=1)

        self.lbl_hint = QLabel("분석을 기다리는 중...")
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_hint.setStyleSheet(f"color: {CT['fg_3']}; font-size: 11pt; padding: 40px;")
        self.merge_layout.addWidget(self.lbl_hint)

        # 초기 API 상태 (AI 칩 생성 후)
        from core.config import get_api_key
        self.update_api_status(bool(get_api_key()))

    def _set_center_view(self, mode):
        """중앙 패널 뷰 전환: 'groups'=그룹 카드, 'files'=파일 브라우저"""
        is_files = (mode == 'files')
        self.btn_view_groups.setChecked(not is_files)
        self.btn_view_files.setChecked(is_files)
        # 그룹 수 표시는 그룹 카드 전용 → 파일 뷰에서는 숨김
        self.lbl_section_hint.setVisible(not is_files)
        self.center_stack.setCurrentIndex(1 if is_files else 0)
        if is_files:
            # 열 때마다 지정 폴더 기준 최신 상태로
            self.center_file_browser.go_home()

    def _apply_card_filter(self, key):
        """필터 버튼 클릭 → 해당 상태 카드만 표시"""
        self.current_card_filter = key
        # 모든 버튼 체크 해제 후 선택된 것만 체크
        for k, btn in self.filter_btns.items():
            btn.setChecked(k == key)
        # 카드 표시/숨김
        for card in self.group_cards:
            if not hasattr(card, 'get_status'):
                card.setVisible(True)
                continue
            card.setVisible(key == 'all' or card.get_status() == key)

    def _refresh_filter_counts(self):
        """필터 상태 갱신 (칩 라벨은 숫자 없이 고정, 그룹 수는 section hint에만 표시)"""
        if not hasattr(self, 'filter_btns'):
            return
        total = len(self.group_cards)
        # 그룹 수 표시 갱신
        if hasattr(self, 'lbl_section_hint'):
            self.lbl_section_hint.setText(f"그룹 {total}")
        # 현재 필터 재적용 (상태 바뀐 카드 반영)
        self._apply_card_filter(self.current_card_filter)

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

    def _write_log_file(self, line: str):
        """로그를 파일로도 기록 — data/logs/tradis_YYYY-MM-DD.log"""
        try:
            if getattr(sys, 'frozen', False):
                base = os.path.dirname(sys.executable)
            else:
                base = os.path.dirname(os.path.abspath(__file__))
            log_dir = os.path.join(base, 'data', 'logs')
            os.makedirs(log_dir, exist_ok=True)
            fname = os.path.join(log_dir, f"tradis_{datetime.datetime.now().strftime('%Y-%m-%d')}.log")
            with open(fname, 'a', encoding='utf-8') as f:
                f.write(line + "\n")
        except Exception:
            pass

    def append_log(self, msg):
        MAX_LOG_LINES = 200  # 성능 최적화를 위해 로그 보관 줄 수 축소 (1000 -> 200)

        line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.log_area.append(line)
        # UI 로그 패널이 제거되어 파일이 확인 창구 — data/logs/에 일자별 기록
        self._write_log_file(line)

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
            # 기존 카드들을 안전하게 삭제 — cleanup() 으로 애니메이션/시그널 먼저 해제
            # (BL 많을 때 deleteLater() 만 호출하면 살아있는 애니메이션이 deleted 객체에
            #  접근해 RuntimeError → 앱 다운 발생)
            while self.merge_layout.count():
                child = self.merge_layout.takeAt(0)
                w = child.widget()
                if w:
                    try:
                        if hasattr(w, 'cleanup'):
                            w.cleanup()
                    except Exception:
                        pass
                    w.deleteLater()

            # 카드 필터 대상 리스트 초기화
            self.group_cards = []

            groups = report.get('groups', {})
            unclassified = report.get('unclassified', [])
            suggested = report.get('suggested', [])
            directory = report.get('directory', '')
            self.emit_log(f"Scan Report: {len(groups)} Groups, {len(unclassified)} Unclassified"
                          + (f", {len(suggested)} Suggested" if suggested else ""))

            if directory: self._update_watch_chip(directory)

            if not groups and not unclassified:
                lbl = QLabel("No files to process.")
                lbl.setStyleSheet("color: #777; font-size: 11pt;")
                self.merge_layout.addWidget(lbl)
                self._refresh_filter_counts()
                return

            # 1차 패스: 카드로 만들 그룹 / 미분류로 합산할 그룹 분리.
            # (단일 루프에서 unclassified 를 mutate 하면서 카드 생성하면 먼저 만들어진
            #  카드가 이후 추가된 미분류 파일을 못 봄 → 행추가 콤보에서 누락. 2-패스 처리)
            cardable_groups = {}
            for text_id, data in groups.items():
                docs = data.get('docs', {})
                has_statement = '자금정산서' in docs or '정산서' in docs
                is_export = any('수출신고필증' in v or '반송신고필증' in v for v in docs.values())
                is_import = any('수입신고필증' in v for v in docs.values())
                if not has_statement and not is_export and not is_import:
                    self.emit_log(f"[건너뜀] {text_id}: 자금정산서/신고필증 없음 — 미분류로 이동")
                    for _fn in docs.values():
                        if _fn and _fn not in unclassified:
                            unclassified.append(_fn)
                    continue
                cardable_groups[text_id] = data

            # 2차 패스: 최종 unclassified 가 확정된 후 카드 생성
            for text_id, data in cardable_groups.items():
                try:
                    # 금액-only 매칭 제안을 해당 카드에 전달 (노란 제안 행으로 표시)
                    data['suggested'] = [sg for sg in suggested if sg.get('bl') == text_id]
                    card = GroupCard(self, self.renamer, directory, text_id, data, unclassified)
                    self.merge_layout.addWidget(card)
                    self.group_cards.append(card)
                    # 상태 변경 시 필터 카운트 갱신
                    if hasattr(card, 'status_changed'):
                        card.status_changed.connect(self._refresh_filter_counts)
                except Exception as e: self.emit_log(f"Error creating card for {text_id}: {e}")

            # 이체증(독립)·미분류 카드는 표시하지 않음 (2026-07 사용자 요청)
            # — 해당 파일들은 [파일] 뷰와 보내기 트레이(전역 단축키, 기본 Ctrl+G)에서 직접 다룰 수 있음
            self.merge_layout.addStretch()

            # 필터 초기화 후 카운트 갱신
            self.current_card_filter = 'all'
            for k, btn in self.filter_btns.items():
                btn.setChecked(k == 'all')
            self._refresh_filter_counts()
            # 스캔 후 메모리 정리 + 추적 로그 (증가 추이 파악용, 파일 로그에만 기록)
            QTimer.singleShot(1500, self._post_scan_memory_cleanup)
        except Exception as e: self.emit_log(f"Critical error updating UI: {e}")

    def _on_merge_complete(self):
        self.emit_log("[상태] 병합 완료. 파일 이동 리스트를 갱신합니다.")
        if hasattr(self, 'file_manager'):
            self.file_manager.refresh_targets()
        # 병합/폴더 정리 후 카드 + 미분류 목록 재스캔
        self._debounced_refresh()
        # 백그라운드 메일 프리페치
        self._prefetch_mail_cache()

    def open_merge_history(self):
        """정리 기록 팝업 (골라서 되돌리기)"""
        from gui.history_dialog import MergeHistoryDialog
        dlg = MergeHistoryDialog(self, log=self.emit_log, on_undone=self._on_merge_complete)
        dlg.exec()
        dlg.deleteLater()

    def _show_undo_toast(self, info):
        """합치기/폴더 정리 완료 직후 되돌리기 토스트 (메인 스레드)

        현재 비활성화됨 — 되돌리기는 정리 기록 팝업에서만 제공 (2026-07 사용자 결정).
        다시 켜려면 dialogs.py run_merge/run_archive 성공 지점에서
        parent.undo_toast_signal.emit(renamer.last_history_entry) 호출을 복원할 것.
        """
        if not info or not info.get('id'):
            return
        from gui.history_dialog import UndoToast, confirm_undo, run_undo
        entry_id = info['id']
        folder_name = info.get('folder_name', '')
        kind_txt = "합치기" if info.get('kind') == 'merge' else "폴더 정리"
        sub_text = f"{kind_txt} · 파일 {info.get('file_count', 0)}개"

        def _undo():
            if not confirm_undo(self, folder_name):
                return
            run_undo(self, entry_id, log=self.emit_log, on_done=self._on_merge_complete)

        toast = UndoToast(folder_name, sub_text, _undo)
        toast.show_toast()

    def _on_move_failed(self, failed_list):
        """파일 이동 실패 알림 팝업 (메인 스레드)"""
        if not failed_list:
            return
        from gui.dialogs import JarvisMessageBox
        items_text = "\n".join(f"  ❌ {name} — {reason}" for name, reason in failed_list[:10])
        if len(failed_list) > 10:
            items_text += f"\n  ... 외 {len(failed_list)-10}건"
        msg = f"다음 파일을 확인해 주세요:\n\n{items_text}"
        JarvisMessageBox.warning(self, "파일 처리 알림", msg)

    def _on_merge_verify_failed(self, data):
        """병합 검증 실패 팝업 (메인 스레드)"""
        from gui.dialogs import JarvisMessageBox
        failed_files = data['failed_files']
        total = data['total']
        success_pages = data['success_pages']
        event = data['event']
        result_holder = data['result']

        failed_text = "\n".join(f"  ❌ {f} ({reason})" for f, reason in failed_files)
        msg = (f"{total}개 중 {len(failed_files)}개 파일 병합 실패\n\n"
               f"{failed_text}\n\n"
               f"성공: {success_pages}페이지")

        dlg = JarvisMessageBox(self, "병합 검증 실패", msg, JarvisMessageBox.Warning)
        dlg.add_button("취소", "cancel", "gray")
        dlg.add_button("무시하고 진행", "ignore", "gray")
        dlg.add_button("다시 합치기", "retry", "cyan")
        dlg.exec()

        result_holder['action'] = dlg.result_value or "cancel"
        dlg.deleteLater()
        event.set()  # 백그라운드 스레드 대기 해제

    def _on_shipping_search(self, bl_number, target_folder):
        """선적서류 자동 검색 (합치기/폴더정리 완료 후 트리거)"""
        if not hasattr(self, 'file_manager'):
            return
        fm = self.file_manager
        matches = fm.scan_shipping_docs_for_bl(bl_number)
        if matches:
            action, selected = fm._show_shipping_docs_dialog(bl_number, matches, target_folder)
            if action and selected:
                failed = fm.move_shipping_docs(selected, target_folder, mode=action)
                fm.refresh_targets()
                self.emit_log(f"[선적서류] {bl_number} {len(selected) - len(failed or [])}건 이동 완료")
                # 이동 실패가 있으면 알림 팝업
                if failed:
                    self.move_failed_signal.emit(failed)
        else:
            # 미발견 → FOLDER TREE를 선적서류폴더로 이동
            shipping_root = getattr(fm.archiver, 'export_docs_root', '')
            if shipping_root and os.path.exists(shipping_root):
                fm.file_browser.navigate_to(shipping_root)
                fm.current_path_label.setText(f"경로: {shipping_root}")
                self.emit_log(f"[선적서류] {bl_number} 미발견 → 선적서류폴더로 이동")

    def _prefetch_mail_cache(self):
        """병합 완료 후 정산서 파일의 B/L 번호로 메일을 미리 검색하여 캐시에 저장"""
        if getattr(self, '_prefetch_running', False):
            return
        self._prefetch_running = True

        import re
        path = self.line_path.text()
        if not path or not os.path.exists(path):
            self._prefetch_running = False
            return

        # 정산서 파일에서 B/L 번호 추출
        bl_numbers = []
        pattern = re.compile(r'^(.+?)\(([^)]+)\).*정산서\.pdf$', re.IGNORECASE)
        try:
            for folder in os.listdir(path):
                folder_path = os.path.join(path, folder)
                if not os.path.isdir(folder_path):
                    continue
                for fname in os.listdir(folder_path):
                    m = pattern.match(fname)
                    if m:
                        bl_id = m.group(2).strip()
                        if bl_id not in bl_numbers:
                            bl_numbers.append(bl_id)
        except Exception:
            self._prefetch_running = False
            return

        if not bl_numbers:
            self._prefetch_running = False
            return

        # 메일 설정 로드
        from core.config import get_config_path
        import json
        config_path = get_config_path()
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            hanbiro = config.get('hanbiro_mail', {})
            email_addr = hanbiro.get('email', '')
            imap_server = hanbiro.get('imap_server', 'raeon.hanbiro.net')
        except Exception:
            self._prefetch_running = False
            return

        import keyring
        password = keyring.get_password("TRADIS_MH", "email_password") or ''
        if not email_addr or not password:
            self._prefetch_running = False
            return

        from export_mail_sender import ExportMailSender, EmailConfig
        email_config = EmailConfig(imap_server=imap_server, email=email_addr, password=password)

        def do_prefetch():
            try:
                sender = ExportMailSender(email_config)
                sender.ensure_connections()
                for bl_id in bl_numbers:
                    # 이미 캐시에 있으면 건너뜀
                    cached = ExportMailSender._search_cache.get(bl_id)
                    if cached:
                        import datetime
                        ts, _ = cached
                        if (datetime.datetime.now() - ts).total_seconds() < ExportMailSender._CACHE_TTL:
                            continue
                    try:
                        sender.search_threads_by_bl(bl_id)
                    except Exception:
                        pass
                self.emit_log(f"[메일 프리페치] {len(bl_numbers)}건 B/L 캐시 완료")
            except Exception as e:
                print(f"[메일 프리페치 오류] {e}")
            finally:
                self._prefetch_running = False

        threading.Thread(target=do_prefetch, daemon=True).start()

    def _debounced_refresh(self):
        # 불필요한 반복 로그 제거 (상태 갱신 시마다 로그가 찍혀 리소스 낭비)
        path = self.line_path.text()
        if path: self.renamer.trigger_intelligent_merge(path)
            
    def trigger_debounced_refresh(self):
        self.debounce_timer.stop()
        self.debounce_timer.start(1000)

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
        
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        key = line_key.text().strip() if accepted else ""
        dlg.deleteLater()
        if accepted and key:
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
            # Watch folder chip 갱신 (Claude Design handoff_2)
            if hasattr(self, '_update_watch_chip'):
                self._update_watch_chip(d)
            self.file_manager.base_path = d
            self.file_manager.refresh_targets()
            self.save_settings()
            self.run_intelligent_merge()

    def start_monitoring(self):
        from core.config import get_api_key
        if not get_api_key():
            from gui.dialogs import JarvisMessageBox
            JarvisMessageBox.critical(self, "API 키 누락", "모니터링을 사용하려면 API 키가 필요합니다.")
            return
        path = self.line_path.text()
        if not path: return
        # 무거운 모듈 백그라운드 프리로딩 (첫 OCR 지연 방지)
        threading.Thread(target=self._preload_ocr_modules, daemon=True).start()
        self.renamer.start(path)
        self.btn_start.setEnabled(False)
        self.btn_start.setText("RUNNING..")
        self.btn_stop.setEnabled(True)
        # Claude Design: CircleToggle + state label 갱신
        if hasattr(self, '_update_state_ui'):
            self._update_state_ui(True)
        self.emit_log("Monitoring Started...")
        self.run_intelligent_merge()

    def _preload_ocr_modules(self):
        """OCR에 필요한 무거운 모듈을 백그라운드에서 미리 로드"""
        try:
            import pypdfium2
            from google.genai import types
            from core.config import get_client
            get_client()
        except Exception:
            pass

    def stop_monitoring(self):
        self.renamer.stop()
        self.btn_start.setEnabled(True)
        self.btn_start.setText("시작")
        self.btn_stop.setEnabled(False)
        # Claude Design: CircleToggle + state label 갱신
        if hasattr(self, '_update_state_ui'):
            self._update_state_ui(False)
        self.emit_log("Monitoring Stopped.")

    def update_api_status(self, connected: bool):
        if not hasattr(self, 'lbl_api_status'):
            return
        # 점(dot)은 별도 self._ai_dot 위젯 — 여기서는 텍스트와 점 색상만 갱신
        if connected:
            self.lbl_api_status.setText("AI 연결됨")
            if hasattr(self, '_ai_dot'):
                self._ai_dot.setStyleSheet(f"background-color: {CT['green']}; border-radius: 3px; border: none;")
        else:
            self.lbl_api_status.setText("API 키 필요")
            if hasattr(self, '_ai_dot'):
                self._ai_dot.setStyleSheet(f"background-color: {CT['red']}; border-radius: 3px; border: none;")
        self.lbl_api_status.setStyleSheet(
            f"color: {CT['fg_1']}; font-size: 9.5pt; font-weight: 500; background: transparent; border: none;"
        )

    def run_intelligent_merge(self):
        if hasattr(self, 'is_analyzing') and self.is_analyzing: return
        from core.config import get_api_key
        if not get_api_key():
            from gui.dialogs import JarvisMessageBox
            JarvisMessageBox.critical(self, "API 키 누락", "API 키가 필요합니다.")
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
        cfg = get_config_path()
        if os.path.exists(cfg):
            try:
                with open(cfg, 'r', encoding='utf-8') as f: data = json.load(f)
                if "target_path" in data:
                    path = data["target_path"]
                    self.line_path.setText(path)
                    # Watch folder chip 갱신 (Claude Design handoff_2)
                    if hasattr(self, '_update_watch_chip'):
                        self._update_watch_chip(path)
                    self.file_manager.base_path = path
                    self.file_manager.refresh_targets()
                    QTimer.singleShot(1000, self.run_intelligent_merge)
                if "import_root" in data:
                    self.archiver.import_root = data["import_root"]
                    self.file_manager.lbl_imp_root.setText(data["import_root"])
                    self.file_manager.start_background_indexing(data["import_root"])
                if "export_root" in data:
                    self.archiver.export_root = data["export_root"]
                    self.file_manager.lbl_exp_root.setText(data["export_root"])
                    self.file_manager.start_background_indexing(data["export_root"])
                if "export_docs_root" in data:
                    self.archiver.export_docs_root = data["export_docs_root"]
                    self.file_manager.lbl_exp_docs_root.setText(data["export_docs_root"])
                # API 키는 keyring에서 로드 (core/config.py에서 자동 처리)
                from core.config import _ensure_api_key
                loaded_api_key = _ensure_api_key()
                self.emit_log("API Key loaded." if loaded_api_key else "API Key missing.")
                if "browser_home_path" in data:
                    self.file_manager.browser_home_path = data["browser_home_path"]
            except Exception as e: print(f"Settings Load Error: {e}")

    def save_settings(self):
        cfg = get_config_path()
        try:
            if os.path.exists(cfg):
                with open(cfg, 'r', encoding='utf-8') as f: data = json.load(f)
            else: data = {}
            # 빈 값으로 기존 설정을 덮어쓰지 않도록 보호
            target = self.line_path.text()
            if target: data["target_path"] = target
            if self.archiver.import_root: data["import_root"] = self.archiver.import_root
            if self.archiver.export_root: data["export_root"] = self.archiver.export_root
            if self.archiver.export_docs_root: data["export_docs_root"] = self.archiver.export_docs_root
            if hasattr(self.file_manager, 'browser_home_path') and self.file_manager.browser_home_path:
                data["browser_home_path"] = self.file_manager.browser_home_path
            # Atomic write: 임시 파일에 쓰고 rename (중간 종료 시 파일 손상 방지)
            tmp_cfg = cfg + ".tmp"
            with open(tmp_cfg, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            # Windows: os.replace는 atomic (대상 파일이 있어도 덮어씀)
            os.replace(tmp_cfg, cfg)
        except Exception as e:
            print(f"Settings save error: {e}")
            # 임시 파일 잔존 방지
            try: os.unlink(cfg + ".tmp")
            except OSError: pass
    
    def _show_mini_window(self):
        """창 내리기 — 작업 표시줄로 최소화.
        (구 미니 HUD 위젯 제거 — 작업 표시줄의 TRADIS 아이콘 클릭으로 복원)"""
        self.showMinimized()

    def changeEvent(self, event):
        # 최소화 시 미사용 메모리 페이지를 OS에 반납 (백그라운드 상주 시 메모리 절감)
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(300, self._trim_working_set)

    @staticmethod
    def _mem_api():
        """kernel32 메모리 API 준비 (argtypes 명시 — 64비트 핸들 오류 방지)"""
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        k32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
        return ctypes, k32, _PMC

    def _trim_working_set(self):
        """파이썬 gc 후 워킹셋을 OS에 반납. 복원 시 필요한 페이지만 다시 올라온다."""
        if not self.isMinimized():
            return
        try:
            import gc
            gc.collect()
            ctypes, k32, _ = self._mem_api()
            k32.SetProcessWorkingSetSize(
                k32.GetCurrentProcess(), ctypes.c_size_t(-1), ctypes.c_size_t(-1))
        except Exception:
            pass

    def _post_scan_memory_cleanup(self):
        """스캔/카드 재구성 후 가비지 정리 + 메모리 추적 로그 (누수 진단 데이터)"""
        try:
            import gc
            gc.collect()
            ws = self._working_set_mb()
            if ws:
                line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [메모리] 워킹셋 {ws:.0f}MB"
                self._write_log_file(line)
        except Exception:
            pass

    @staticmethod
    def _working_set_mb():
        """현재 프로세스 워킹셋(MB) — 메모리 추적 로그용"""
        try:
            ctypes, k32, _PMC = JarvisGUI._mem_api()
            pmc = _PMC()
            pmc.cb = ctypes.sizeof(_PMC)
            if k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
                return pmc.WorkingSetSize / 1048576
        except Exception:
            pass
        return 0.0

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
    def _get_rk_automation(self):
        """ReadyKorea 자동화 지연 초기화"""
        if self.rk_automation is None:
            from readykorea_automation import ReadyKoreaAutomation
            self.rk_automation = ReadyKoreaAutomation(on_status_change=self._on_rk_status_change)
        return self.rk_automation

    def _on_rk_status_change(self, status, message: str):
        """ReadyKorea 자동화 상태 변경 콜백 (스레드 안전)"""
        from readykorea_automation import AutomationStatus
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
        from readykorea_automation import ExportInputData
        input_data = ExportInputData.from_export_data(self.last_export_data)
        
        self._add_rk_log("자동 입력 시작...")
        
        def run_automation():
            try:
                result = self._get_rk_automation().run_automation(input_data)
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
            result = self._get_rk_automation().connect()
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
            config_path = get_config_path()
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

            from export_mail_sender import ExportMailSender, EmailConfig
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
            JarvisMessageBox.warning(self, "파일 없음", f"수출/반송신고필증을 찾을 수 없습니다.\n폴더: {folder_path}\nID: {identifier}")
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

    # ── 관리자 모드 ──────────────────────────────────────────

    def _on_admin_unlocked(self):
        """관리자 잠금 해제 → navbar에 일정/통관/보고 버튼 추가"""
        self.license_tier = "admin"
        self._save_license_tier("admin")

        # navbar 재생성 — admin 등급이므로 일정/통관/보고 탭이 포함된 전체 메뉴가 만들어진다
        current_tab = self.current_nav_tab
        old_navbar = self.navbar
        self.main_layout.removeWidget(old_navbar)
        old_navbar.deleteLater()
        self._create_vertical_navbar()
        # _create_vertical_navbar()가 활성 탭을 정산으로 초기화하므로 원래 보던 탭 복원
        self._on_navbar_clicked(current_tab)
        self.emit_log("[관리자] 일정/통관/보고 탭이 활성화되었습니다.")

    def _save_license_tier(self, tier):
        """config.json에 라이선스 등급 저장"""
        try:
            cfg = get_config_path()
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
        """업데이트 다운로드 시작 (커스텀 진행 다이얼로그)"""
        from PyQt6.QtWidgets import QProgressBar, QGraphicsDropShadowEffect
        from PyQt6.QtCore import Qt

        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setMinimumWidth(380)

        container = QWidget(dlg)
        container.setObjectName("update_dlg")
        container.setStyleSheet("""
            #update_dlg {
                background-color: rgba(45, 50, 60, 230);
                border: 1px solid #40464e;
                border-radius: 20px;
            }
        """)
        shadow = QGraphicsDropShadowEffect(dlg)
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(Qt.GlobalColor.black)
        container.setGraphicsEffect(shadow)

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.addWidget(container)

        inner = QVBoxLayout(container)
        inner.setContentsMargins(24, 28, 24, 20)
        inner.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        lbl_title = QLabel("업데이트")
        lbl_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #ffffff; background: transparent;")
        title_row.addStretch()
        title_row.addWidget(lbl_title)
        title_row.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(28, 28)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                color: rgba(255,255,255,0.5); font-size: 14px;
            }
            QPushButton:hover { color: #ff6b6b; }
        """)
        btn_close.clicked.connect(lambda: self._cancel_update())
        title_row.addWidget(btn_close)
        inner.addLayout(title_row)

        lbl_msg = QLabel(f"TRADIS MH v{new_ver} 다운로드 중...")
        lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_msg.setFont(QFont("Segoe UI", 10))
        lbl_msg.setStyleSheet("color: rgba(255,255,255,0.7); background: transparent;")
        inner.addWidget(lbl_msg)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setFixedHeight(8)
        progress.setTextVisible(False)
        progress.setStyleSheet("""
            QProgressBar {
                background-color: rgba(30, 35, 45, 200);
                border: 1px solid #40464e;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #00d4ff;
                border-radius: 3px;
            }
        """)
        inner.addWidget(progress)

        self._update_progress = dlg
        self._update_progress_bar = progress
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()

        self._download_url = url
        self._new_ver = new_ver
        self._update_cancelled = False

        def _do_download():
            def on_progress(downloaded, total):
                if self._update_cancelled:
                    raise Exception("취소됨")
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    self.download_progress_signal.emit(pct)

            try:
                path = download_update(url, progress_callback=on_progress)
            except Exception as e:
                print(f"[업데이트 다운로드 예외] {e}")
                path = None
            if not self._update_cancelled:
                self.download_complete_signal.emit(path)

        threading.Thread(target=_do_download, daemon=True).start()

    def _cancel_update(self):
        """업데이트 다운로드 취소"""
        self._update_cancelled = True
        if hasattr(self, '_update_progress') and self._update_progress:
            self._update_progress.close()
            self._update_progress = None
            self._update_progress_bar = None
        self.emit_log("[업데이트] 다운로드가 취소되었습니다.")

    def _update_download_progress(self, pct):
        """다운로드 진행률 업데이트"""
        if hasattr(self, '_update_progress_bar') and self._update_progress_bar:
            self._update_progress_bar.setValue(pct)

    def _on_download_complete(self, tmp_path):
        """다운로드 완료 처리"""
        if hasattr(self, '_update_progress') and self._update_progress:
            self._update_progress.close()
            self._update_progress = None

        if not tmp_path:
            from gui.dialogs import JarvisMessageBox
            JarvisMessageBox.warning(self, "업데이트 실패", "다운로드에 실패했습니다.\n다음에 다시 시도해주세요.")
            return

        self.emit_log(f"[업데이트] v{self._new_ver} 다운로드 완료. 업데이트를 설치합니다...")

        # 업데이트 종료 시 closeEvent가 발생하지 않을 수 있으므로 미리 저장
        try:
            self.save_settings()
            self.emit_log("[업데이트] 설정 저장 완료.")
        except Exception as e:
            print(f"[업데이트] 설정 저장 실패: {e}")

        if apply_update(tmp_path):
            # PyInstaller _MEI 폴더 정리를 위해 정상 종료 필수
            # os._exit(0)는 atexit 핸들러를 스킵하여 _MEI 잔존 → DLL 로드 실패 유발
            def _clean_exit_for_update():
                QApplication.quit()  # Qt 이벤트 루프 종료 → sys.exit() → atexit → _MEI 정리

            # 10초 후에도 프로세스가 살아있으면 종료 (스레드 hang 대비)
            # sys.exit()로 atexit 핸들러(_MEI 정리) 실행 보장
            import time as _time
            def _force_exit():
                _time.sleep(10)
                try:
                    sys.exit(0)
                except SystemExit:
                    os._exit(0)  # sys.exit마저 실패 시 최후 수단
            threading.Thread(target=_force_exit, daemon=True).start()

            QTimer.singleShot(800, _clean_exit_for_update)
        else:
            from gui.dialogs import JarvisMessageBox
            JarvisMessageBox.warning(self, "업데이트", "개발 모드에서는 자동 업데이트가 지원되지 않습니다.")



if __name__ == "__main__":
    # Windows 작업 표시줄에 TRADIS 고유 아이콘·이름이 표시되도록 앱 ID 등록
    # (미등록 시 python 실행에서 기본 아이콘으로 묶이고 '작업 표시줄에 고정'이 깨짐)
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Haedo.TRADIS.MH")
    except Exception:
        pass

    instance_socket = check_single_instance()
    if not instance_socket:
        temp_app = QApplication(sys.argv)
        temp_app.setWindowIcon(QIcon(resource_path("app_icon.ico")))
        from gui.dialogs import JarvisMessageBox
        JarvisMessageBox.warning(None, "중복 실행", "TRADIS MH가 이미 실행 중입니다.")
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("app_icon.ico")))
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
