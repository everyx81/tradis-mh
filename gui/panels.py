# JARVIS GUI 패널 모듈
"""
패널 모듈:
- FileManagerWidget: 파일 관리 및 검색
"""
import os
import sys
import shutil
import threading
import subprocess
import json
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

from .widgets import (DropListWidget, JarvisPanel, DraggableSearchResultList,
                      DraggableTreeView, NeonButton, get_unique_filename, TargetListWidget)
from .utils import resource_path
from .styles import TARGET_LIST_STYLESHEET
from .dialogs import JarvisMessageBox
from .report_panel import ReportPanel

class FileManagerWidget(QWidget):
    # Signal for thread-safe UI refresh after export/import
    refresh_after_move_signal = pyqtSignal(int, list, list, str)  # (count, duplicates, selected_folders, base_path)
    search_result_signal = pyqtSignal(list)  # Everything 검색 결과 전달용 시그널
    quick_export_complete_signal = pyqtSignal(int, list, list, list)  # (count, duplicates, moved_folders, moved_dst_paths)
    tab_changed_signal = pyqtSignal(int, str)  # (탭 인덱스, 탭 이름) - 메인 콘텐츠 전환용
    
    # ReadyKorea 자동화 버튼 시그널
    rk_auto_input_clicked = pyqtSignal()  # 자동 입력 버튼 클릭
    rk_test_clicked = pyqtSignal()  # 테스트 버튼 클릭
    send_mail_clicked = pyqtSignal()  # 메일 발송 버튼 클릭
    start_monitoring_clicked = pyqtSignal()  # 모니터링 시작 버튼 클릭
    stop_monitoring_clicked = pyqtSignal()  # 모니터링 중지 버튼 클릭
    item_deleted = pyqtSignal()  # 항목 삭제 시그널
    admin_unlocked = pyqtSignal()  # 관리자 잠금 해제 시그널

    def __init__(self, parent=None, path_callback=None, archiver=None, license_tier="standard"):
        super().__init__(parent)
        self.license_tier = license_tier
        self.path_callback = path_callback
        self.archiver = archiver
        self.target_subfolders = []
        self.move_list_t1 = []
        self.browser_home_path = ""  # 홈 폴더 경로
        
        # Signal 연결: 백그라운드 쓰레드에서 emit되면 메인 쓰레드에서 슬롯 실행
        self.refresh_after_move_signal.connect(self._on_move_complete)
        self.search_result_signal.connect(self._display_search_results)
        self.quick_export_complete_signal.connect(self._on_quick_export_complete)
        
        self.init_ui()
        QTimer.singleShot(0, self.refresh_targets)
        self.load_config()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.tabs = QTabWidget()
        
        # TAB 1: Internal
        tab1 = QWidget()
        tab1.setStyleSheet("background-color: transparent;")
        t1_layout = QHBoxLayout(tab1)
        t1_layout.setContentsMargins(0, 0, 0, 0)
        t1_layout.setSpacing(5)
        
        # === 왼쪽 영역: 파일 리스트 + 버튼 ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.setSpacing(5)
        
        # 1. MOVE TARGET (폴더 리스트)
        target_header = QHBoxLayout()
        self.lbl_target_title = QLabel("1. MOVE TARGET")
        target_header.addWidget(self.lbl_target_title)
        target_header.addStretch()
        
        self.btn_refresh_target = NeonButton("↻", color="cyan")
        self.btn_refresh_target.setFixedSize(30, 22)
        self.btn_refresh_target.clicked.connect(self.refresh_targets)
        target_header.addWidget(self.btn_refresh_target)
        
        left_layout.addLayout(target_header)
        
        # 폴더 리스트 (TargetListWidget)
        self.list_target = TargetListWidget()
        self.list_target.delete_requested.connect(self._delete_target_folder)
        self.list_target.rename_requested.connect(self._rename_target_folder)
        self.list_target.setMaximumHeight(150)
        self.list_target.setStyleSheet(TARGET_LIST_STYLESHEET)
        self.list_target.itemClicked.connect(self._on_target_folder_clicked)
        # 폴더 우클릭 메뉴 (삭제 기능)
        self.list_target.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_target.customContextMenuRequested.connect(self._show_target_folder_context_menu)
        left_layout.addWidget(self.list_target)
        
        # 2. FILES TO MOVE
        file_header = QHBoxLayout()
        file_header.addWidget(QLabel("2. FILES TO MOVE (드래그해서 추가)"))
        file_header.addStretch()
        left_layout.addLayout(file_header)
        
        self.list_widget = DropListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget._restore_style()
        self.list_widget.items_dropped.connect(self._on_items_dropped)
        self.list_widget.refresh_needed.connect(lambda: self._load_folder_contents(self.list_widget.current_folder) if self.list_widget.current_folder else None)
        left_layout.addWidget(self.list_widget)
        
        # 하단 버튼
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(5)
        
        self.btn_to_import = NeonButton("→ 수입", color="cyan")
        self.btn_to_import.setFont(QFont("Malgun Gothic", 9, QFont.Weight.Bold))
        self.btn_to_import.clicked.connect(lambda: self._quick_export_to('import'))
        btn_layout.addWidget(self.btn_to_import, stretch=1)
        
        self.btn_to_export = NeonButton("→ 수출", color="cyan")
        self.btn_to_export.setFont(QFont("Malgun Gothic", 9, QFont.Weight.Bold))
        self.btn_to_export.clicked.connect(lambda: self._quick_export_to('export'))
        btn_layout.addWidget(self.btn_to_export, stretch=1)
        
        self.btn_toggle_search = NeonButton("🔍 검색", color="cyan")
        self.btn_toggle_search.setFont(QFont("Malgun Gothic", 9, QFont.Weight.Bold))
        self.btn_toggle_search.clicked.connect(self._toggle_search_panel)
        btn_layout.addWidget(self.btn_toggle_search, stretch=1)
        
        left_layout.addLayout(btn_layout)
        

        
        # === 오른쪽 영역: JARVIS SEARCH 패널 ===
        self.search_panel = JarvisPanel()
        self.search_panel.setMinimumWidth(480)
        self.search_panel.setMaximumWidth(480)
        search_panel_layout = QVBoxLayout(self.search_panel)
        # 여백을 넉넉하게 확장 (Left, Top, Right, Bottom)
        search_panel_layout.setContentsMargins(20, 25, 20, 25)
        search_panel_layout.setSpacing(15)
        
        # 1. 상단 그룹: 검색
        self.search_group = QWidget()
        self.search_group.setStyleSheet("background-color: transparent;")
        search_group_layout = QVBoxLayout(self.search_group)
        search_group_layout.setContentsMargins(0, 0, 0, 0)
        search_group_layout.setSpacing(3)
        
        self.search_header_layout = QHBoxLayout()
        self.lbl_search_icon = QLabel("🔍")
        self.lbl_search_icon.setStyleSheet("color: #00ffff; font-size: 12pt;")
        self.search_header_layout.addWidget(self.lbl_search_icon)
        self.lbl_search_text = QLabel("TRADIS SEARCH")
        self.lbl_search_text.setStyleSheet("color: #00ffff; font-weight: bold; font-size: 10pt;")
        self.search_header_layout.addWidget(self.lbl_search_text)
        self.search_header_layout.addStretch()
        btn_close_search = NeonButton("✕", color="cyan")
        btn_close_search.setFixedSize(25, 25)
        btn_close_search.clicked.connect(self._toggle_search_panel)
        self.search_header_layout.addWidget(btn_close_search)
        search_group_layout.addLayout(self.search_header_layout)
        
        self.search_input_module = QWidget()
        search_input_module_layout = QHBoxLayout(self.search_input_module)
        search_input_module_layout.setContentsMargins(0,0,0,0)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색어 입력 (업체명, BL번호)")
        self.search_input.returnPressed.connect(self._everything_search)
        self.search_input.setStyleSheet("""
            QLineEdit { background-color: rgba(2, 11, 20, 120); border: 2px solid #335566; border-radius: 8px; color: #ffffff; padding: 6px 10px; font-size: 10pt; }
            QLineEdit:focus { border: 2px solid #00ffff; }
        """)
        search_input_module_layout.addWidget(self.search_input, stretch=1)
        self.btn_search = NeonButton("SCAN", color="cyan")
        self.btn_search.setFixedSize(55, 32)
        self.btn_search.clicked.connect(self._everything_search)
        search_input_module_layout.addWidget(self.btn_search)
        search_group_layout.addWidget(self.search_input_module)
        
        self.search_result_list = DraggableSearchResultList()
        self.search_result_list.itemClicked.connect(self._on_search_result_clicked)
        search_group_layout.addWidget(self.search_result_list)
        
        self.search_status_label = QLabel("검색 결과 클릭 ↓ 하단 탐색기")
        self.search_status_label.setStyleSheet("color: #888; font-size: 8pt;")
        self.search_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        search_group_layout.addWidget(self.search_status_label)
        search_panel_layout.addWidget(self.search_group, stretch=1)
        
        # 2. 하단 그룹: 폴더 탐색기
        self.browser_group = QWidget()
        self.browser_group.setStyleSheet("background-color: transparent;")
        browser_group_layout = QVBoxLayout(self.browser_group)
        browser_group_layout.setContentsMargins(0, 0, 0, 0)
        browser_group_layout.setSpacing(3)
        
        self.browser_header_layout = QHBoxLayout()
        self.lbl_browser_icon = QLabel("📂")
        self.lbl_browser_icon.setStyleSheet("color: #00ffff; font-size: 11pt;")
        self.browser_header_layout.addWidget(self.lbl_browser_icon)
        self.lbl_browser_text = QLabel("FOLDER TREE")
        self.lbl_browser_text.setStyleSheet("color: #00ffff; font-weight: bold; font-size: 9pt;")
        self.browser_header_layout.addWidget(self.lbl_browser_text)
        self.btn_go_up = NeonButton("⬆", color="cyan")
        self.btn_go_up.setFixedSize(30, 26)
        self.btn_go_up.clicked.connect(self._browser_go_up)
        self.browser_header_layout.addWidget(self.btn_go_up)
        self.btn_go_home = NeonButton("🏠", color="cyan")
        self.btn_go_home.setFixedSize(30, 26)
        self.btn_go_home.clicked.connect(self._browser_go_home)
        self.browser_header_layout.addWidget(self.btn_go_home)
        self.btn_set_home = NeonButton("⚙", color="cyan")
        self.btn_set_home.setFixedSize(30, 26)
        self.btn_set_home.clicked.connect(self._set_browser_home)
        self.browser_header_layout.addWidget(self.btn_set_home)
        self.browser_header_layout.addStretch()
        browser_group_layout.addLayout(self.browser_header_layout)
        
        self.current_path_label = QLabel("경로: (폴더를 선택하세요)")
        self.current_path_label.setStyleSheet("color: #888; font-size: 8pt;")
        self.current_path_label.setWordWrap(True)
        browser_group_layout.addWidget(self.current_path_label)
        
        self.file_browser = DraggableTreeView()
        self.file_browser.doubleClicked.connect(self._browser_on_double_click)
        browser_group_layout.addWidget(self.file_browser)
        
        self.browser_hint = QLabel("→ 드래그하여 리스트에 추가")
        self.browser_hint.setStyleSheet("color: #00cccc; font-size: 9pt; font-weight: bold; padding: 5px;")
        self.browser_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        browser_group_layout.insertWidget(0, self.browser_hint)
        search_panel_layout.addWidget(self.browser_group, stretch=1)
        
        self.search_panel.setObjectName("JarvisSearchPanel")
        self.search_panel.setStyleSheet("#JarvisSearchPanel { border-left: 2px solid #00aaff; }")
        self.search_panel.hide()
        
        t1_layout.addWidget(left_widget, stretch=2)
        self.tabs.addTab(tab1, "MK1")
        
        # TAB 2: MK3 (일정관리) - 메모 위젯용 placeholder
        mk3_tab = QWidget()
        mk3_tab.setStyleSheet("background-color: transparent;")
        self.mk3_memo_layout = QVBoxLayout(mk3_tab)
        self.mk3_memo_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs.addTab(mk3_tab, "MK3")
        self.mk3_tab_widget = mk3_tab
        
        # TAB 3: VERONICA (통관) - admin 전용
        if self.license_tier != "admin":
            # standard: VERONICA/REPORT 탭 없이 바로 SETTINGS로
            self._setup_settings_tab()
            layout.addWidget(self.tabs)
            self.tabs.currentChanged.connect(self._on_tab_changed)
            return

        tab_veronica = QWidget()
        tab_veronica.setStyleSheet("background-color: transparent;")
        veronica_layout = QVBoxLayout(tab_veronica)
        veronica_layout.setContentsMargins(15, 20, 15, 20)
        veronica_layout.setSpacing(15)
        
        # 타이틀
        title_label = QLabel("⚡ 1분컷! 수출")
        title_label.setStyleSheet("color: #00ffff; font-size: 16pt; font-weight: bold;")
        veronica_layout.addWidget(title_label)
        
        # 설명
        desc_label = QLabel("메일 도착 → 엑셀 파싱 → 레디코리아 입력 → 필증 발송 (1분 이내)")
        desc_label.setStyleSheet("color: #888; font-size: 9pt;")
        veronica_layout.addWidget(desc_label)
        
        # 구분선
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #00aaaa;")
        veronica_layout.addWidget(line)
        
        # 상태 표시
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("모니터링 상태:"))
        self.veronica_status = QLabel("● 대기 중")
        self.veronica_status.setStyleSheet("color: #888; font-weight: bold;")
        status_layout.addWidget(self.veronica_status)
        status_layout.addStretch()
        veronica_layout.addLayout(status_layout)
        
        # 버튼 영역 (별도 행으로 분리하여 창 크기 영향 방지)
        monitor_btn_layout = QHBoxLayout()
        monitor_btn_layout.setSpacing(10)
        
        # START 버튼
        self.btn_monitor_start = NeonButton("START")
        self.btn_monitor_start.setFixedSize(80, 26)
        self.btn_monitor_start.clicked.connect(self.start_monitoring_clicked.emit)
        monitor_btn_layout.addWidget(self.btn_monitor_start)
        
        # STOP 버튼
        self.btn_monitor_stop = NeonButton("STOP", color="orange")
        self.btn_monitor_stop.setFixedSize(80, 26)
        self.btn_monitor_stop.setEnabled(False)
        self.btn_monitor_stop.clicked.connect(self.stop_monitoring_clicked.emit)
        monitor_btn_layout.addWidget(self.btn_monitor_stop)
        
        monitor_btn_layout.addStretch() # 왼쪽 정렬
        veronica_layout.addLayout(monitor_btn_layout)
        
        # 최근 감지된 메일 목록
        mail_header = QLabel("📧 최근 감지된 수출 요청")
        mail_header.setStyleSheet("color: #00cccc; font-weight: bold; margin-top: 10px;")
        veronica_layout.addWidget(mail_header)
        
        self.export_mail_list = QListWidget()
        self.export_mail_list.setMaximumHeight(150)
        self.export_mail_list.setStyleSheet("""
            QListWidget { 
                background-color: rgba(5, 15, 30, 200); 
                border: 1px solid #555; 
                border-radius: 8px; 
                color: #ffffff; 
                padding: 5px;
            }
            QListWidget::item { padding: 5px; }
            QListWidget::item:selected { background-color: rgba(0, 255, 255, 50); color: #00ffff; }
        """)
        
        # 우클릭 메뉴 설정 (삭제 기능)
        self.export_mail_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.export_mail_list.customContextMenuRequested.connect(self._show_mail_list_context_menu)
        
        veronica_layout.addWidget(self.export_mail_list)
        
        # 최근 파싱 결과
        parse_header = QLabel("📊 최근 파싱 결과")
        parse_header.setStyleSheet("color: #00cccc; font-weight: bold; margin-top: 10px;")
        veronica_layout.addWidget(parse_header)
        
        self.export_parse_result = QTextEdit()
        self.export_parse_result.setMaximumHeight(120)
        self.export_parse_result.setReadOnly(True)
        self.export_parse_result.setStyleSheet("""
            QTextEdit { 
                background-color: rgba(5, 15, 30, 200); 
                border: 1px solid #00aaaa; 
                border-radius: 8px; 
                color: #00ff88; 
                padding: 10px;
                font-family: 'Consolas', monospace;
            }
        """)
        self.export_parse_result.setPlaceholderText("아직 파싱된 데이터가 없습니다...")
        veronica_layout.addWidget(self.export_parse_result)
        
        # ReadyKorea 자동 입력 섹션
        rk_header = QLabel("🖥️ ReadyKorea 자동 입력")
        rk_header.setStyleSheet("color: #00cccc; font-weight: bold; margin-top: 15px;")
        veronica_layout.addWidget(rk_header)
        
        # 자동화 상태 표시
        rk_status_layout = QHBoxLayout()
        rk_status_layout.addWidget(QLabel("자동화 상태:"))
        self.rk_automation_status = QLabel("● 대기 중")
        self.rk_automation_status.setStyleSheet("color: #888; font-weight: bold;")
        rk_status_layout.addWidget(self.rk_automation_status)
        rk_status_layout.addStretch()
        veronica_layout.addLayout(rk_status_layout)
        
        # 버튼 영역
        rk_btn_layout = QHBoxLayout()
        rk_btn_layout.setSpacing(10)
        
        self.btn_rk_auto_input = NeonButton("▶ 자동 입력 실행", color="cyan")
        self.btn_rk_auto_input.setFixedHeight(35)
        # 커스텀 비활성화 스타일 적용 (실제 setEnabled(False) 대신)
        self._rk_button_enabled = False
        self.btn_rk_auto_input.setStyleSheet("""
            QPushButton {
                background-color: rgba(30, 30, 30, 150);
                border: 1px solid #333;
                border-radius: 10px;
                color: #444;
            }
        """)
        self.btn_rk_auto_input.clicked.connect(self.rk_auto_input_clicked.emit)
        rk_btn_layout.addWidget(self.btn_rk_auto_input)
        
        # 메일 발송 버튼 (비활성화 상태로 시작)
        self.btn_send_mail = NeonButton("📧 메일 발송", color="cyan")
        self.btn_send_mail.setFixedHeight(35)
        self._send_mail_enabled = False
        self.btn_send_mail.setStyleSheet("""
            QPushButton {
                background-color: rgba(30, 30, 30, 150);
                border: 1px solid #333;
                border-radius: 10px;
                color: #444;
            }
        """)
        self.btn_send_mail.clicked.connect(self.send_mail_clicked.emit)
        rk_btn_layout.addWidget(self.btn_send_mail)
        
        veronica_layout.addLayout(rk_btn_layout)
        
        # 자동화 로그
        self.rk_log = QTextEdit()
        self.rk_log.setMaximumHeight(100)
        self.rk_log.setReadOnly(True)
        self.rk_log.setStyleSheet("""
            QTextEdit { 
                background-color: rgba(5, 15, 30, 200); 
                border: 1px solid #555; 
                border-radius: 8px; 
                color: #aaaaaa; 
                padding: 8px;
                font-family: 'Consolas', monospace;
                font-size: 9pt;
            }
        """)
        self.rk_log.setPlaceholderText("자동화 로그가 여기에 표시됩니다...")
        veronica_layout.addWidget(self.rk_log)
        
        veronica_layout.addStretch()
        self.tabs.addTab(tab_veronica, "VERONICA")

        # TAB 4: REPORT (일일 보고서)
        self.report_panel = ReportPanel()
        self.report_panel.log_signal.connect(self.emit_log)
        self.tabs.addTab(self.report_panel, "REPORT")

        self._setup_settings_tab()
        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _setup_settings_tab(self):
        """SETTINGS 탭 생성"""
        tab4 = QWidget()
        tab4.setStyleSheet("background-color: transparent;")
        t4_layout = QVBoxLayout(tab4)
        t4_layout.setContentsMargins(10, 20, 10, 20)
        t4_layout.setSpacing(15)
        t4_layout.addWidget(QLabel("폴더 정리 경로 설정"))
        
        self.btn_set_imp = NeonButton("SET IMPORT ROOT")
        self.btn_set_imp.clicked.connect(lambda: self.set_root('import'))
        self.lbl_imp_root = QLabel("Not Set")
        self.lbl_imp_root.setStyleSheet("color: #555; font-size: 8pt;")
        t4_layout.addWidget(self.btn_set_imp)
        t4_layout.addWidget(self.lbl_imp_root)
        
        self.btn_set_exp = NeonButton("SET EXPORT ROOT")
        self.btn_set_exp.clicked.connect(lambda: self.set_root('export'))
        self.lbl_exp_root = QLabel("Not Set")
        self.lbl_exp_root.setStyleSheet("color: #555; font-size: 8pt;")
        t4_layout.addWidget(self.btn_set_exp)
        t4_layout.addWidget(self.lbl_exp_root)
        
        self.btn_set_exp_docs = NeonButton("SET EXPORT DOCS SOURCE")
        self.btn_set_exp_docs.clicked.connect(lambda: self.set_root('export_docs'))
        self.lbl_exp_docs_root = QLabel("Not Set")
        self.lbl_exp_docs_root.setStyleSheet("color: #555; font-size: 8pt;")
        t4_layout.addWidget(self.btn_set_exp_docs)
        t4_layout.addWidget(self.lbl_exp_docs_root)
        
        # === 매뉴얼 섹션 ===
        t4_layout.addSpacing(10)
        self.btn_show_manual = NeonButton("📘 사용자 매뉴얼 보기", color="cyan")
        self.btn_show_manual.setFixedHeight(40)
        self.btn_show_manual.clicked.connect(self._show_manual_dialog)
        t4_layout.addWidget(self.btn_show_manual)

        # === 한비로 메일 설정 섹션 ===
        t4_layout.addSpacing(20)
        lbl_mail_header = QLabel("HANBIRO MAIL SETTING")
        lbl_mail_header.setStyleSheet("color: #00ffff; font-weight: bold;")
        t4_layout.addWidget(lbl_mail_header)
        
        # ID 입력 (자동으로 @raeon.co.kr 추가)
        mail_row1 = QHBoxLayout()
        mail_row1.addWidget(QLabel("ID:"))
        self.input_hanbiro_email = QLineEdit()
        self.input_hanbiro_email.setPlaceholderText("userid")
        self.input_hanbiro_email.setStyleSheet("""
            QLineEdit { 
                background-color: rgba(5, 15, 30, 200); 
                border: 1px solid #00aaaa; 
                border-radius: 5px; 
                color: #ffffff; 
                padding: 5px; 
            }
        """)
        mail_row1.addWidget(self.input_hanbiro_email)
        lbl_domain = QLabel("@raeon.co.kr")
        lbl_domain.setStyleSheet("color: #00aaaa; font-weight: bold;")
        mail_row1.addWidget(lbl_domain)
        t4_layout.addLayout(mail_row1)
        
        # 비밀번호 입력
        mail_row2 = QHBoxLayout()
        mail_row2.addWidget(QLabel("Password:"))
        self.input_hanbiro_password = QLineEdit()
        self.input_hanbiro_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_hanbiro_password.setPlaceholderText("********")
        self.input_hanbiro_password.setStyleSheet("""
            QLineEdit { 
                background-color: rgba(5, 15, 30, 200); 
                border: 1px solid #00aaaa; 
                border-radius: 5px; 
                color: #ffffff; 
                padding: 5px; 
            }
        """)
        mail_row2.addWidget(self.input_hanbiro_password)
        t4_layout.addLayout(mail_row2)
        
        # 저장 및 테스트 버튼
        mail_btn_row = QHBoxLayout()
        self.btn_save_mail = NeonButton("SAVE", color="cyan")
        self.btn_save_mail.clicked.connect(self._save_hanbiro_settings)
        mail_btn_row.addWidget(self.btn_save_mail)
        
        self.btn_test_mail = NeonButton("TEST CONNECTION", color="cyan")
        self.btn_test_mail.clicked.connect(self._test_hanbiro_connection)
        mail_btn_row.addWidget(self.btn_test_mail)
        t4_layout.addLayout(mail_btn_row)
        
        # 연결 상태 표시
        self.lbl_mail_status = QLabel("Status: Not configured")
        self.lbl_mail_status.setStyleSheet("color: #888; font-size: 8pt;")
        t4_layout.addWidget(self.lbl_mail_status)
        
        # === 관리자 잠금 해제 섹션 ===
        t4_layout.addSpacing(20)
        lbl_admin_header = QLabel("ADMIN UNLOCK")
        lbl_admin_header.setStyleSheet("color: #ff88ff; font-weight: bold;")
        t4_layout.addWidget(lbl_admin_header)

        admin_row = QHBoxLayout()
        self.input_admin_pw = QLineEdit()
        self.input_admin_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_admin_pw.setPlaceholderText("관리자 비밀번호")
        self.input_admin_pw.setStyleSheet("""
            QLineEdit {
                background-color: rgba(5, 15, 30, 200);
                border: 1px solid #ff88ff;
                border-radius: 5px;
                color: #ffffff;
                padding: 5px;
            }
        """)
        admin_row.addWidget(self.input_admin_pw)

        self.btn_admin_unlock = NeonButton("UNLOCK", color="magenta")
        self.btn_admin_unlock.clicked.connect(self._on_admin_unlock)
        admin_row.addWidget(self.btn_admin_unlock)
        t4_layout.addLayout(admin_row)

        self.lbl_admin_status = QLabel("Status: Standard")
        self.lbl_admin_status.setStyleSheet("color: #888; font-size: 8pt;")
        t4_layout.addWidget(self.lbl_admin_status)

        # admin 상태면 UI 반영
        if self.license_tier == "admin":
            self.lbl_admin_status.setText("Status: Admin ✓")
            self.lbl_admin_status.setStyleSheet("color: #ff88ff; font-size: 8pt;")
            self.input_admin_pw.setEnabled(False)
            self.btn_admin_unlock.setEnabled(False)

        t4_layout.addStretch()
        self.tabs.addTab(tab4, "SETTINGS")
    
    def _on_tab_changed(self, index):
        tab_name = self.tabs.tabText(index)
        self.tab_changed_signal.emit(index, tab_name)

    def _calculate_target_geometry(self):
        """탐색창의 목표 형상 (Right Panel에 맞춤)"""
        parent = self.search_panel.parent()
        # 기본값
        x, y, w, h = 1000, 50, 480, 800
        if parent:
            w = 480
            h = parent.height() - 60
            x = parent.width() - 480
            y = 50
        
        try:
            if parent and hasattr(parent, 'right_panel'):
                rp = parent.right_panel
                # Right Panel의 전역 좌표 및 크기
                global_pos = rp.mapToGlobal(QPoint(0, 0))
                local_pos = parent.mapFromGlobal(global_pos)
                
                rp_x = local_pos.x()
                rp_y = local_pos.y()
                rp_h = rp.height()
                
                # 초기화 전(0) Fallback
                if rp_x < parent.width() * 0.5:
                    rp_x = int(parent.width() * 0.724)
                
                x = rp_x - 480
                y = rp_y
                h = rp_h
        except: pass
             
        if x < 10: x = 10
        return QRect(x, y, 480, h)

    def reposition_search_panel(self):
        """외부(Main Window) 리사이즈 시 위치 갱신용"""
        if self.search_panel.isVisible():
            geo = self._calculate_target_geometry()
            self.search_panel.setGeometry(geo)

    def _animate_search_panel(self, show):
        anim_targets = [
            (self.lbl_search_text, 200, 'typing', "TRADIS SEARCH"),
            (self.lbl_search_icon, 700, 'fade', None),
            (self.lbl_browser_text, 1000, 'typing', "FOLDER TREE"),
            (self.lbl_browser_icon, 1500, 'fade', None),
            (self.btn_go_up, 1650, 'fade', None),
            (self.search_input_module, 1800, 'fade', None),
            (self.search_result_list, 2000, 'fade', None),
            (self.file_browser, 2300, 'fade', None),
            (self.browser_hint, 2600, 'typing', "→ 드래그하여 리스트에 추가"),
        ]
        
        if show:
            self.search_group.show()
            self.browser_group.show()
            self.search_panel.set_core_opacity(0.0)
            if hasattr(self, 'pulse_group'): self.pulse_group.stop()

            for widget, delay, type_, content in anim_targets:
                effect = widget.graphicsEffect()
                if not effect or not isinstance(effect, QGraphicsOpacityEffect):
                    effect = QGraphicsOpacityEffect(widget)
                    widget.setGraphicsEffect(effect)
                
                if type_ == 'typing':
                    widget.setText("")
                    effect.setOpacity(1.0)
                else:
                    effect.setOpacity(0.0)
                widget.show()
            
            for w in [self.search_status_label, self.current_path_label]:
                if not w.graphicsEffect(): w.setGraphicsEffect(QGraphicsOpacityEffect(w))
                w.graphicsEffect().setOpacity(0.0)
                QTimer.singleShot(2500, lambda w=w: w.graphicsEffect().setOpacity(1.0))

            if not hasattr(self, 'glow_overlay'):
                self.glow_overlay = QWidget(self.search_panel)
                self.glow_overlay.setStyleSheet("background-color: #00ffff;")
                self.glow_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                self.glow_opacity = QGraphicsOpacityEffect(self.glow_overlay)
                self.glow_opacity.setOpacity(0.0)
                self.glow_overlay.setGraphicsEffect(self.glow_opacity)
            self.glow_overlay.resize(self.search_panel.size())
            self.glow_overlay.raise_()
            self.glow_overlay.show()
        
        self.anim_group = QParallelAnimationGroup()

        geo_anim = QPropertyAnimation(self.search_panel, b"geometry")
        geo_anim.setDuration(600)
        geo_anim.setEasingCurve(QEasingCurve.Type.OutBack if show else QEasingCurve.Type.InBack)
        
        target_geo = self._calculate_target_geometry()
        # 애니메이션 시작/끝 설정
        if show:
            geo_anim.setStartValue(QRect(target_geo.x(), target_geo.y(), 0, target_geo.height()))
            geo_anim.setEndValue(target_geo)
        else:
            current = self.search_panel.geometry()
            geo_anim.setStartValue(current)
            geo_anim.setEndValue(QRect(target_geo.x(), target_geo.y(), 0, target_geo.height()))
            
        self.anim_group.addAnimation(geo_anim)

        if show:
            core_anim = QPropertyAnimation(self.search_panel, b"core_opacity_prop")
            core_anim.setDuration(2000)
            core_anim.setStartValue(0.0)
            core_anim.setEndValue(0.8)
            core_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
            self.anim_group.addAnimation(core_anim)
        else:
            core_anim = QPropertyAnimation(self.search_panel, b"core_opacity_prop")
            core_anim.setDuration(500)
            core_anim.setStartValue(self.search_panel.get_core_opacity())
            core_anim.setEndValue(0.0)
            self.anim_group.addAnimation(core_anim)
            if hasattr(self, 'pulse_group'): self.pulse_group.stop()

        if show:
            for widget, delay, type_, content in anim_targets:
                seq = QSequentialAnimationGroup()
                seq.addPause(delay)
                if type_ == 'typing':
                    char_duration = 30
                    total_dur = len(content) * char_duration 
                    anim = QVariantAnimation()
                    anim.setDuration(max(300, total_dur))
                    anim.setStartValue(0)
                    anim.setEndValue(len(content))
                    anim.valueChanged.connect(lambda v, w=widget, t=content: w.setText(t[:int(v)]))
                    seq.addAnimation(anim)
                else:
                    anim = QPropertyAnimation(widget.graphicsEffect(), b"opacity")
                    anim.setDuration(200)
                    anim.setStartValue(0.0)
                    anim.setEndValue(1.0)
                    anim.setEasingCurve(QEasingCurve.Type.OutExpo)
                    seq.addAnimation(anim)
                self.anim_group.addAnimation(seq)
            
            glow_seq = QSequentialAnimationGroup()
            glow_seq.addPause(2600)
            glow_in = QPropertyAnimation(self.glow_opacity, b"opacity")
            glow_in.setDuration(500)
            glow_in.setStartValue(0.0)
            glow_in.setEndValue(0.3)
            glow_seq.addAnimation(glow_in)
            glow_out = QPropertyAnimation(self.glow_opacity, b"opacity")
            glow_out.setDuration(1000)
            glow_out.setStartValue(0.3)
            glow_out.setEndValue(0.0)
            glow_seq.addAnimation(glow_out)
            self.anim_group.addAnimation(glow_seq)
            QTimer.singleShot(2500, lambda: self.glow_overlay.resize(self.search_panel.size()))
        else:
            if hasattr(self, 'glow_overlay'): self.glow_opacity.setOpacity(0.0)

        if not show:
            self.anim_group.finished.connect(self._on_search_panel_hidden)

        self.anim_group.start()

    def refresh_targets(self):
        try:
            if not self.isVisible() and self.parent() is None:
                return
            base_path = self.path_callback() if self.path_callback else ""
            # 불필요한 반복 로그 제거 (UI 리소스 낭비 방지)
            
            
            current_item = self.list_target.currentItem()
            current = current_item.data(Qt.ItemDataRole.UserRole) if current_item else ""
            
            if not base_path or not os.path.exists(base_path):
                self.target_subfolders = []
            else:
                try:
                    self.target_subfolders = sorted([d for d in os.listdir(base_path) if os.path.isdir(os.path.join(base_path, d))])
                except Exception as e:
                    self.emit_log(f"[오류] 폴더 목록 로드 실패: {e}")
                    self.target_subfolders = []
            
            self.list_target.clear()
            for folder in self.target_subfolders:
                item = QListWidgetItem(f"📁 {folder}")
                item.setData(Qt.ItemDataRole.UserRole, folder)
                self.list_target.addItem(item)
            
            # 이전 선택 폴더가 여전히 존재하는지 확인
            folder_still_exists = False
            if current:
                for i in range(self.list_target.count()):
                    item = self.list_target.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == current:
                        self.list_target.setCurrentItem(item)
                        folder_still_exists = True
                        break
            
            # 선택된 폴더가 삭제되었으면 FILES TO MOVE도 초기화
            if current and not folder_still_exists:
                self.list_widget.clear()
                self.current_target_folder = None
                self.emit_log(f"[상태] 폴더 '{current}'가 삭제되어 파일 목록 초기화")
                    
            if self.target_subfolders:
                self.lbl_target_title.setText(f"1. MOVE TARGET ({len(self.target_subfolders)} Found)")
            else:
                self.list_target.addItem(QListWidgetItem("(No Folders)"))
                self.lbl_target_title.setText("1. MOVE TARGET (0)")
                # 폴더가 없으면 FILES TO MOVE도 초기화
                self.list_widget.clear()
                self.current_target_folder = None
                
        except RuntimeError: return
        except Exception as e:
            print(f"Error in refresh_targets: {e}")
            if hasattr(self, 'target_subfolders'):
                self.lbl_target_title.setText(f"1. MOVE TARGET ({len(self.target_subfolders)} Found)")
            else:
                self.lbl_target_title.setText("1. MOVE TARGET (0)")

    def _on_target_folder_clicked(self, item):
        folder_name = item.data(Qt.ItemDataRole.UserRole)
        if not folder_name or folder_name == "(No Folders)": return
        base_path = self.path_callback() if self.path_callback else ""
        if not base_path: return
        folder_path = os.path.join(base_path, folder_name)
        if not os.path.exists(folder_path):
            self.emit_log(f"[오류] 폴더가 존재하지 않습니다: {folder_path}")
            return
        self.current_target_folder = folder_path
        self._load_folder_contents(folder_path)
        self.emit_log(f"[상태] 폴더 선택됨: {folder_name}")

    def _load_folder_contents(self, folder_path):
        self.list_widget.current_folder = folder_path
        self.list_widget.clear()
        try:
            items = os.listdir(folder_path)
            folders = sorted([f for f in items if os.path.isdir(os.path.join(folder_path, f))])
            files = sorted([f for f in items if os.path.isfile(os.path.join(folder_path, f))])
            for folder in folders:
                item = QListWidgetItem(f"📁 {folder}")
                item.setData(Qt.ItemDataRole.UserRole, os.path.join(folder_path, folder))
                self.list_widget.addItem(item)
            for file in files:
                item = QListWidgetItem(f"📄 {file}")
                item.setData(Qt.ItemDataRole.UserRole, os.path.join(folder_path, file))
                self.list_widget.addItem(item)
        except Exception as e:
             self.emit_log(f"[오류] 폴더 내용 로드 실패: {e}")



    def add_native_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "파일 선택", "", "All Files (*)")
        if files: self.add_dropped_items(files)

    def add_native_folder_new(self):
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택")
        if folder: self.add_dropped_items([folder])

    def add_dropped_items(self, paths):
        if paths:
            new_paths = [p for p in paths if p not in self.move_list_t1]
            self.move_list_t1.extend(new_paths)
            self.refresh_list_display()

    def _on_items_dropped(self, paths):
        if not paths: return
        if not hasattr(self, 'current_target_folder') or not self.current_target_folder:
            current_item = self.list_target.currentItem()
            if not current_item:
                self.add_dropped_items(paths)
                self.emit_log(f"[드래그 앤 드롭] {len(paths)}개 항목 추가됨 (대상 폴더 선택 필요)")
                return
            folder_name = current_item.data(Qt.ItemDataRole.UserRole)
            if not folder_name or folder_name == "(No Folders)":
                self.add_dropped_items(paths)
                return
            base_path = self.path_callback() if self.path_callback else ""
            self.current_target_folder = os.path.join(base_path, folder_name)
        
        dst_path = self.current_target_folder
        if not os.path.exists(dst_path):
            self.emit_log(f"[오류] 대상 폴더가 존재하지 않습니다: {dst_path}")
            return

        # 폴더가 포함되어 있으면 파일만 꺼낼지 물어보기
        has_folder = any(os.path.isdir(p) for p in paths)
        extract_files = False
        if has_folder:
            dlg = JarvisMessageBox(self, "폴더 이동", "폴더 안의 파일만 꺼내서 이동할까요?", JarvisMessageBox.Question)
            dlg.add_button("폴더째로", "as_is", "gray")
            dlg.add_button("파일만 꺼내기", "extract", "cyan")
            dlg.exec()
            extract_files = (dlg.result_value == "extract")

        moved_count = 0
        empty_folders = []  # 파일 꺼낸 후 삭제할 빈 폴더
        for src in paths:
            try:
                if extract_files and os.path.isdir(src):
                    # 폴더 안의 파일만 이동
                    for item in os.listdir(src):
                        item_path = os.path.join(src, item)
                        dest = os.path.join(dst_path, item)
                        if os.path.exists(dest): dest = get_unique_filename(dest)
                        shutil.move(item_path, dest)
                        moved_count += 1
                    empty_folders.append(src)
                else:
                    dest = os.path.join(dst_path, os.path.basename(src))
                    if os.path.exists(dest): dest = get_unique_filename(dest)
                    shutil.move(src, dest)
                    moved_count += 1
            except Exception as e:
                self.emit_log(f"[오류] 이동 실패: {os.path.basename(src)} - {e}")

        # 비어진 폴더 삭제
        for folder in empty_folders:
            try:
                if os.path.exists(folder) and not os.listdir(folder):
                    os.rmdir(folder)
            except Exception:
                pass

        if moved_count > 0:
            self._load_folder_contents(dst_path)
            self.emit_log(f"[완료] {moved_count}개 항목이 {os.path.basename(dst_path)}로 이동됨")

    def _toggle_search_panel(self):
        if self.search_panel.isVisible():
            self._animate_search_panel(False)
        else:
            self.search_panel.setMaximumWidth(0)
            self.search_panel.show()
            self._animate_search_panel(True)
            self.btn_toggle_search.setText("◀ CLOSE")
            self.search_input.setFocus()

    def _on_search_panel_hidden(self):
        self.search_panel.hide()
        self.search_panel.setMaximumWidth(480)
        self.btn_toggle_search.setText("🔍 SEARCH")

    def _get_es_path(self):
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        local_es = os.path.join(base_dir, "es.exe")
        if os.path.exists(local_es): return local_es
        return "es.exe"

    def _everything_search(self):
        query = self.search_input.text().strip()
        if not query:
            self.search_status_label.setText("검색어를 입력하세요")
            return
        self.search_status_label.setText("검색 중...")
        self.search_result_list.clear()
        
        def run_search():
            try:
                es_path = self._get_es_path()
                self.emit_log(f"[DEBUG] es.exe 경로: {es_path}")
                result = subprocess.run([es_path, "-n", "100", query], capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
                try: output = result.stdout.decode('cp949')
                except: output = result.stdout.decode('utf-8', errors='replace')
                try: stderr = result.stderr.decode('cp949')
                except: stderr = result.stderr.decode('utf-8', errors='replace')
                
                if stderr:
                    QTimer.singleShot(0, lambda: self._search_error(f"Everything 오류: {stderr}"))
                    return
                paths = [line.strip() for line in output.split('\n') if line.strip()]
                self.emit_log(f"[Everything] 검색어: {query}, 결과: {len(paths)}개")
                self.search_result_signal.emit(list(paths))
            except FileNotFoundError:
                QTimer.singleShot(0, lambda: self._search_error("es.exe를 찾을 수 없습니다."))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._search_error(f"검색 오류: {e}"))
        
        threading.Thread(target=run_search, daemon=True).start()

    def _display_search_results(self, paths):
        self.search_result_list.clear()
        if not paths:
            self.search_status_label.setText("검색 결과 없음")
            return
        for p in paths:
            icon = "📁" if os.path.isdir(p) else "📄"
            name = os.path.basename(p)
            item = QListWidgetItem(f"{icon} {name}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p)
            self.search_result_list.addItem(item)
        self.search_status_label.setText(f"검색 결과 {len(paths)}개 ↑ 드래그하여 추가")

    def _search_error(self, message):
        self.search_status_label.setText(message)
        self.emit_log(f"[Everything] {message}")

    def _on_search_result_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            if os.path.isdir(path):
                self.file_browser.navigate_to(path)
                self.current_path_label.setText(f"경로: {path}")
            else:
                parent_dir = os.path.dirname(path)
                self.file_browser.navigate_to(parent_dir)
                self.current_path_label.setText(f"경로: {parent_dir}")

    def _browser_go_up(self):
        self.file_browser.go_up()
        self.current_path_label.setText(f"경로: {self.file_browser.current_path}")

    def _browser_go_home(self):
        if self.browser_home_path and os.path.isdir(self.browser_home_path):
            self.file_browser.navigate_to(self.browser_home_path)
            self.current_path_label.setText(f"경로: {self.browser_home_path}")
            self.emit_log(f"[탐색기] 홈 폴더로 이동: {self.browser_home_path}")
        else:
            JarvisMessageBox.information(self, "홈 폴더", "홈 폴더가 설정되지 않았습니다.")

    def _set_browser_home(self):
        current_path = getattr(self.file_browser, 'current_path', None)
        if current_path and os.path.isdir(current_path):
            self.browser_home_path = current_path
            # 설정은 JarvisGUI.save_settings()에서 통합 저장됨
            self.emit_log(f"[탐색기] 홈 폴더 설정: {current_path}")
            JarvisMessageBox.information(self, "홈 폴더 설정", f"홈 폴더가 설정되었습니다:\n{current_path}")
        else:
            JarvisMessageBox.warning(self, "오류", "현재 폴더를 확인할 수 없습니다.")

    def load_config(self):
        try:
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.browser_home_path = config.get('browser_home_path', "")
                    if self.browser_home_path and os.path.isdir(self.browser_home_path):
                         # UI 초기화 후 실행을 위해 지연 호출
                         QTimer.singleShot(500, lambda: self.file_browser.navigate_to(self.browser_home_path))
                         QTimer.singleShot(500, lambda: self.current_path_label.setText(f"경로: {self.browser_home_path}"))
                    
                    # 한비로 메일 설정 로드
                    hanbiro = config.get('hanbiro_mail', {})
                    if hasattr(self, 'input_hanbiro_email'):
                        email = hanbiro.get('email', '')
                        # 이메일에서 ID만 추출 (@raeon.co.kr 제거)
                        user_id = email.replace('@raeon.co.kr', '') if email else ''
                        self.input_hanbiro_email.setText(user_id)
                        self.input_hanbiro_password.setText(hanbiro.get('password', ''))
                        if email:
                            self.lbl_mail_status.setText(f"Status: Configured ({email})")
        except Exception as e:
            print(f"Config Load Error: {e}")

    def _browser_on_double_click(self, index):
        path = self.file_browser.file_model.filePath(index)
        if os.path.isdir(path):
            self.file_browser.navigate_to(path)
            self.current_path_label.setText(f"경로: {path}")

    def delete_selected_items(self):
        selected_items = self.list_widget.selectedItems()
        if not selected_items: return
        for item in selected_items:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path in self.move_list_t1: self.move_list_t1.remove(path)
        self.refresh_list_display()

    def refresh_list_display(self):
        self.list_widget.clear()
        for p in self.move_list_t1:
            icon = "📁" if os.path.isdir(p) else "📄"
            name = os.path.basename(p)
            item = QListWidgetItem(f"{icon} {name}")
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.list_widget.addItem(item)

    def execute_move(self):
        if not hasattr(self, 'current_target_folder') or not self.current_target_folder:
            current_item = self.list_target.currentItem()
            if not current_item:
                JarvisMessageBox.information(self, "파일 이동", "먼저 MOVE TARGET에서 대상 폴더를 선택해 주세요.")
                return
            folder_name = current_item.data(Qt.ItemDataRole.UserRole)
            if not folder_name or folder_name == "(No Folders)": return
            base_path = self.path_callback() if self.path_callback else ""
            self.current_target_folder = os.path.join(base_path, folder_name)
        
        dst_path = self.current_target_folder
        if not os.path.exists(dst_path):
            JarvisMessageBox.warning(self, "오류", f"대상 폴더가 존재하지 않습니다:\n{dst_path}")
            return
        
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            JarvisMessageBox.information(self, "파일 이동", "이동할 파일을 먼저 선택(클릭)해 주세요.")
            return

        to_move = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]
        moved_count = 0
        for src in to_move:
            try:
                dest = os.path.join(dst_path, os.path.basename(src))
                if os.path.exists(dest): dest = get_unique_filename(dest)
                shutil.move(src, dest)
                moved_count += 1
                if src in self.move_list_t1: self.move_list_t1.remove(src)
            except Exception as e: print(f"Move Error for {src}: {e}")
        
        if moved_count > 0:
            self._load_folder_contents(dst_path)
            self.emit_log(f"[완료] {moved_count}개 항목 이동됨")

    def _quick_export_to(self, mode):
        root = self.archiver.import_root if mode == 'import' else self.archiver.export_root
        if not root:
             JarvisMessageBox.warning(self, "오류", f"{'가져오기' if mode == 'import' else '내보내기'} 경로가 설정되지 않았습니다!")
             return

        base_path = self.path_callback() if self.path_callback else ""
        if not base_path: return

        selected_items = self.list_target.selectedItems()
        if not selected_items:
            JarvisMessageBox.information(self, "내보내기", "MOVE TARGET에서 내보낼 폴더를 먼저 선택(클릭)해 주세요.")
            return

        selected_folders = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items if item.data(Qt.ItemDataRole.UserRole) != "(No Folders)"]
        valid_folders = []
        for folder_name in selected_folders:
            path = os.path.join(base_path, folder_name)
            if os.path.isdir(path):
                 parts = folder_name.split('_')
                 if len(parts) >= 2: valid_folders.append((path, folder_name))

        if not valid_folders:
            JarvisMessageBox.warning(self, "오류", "Company_ID 형식의 폴더가 선택되지 않았습니다.")
            return

        # 중복 사전 검사
        new_folders = []
        dup_folders = []  # (src_path, folder_name, existing_full_path)
        for src_path, folder_name in valid_folders:
            parts = folder_name.split('_')
            comp = parts[0]
            fid = "_".join(parts[1:])
            existing_rel = self._find_id_in_company_dir(root, comp, fid)
            if existing_rel:
                existing_full = os.path.join(root, existing_rel)
                dup_folders.append((src_path, folder_name, existing_full))
            else:
                new_folders.append((src_path, folder_name))

        # 중복이 있으면 사용자에게 물어보기
        dup_action = None  # "merge" or "new"
        if dup_folders:
            dup_names = [fn for _, fn, _ in dup_folders]
            dup_action = self._show_duplicate_merge_dialog(dup_names)
            # result: "merge" = 병합, "new" = 새 폴더, None = 취소
            if dup_action is None:
                return

        def run_move():
            count = 0
            duplicates = []
            moved_dst_paths = []
            self.emit_log(f"[{mode.upper()} 이동 시작] 대상: {len(valid_folders)}개 폴더")

            # 새 폴더 이동
            for src_path, folder_name in new_folders:
                parts = folder_name.split('_')
                comp = parts[0]
                fid = "_".join(parts[1:])

                existing_company_folder = self._find_company_folder(root, comp)
                if existing_company_folder: dst_parent = existing_company_folder
                else:
                    dst_parent = os.path.join(root, comp)
                    os.makedirs(dst_parent, exist_ok=True)

                dst = os.path.join(dst_parent, fid)
                try:
                    shutil.move(src_path, dst)
                    count += 1
                    moved_dst_paths.append(dst)
                    self.emit_log(f" -> [이동 성공] {folder_name} -> {comp}/{fid}")
                except Exception as e: self.emit_log(f" -> [이동 실패] {folder_name}: {e}")

            # 중복 폴더 처리
            for src_path, folder_name, existing_full in dup_folders:
                parts = folder_name.split('_')
                comp = parts[0]
                fid = "_".join(parts[1:])
                if dup_action == "merge":
                    # 병합: 파일 단위로 복사 (동일 파일 덮어쓰기, 새 파일 추가)
                    try:
                        merged = 0
                        for item in os.listdir(src_path):
                            src_item = os.path.join(src_path, item)
                            dst_item = os.path.join(existing_full, item)
                            if os.path.isfile(src_item):
                                shutil.copy2(src_item, dst_item)
                                merged += 1
                            elif os.path.isdir(src_item):
                                if os.path.exists(dst_item):
                                    # 하위 폴더도 파일 단위로 병합
                                    for sub in os.listdir(src_item):
                                        shutil.copy2(os.path.join(src_item, sub), os.path.join(dst_item, sub))
                                        merged += 1
                                else:
                                    shutil.copytree(src_item, dst_item)
                                    merged += 1
                        # 원본 폴더 삭제
                        shutil.rmtree(src_path)
                        count += 1
                        moved_dst_paths.append(existing_full)
                        self.emit_log(f" -> [병합 완료] {folder_name} ({merged}개 파일)")
                    except Exception as e:
                        self.emit_log(f" -> [병합 실패] {folder_name}: {e}")
                else:
                    # 새 폴더로 생성: 폴더명(1), (2), ...
                    dst_parent = os.path.dirname(existing_full)
                    base_fid = fid
                    n = 1
                    while True:
                        new_fid = f"{base_fid}({n})"
                        new_dst = os.path.join(dst_parent, new_fid)
                        if not os.path.exists(new_dst):
                            break
                        n += 1
                    try:
                        shutil.move(src_path, new_dst)
                        count += 1
                        moved_dst_paths.append(new_dst)
                        self.emit_log(f" -> [새 폴더] {folder_name} -> {comp}/{new_fid}")
                    except Exception as e:
                        self.emit_log(f" -> [새 폴더 실패] {folder_name}: {e}")

            import time
            time.sleep(0.3)
            self.quick_export_complete_signal.emit(count, duplicates, valid_folders, moved_dst_paths)

        threading.Thread(target=run_move, daemon=True).start()

    def _show_duplicate_merge_dialog(self, dup_names):
        """중복 폴더 발견 시 병합/새 폴더/취소 선택 다이얼로그

        Returns:
            "merge": 병합, "new": 새 폴더, None: 취소
        """
        names_text = "\n".join(f"  • {n}" for n in dup_names[:5])
        if len(dup_names) > 5:
            names_text += f"\n  ... 외 {len(dup_names) - 5}건"

        msg = f"이미 동일한 폴더가 {len(dup_names)}건 있습니다.\n\n{names_text}"

        dlg = JarvisMessageBox(self, "중복 폴더 발견", msg, JarvisMessageBox.Question)
        dlg.add_button("취소", "reject", "gray")
        dlg.add_button("새 폴더", "new", "gray")
        dlg.add_button("병합", "merge", "cyan")
        dlg.exec()

        if dlg.result_value == "merge":
            return "merge"
        elif dlg.result_value == "new":
            return "new"
        else:
            return None

    def _on_quick_export_complete(self, count, duplicates, moved_folders, moved_dst_paths=None):
        self.emit_log(f"[DEBUG] _on_quick_export_complete 호출됨: count={count}")
        for src_path, _ in moved_folders:
            if src_path in self.move_list_t1: self.move_list_t1.remove(src_path)
        self.refresh_list_display()
        self.refresh_targets()
        
        if count > 0: msg = f"{count}개의 폴더를 성공적으로 이동했습니다."
        else: msg = "이동된 폴더가 없습니다."
        if duplicates: msg += f"\n\n[중복 대량 제외] {len(duplicates)}건"
        
        # JarvisMessageBox 커스텀 사용: 폴더 열기 버튼 추가
        dlg = JarvisMessageBox(self, "작업 완료", msg, JarvisMessageBox.Information)
        dlg.add_button("확인", "accept", "cyan")
        if moved_dst_paths and count > 0:
            dlg.add_button("폴더 열기", "open_folder", "orange")
        dlg.exec()
        
        if dlg.result_value == "open_folder" and moved_dst_paths:
            path = os.path.normpath(moved_dst_paths[0])
            try:
                os.startfile(path)
            except Exception as e:
                self.emit_log(f"[오류] 폴더 열기 실패: {e}")



    def _find_id_in_company_dir(self, root, company, target_id):
        clean_company = company.replace("★", "").strip()
        try:
            # 1단계: root 직접 하위에서 회사 폴더 찾기
            for folder in os.listdir(root):
                folder_path = os.path.join(root, folder)
                if not os.path.isdir(folder_path): continue
                clean_folder = folder.replace("★", "").strip()
                if clean_folder.upper() == clean_company.upper():
                    if target_id in os.listdir(folder_path): return os.path.join(folder, target_id)
            
            # 2단계: root/*/하위에서 회사 폴더 찾기
            for parent_folder in os.listdir(root):
                parent_path = os.path.join(root, parent_folder)
                if not os.path.isdir(parent_path): continue
                try:
                    for sub_folder in os.listdir(parent_path):
                        sub_path = os.path.join(parent_path, sub_folder)
                        if not os.path.isdir(sub_path): continue
                        clean_sub = sub_folder.replace("★", "").strip()
                        if clean_sub.upper() == clean_company.upper():
                            if target_id in os.listdir(sub_path): 
                                return os.path.join(parent_folder, sub_folder, target_id)
                except PermissionError:
                    continue
        except: pass
        return None

    def _find_company_folder(self, root, company):
        clean_company = company.replace("★", "").strip()
        try:
            # 1단계: root 직접 하위 검색
            for folder in os.listdir(root):
                folder_path = os.path.join(root, folder)
                if not os.path.isdir(folder_path): continue
                clean_folder = folder.replace("★", "").strip()
                if clean_folder.upper() == clean_company.upper(): return folder_path
            
            # 2단계: root/*/하위 검색 (하위의 하위)
            for parent_folder in os.listdir(root):
                parent_path = os.path.join(root, parent_folder)
                if not os.path.isdir(parent_path): continue
                try:
                    for sub_folder in os.listdir(parent_path):
                        sub_path = os.path.join(parent_path, sub_folder)
                        if not os.path.isdir(sub_path): continue
                        clean_sub = sub_folder.replace("★", "").strip()
                        if clean_sub.upper() == clean_company.upper(): return sub_path
                except PermissionError:
                    continue
        except: pass
        return None

    def _on_move_complete(self, count, duplicates, selected_folders, base_path):
        self.emit_log(f"[상태] 이동 완료 (성공: {count}). UI를 갱신합니다.")
        for folder in selected_folders:
            abs_path = os.path.join(base_path, folder)
            if abs_path in self.move_list_t1: self.move_list_t1.remove(abs_path)
        self.refresh_targets()
        self.refresh_list_display()
        if count > 0 or duplicates:
            msg = f"{count}개의 폴더를 성공적으로 이동했습니다."
            if duplicates: msg += f"\n\n[알림] 중복으로 인한 제외: {len(duplicates)}건"
            JarvisMessageBox.information(self, "작업 완료", msg)
        else: self.emit_log("[알림] 이동된 항목이 없습니다.")

    def set_root(self, mode):
        d = QFileDialog.getExistingDirectory(self, f"Select {mode.upper()} Root")
        if d:
            if mode == 'import': 
                self.archiver.import_root = d
                self.lbl_imp_root.setText(d)
                self.lbl_imp_root.setStyleSheet("color: #00aaaa; font-size: 8pt;")
            elif mode == 'export': 
                self.archiver.export_root = d
                self.lbl_exp_root.setText(d)
                self.lbl_exp_root.setStyleSheet("color: #00aaaa; font-size: 8pt;")
            elif mode == 'export_docs':
                self.archiver.export_docs_root = d
                self.lbl_exp_docs_root.setText(d)
                self.lbl_exp_docs_root.setStyleSheet("color: #00aaaa; font-size: 8pt;")

    def emit_log(self, msg):
        if self.archiver and hasattr(self.archiver, 'log_callback') and self.archiver.log_callback:
            self.archiver.log_callback(msg)
        else:
            print(f"[FileManager Log] {msg}")

    def _on_admin_unlock(self):
        """관리자 비밀번호 검증"""
        from version import ADMIN_PASSWORD
        pw = self.input_admin_pw.text().strip()
        if not pw:
            JarvisMessageBox.warning(self, "오류", "비밀번호를 입력해주세요.")
            return

        if pw == ADMIN_PASSWORD:
            self.license_tier = "admin"
            self.lbl_admin_status.setText("Status: Admin ✓")
            self.lbl_admin_status.setStyleSheet("color: #ff88ff; font-size: 8pt;")
            self.input_admin_pw.setEnabled(False)
            self.btn_admin_unlock.setEnabled(False)
            self.admin_unlocked.emit()
            JarvisMessageBox.information(self, "관리자 모드", "관리자 모드가 활성화되었습니다.")
        else:
            JarvisMessageBox.warning(self, "오류", "비밀번호가 올바르지 않습니다.")
            self.input_admin_pw.clear()

    def _save_hanbiro_settings(self):
        """한비로 메일 설정 저장"""
        user_id = self.input_hanbiro_email.text().strip()
        password = self.input_hanbiro_password.text()
        
        if not user_id or not password:
            JarvisMessageBox.warning(self, "오류", "ID와 비밀번호를 모두 입력해주세요.")
            return
        
        # ID에 도메인 자동 추가
        email = f"{user_id}@raeon.co.kr"
        
        try:
            config = {}
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            config['hanbiro_mail'] = {
                'imap_server': 'raeon.hanbiro.net',
                'imap_port': 993,
                'email': email,
                'password': password
            }
            
            with open('config.json', 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            
            self.lbl_mail_status.setText(f"Status: Saved ({email})")
            self.lbl_mail_status.setStyleSheet("color: #00ff88; font-size: 8pt;")
            self.emit_log(f"[Mail] Hanbiro settings saved: {email}")
            JarvisMessageBox.information(self, "저장 완료", "한비로 메일 설정이 저장되었습니다.")
            
        except Exception as e:
            JarvisMessageBox.warning(self, "오류", f"저장 실패: {e}")
    
    def _test_hanbiro_connection(self):
        """한비로 IMAP 연결 테스트"""
        user_id = self.input_hanbiro_email.text().strip()
        password = self.input_hanbiro_password.text()
        
        if not user_id or not password:
            JarvisMessageBox.warning(self, "오류", "ID와 비밀번호를 먼저 입력해주세요.")
            return
        
        # ID에 도메인 자동 추가
        email = f"{user_id}@raeon.co.kr"
        
        self.lbl_mail_status.setText("Status: Testing connection...")
        self.lbl_mail_status.setStyleSheet("color: #ffaa00; font-size: 8pt;")
        QApplication.processEvents()
        
        # 동기 방식으로 테스트 (UI가 잠깐 멈출 수 있음)
        import imaplib
        import socket
        socket.setdefaulttimeout(10)  # 10초 타임아웃
        
        try:
            mail = imaplib.IMAP4_SSL('raeon.hanbiro.net', 993)
            mail.login(email, password)
            mail.logout()
            
            # 성공
            self.lbl_mail_status.setText(f"Status: Connected ({email})")
            self.lbl_mail_status.setStyleSheet("color: #00ff88; font-size: 8pt;")
            self.emit_log(f"[Mail] Connection test successful: {email}")
            JarvisMessageBox.information(self, "연결 성공", "한비로 메일 서버 연결에 성공했습니다!")
            
        except Exception as e:
            # 실패
            self.lbl_mail_status.setText(f"Status: Connection failed")
            self.lbl_mail_status.setStyleSheet("color: #ff4444; font-size: 8pt;")
            self.emit_log(f"[Mail] Connection test failed: {e}")
            JarvisMessageBox.warning(self, "연결 실패", f"연결 실패: {e}")
        
        finally:
            socket.setdefaulttimeout(None)
    
    def _on_test_complete(self, success, message, email):
        """연결 테스트 결과 처리"""
        if success:
            self.lbl_mail_status.setText(f"Status: Connected ({email})")
            self.lbl_mail_status.setStyleSheet("color: #00ff88; font-size: 8pt;")
            self.emit_log(f"[Mail] Connection test successful: {email}")
            JarvisMessageBox.information(self, "연결 성공", "한비로 메일 서버 연결에 성공했습니다!")
        else:
            self.lbl_mail_status.setText(f"Status: Connection failed")
            self.lbl_mail_status.setStyleSheet("color: #ff4444; font-size: 8pt;")
            self.emit_log(f"[Mail] Connection test failed: {message}")
            JarvisMessageBox.warning(self, "연결 실패", f"연결 실패: {message}")

    def _show_mail_list_context_menu(self, pos):
        """수출 요청 목록 우클릭 메뉴"""
        item = self.export_mail_list.itemAt(pos)
        if not item:
            return
        
        menu = QMenu(self)
        delete_action = QAction("❌ 목록에서 삭제", self)
        delete_action.triggered.connect(lambda: self._delete_mail_list_item(item))
        menu.addAction(delete_action)
        menu.exec(self.export_mail_list.mapToGlobal(pos))
        
    def _delete_mail_list_item(self, item):
        """목록에서 항목 삭제"""
        row = self.export_mail_list.row(item)
        self.export_mail_list.takeItem(row)
        # 삭제 후 시그널 발생 (연동 데이터 초기화용)
        self.item_deleted.emit()

    def _show_target_folder_context_menu(self, pos):
        """MOVE TARGET 폴더 우클릭 메뉴"""
        item = self.list_target.itemAt(pos)
        if not item:
            return
        
        folder_name = item.data(Qt.ItemDataRole.UserRole)
        if not folder_name or folder_name == "(No Folders)":
            return
        
        menu = QMenu(self)
        
        rename_action = QAction(f"✏️ '{folder_name}' 이름 변경 (F2)", self)
        rename_action.triggered.connect(lambda: self._rename_target_folder(folder_name))
        menu.addAction(rename_action)
        
        delete_action = QAction(f"🗑️ '{folder_name}' 폴더 삭제 (Delete)", self)
        delete_action.triggered.connect(lambda: self._delete_target_folder(folder_name))
        menu.addAction(delete_action)
        
        menu.exec(self.list_target.mapToGlobal(pos))
    
    def _rename_target_folder(self, folder_name: str):
        """MOVE TARGET 폴더 이름 변경"""
        base_path = self.path_callback() if self.path_callback else ""
        if not base_path:
            return
        
        old_path = os.path.join(base_path, folder_name)
        if not os.path.exists(old_path):
            return
            
        new_name, ok = QInputDialog.getText(self, "이름 변경", f"'{folder_name}'의 새 이름을 입력하세요:", text=folder_name)
        if ok and new_name and new_name != folder_name:
            new_path = os.path.join(base_path, new_name)
            try:
                if os.path.exists(new_path):
                    JarvisMessageBox.warning(self, "오류", "이미 존재하는 이름입니다.")
                    return
                
                os.rename(old_path, new_path)
                self.emit_log(f"[이름 변경] {folder_name} -> {new_name}")
                self.refresh_targets()
                
                # 변경된 폴더 자동 선택
                for i in range(self.list_target.count()):
                    item = self.list_target.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) == new_name:
                        self.list_target.setCurrentItem(item)
                        self._on_target_folder_clicked(item)
                        break
            except Exception as e:
                self.emit_log(f"[오류] 이름 변경 실패: {e}")
                JarvisMessageBox.critical(self, "오류", f"이름 변경 실패: {e}")
    
    def _delete_target_folder(self, folder_name: str):
        """MOVE TARGET 폴더 삭제"""
        base_path = self.path_callback() if self.path_callback else ""
        if not base_path:
            JarvisMessageBox.warning(self, "오류", "기본 경로가 설정되지 않았습니다.")
            return
        
        folder_path = os.path.join(base_path, folder_name)
        
        if not os.path.exists(folder_path):
            JarvisMessageBox.warning(self, "오류", f"폴더가 존재하지 않습니다:\n{folder_path}")
            return
        
        # 폴더 내 파일 수 확인
        try:
            file_count = sum(len(files) for _, _, files in os.walk(folder_path))
            subfolder_count = sum(len(dirs) for _, dirs, _ in os.walk(folder_path))
        except:
            file_count = 0
            subfolder_count = 0
        
        # 확인 대화상자
        warning_msg = f"'{folder_name}' 폴더를 삭제하시겠습니까?"
        if file_count > 0 or subfolder_count > 0:
            warning_msg += f"\n\n⚠️ 이 폴더에는 {file_count}개 파일, {subfolder_count}개 하위폴더가 있습니다.\n모두 삭제됩니다!"
        
        if not JarvisMessageBox.question(self, "폴더 삭제 확인", warning_msg):
            return
        
        try:
            import shutil
            shutil.rmtree(folder_path)
            self.emit_log(f"[삭제 완료] 폴더 삭제됨: {folder_name}")
            JarvisMessageBox.information(self, "완료", f"'{folder_name}' 폴더가 삭제되었습니다.")
            
            # 목록 갱신
            self.refresh_targets()
            
        except Exception as e:
            self.emit_log(f"[오류] 폴더 삭제 실패: {e}")
            JarvisMessageBox.critical(self, "삭제 실패", f"폴더 삭제 중 오류 발생:\n{str(e)}")

    def _show_manual_dialog(self):
        """사용자 매뉴얼 표시 다이얼로그"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton
        
        dlg = QDialog(self)
        dlg.setWindowTitle("TRADIS MH 사용자 매뉴얼")
        dlg.resize(700, 800)
        dlg.setStyleSheet("background-color: #050f1e; color: #ffffff;")
        
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 타이틀
        title = QLabel("📘 TRADIS MH 통합 매뉴얼")
        title.setStyleSheet("font-size: 18pt; font-weight: bold; color: #00ffff; margin-bottom: 15px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # 뷰어
        browser = QTextBrowser()
        browser.setStyleSheet("""
            QTextBrowser {
                background-color: rgba(30, 30, 30, 150);
                border: 1px solid #444;
                border-radius: 8px;
                font-family: 'Malgun Gothic', sans-serif;
                font-size: 11pt;
                padding: 15px;
                line-height: 1.6;
            }
        """)
        
        # 매뉴얼 내용 (코드 내장)
        manual_content = """
# TRADIS MH 사용자 매뉴얼

---

## 📌 TRADIS MH란?

**TRADIS MH**는 관세사무소 업무를 자동화하는 AI 어시스턴트입니다.

주요 기능:
- 📄 **파일 자동 분석/병합**: PDF 파일을 AI가 분석하고 같은 건의 서류를 자동 병합
- 📁 **파일 매니저**: 파일/폴더를 쉽게 정리하고 서버로 이동
- 📧 **수출 메일 자동화**: 수출 요청 메일 감지 → 자동 처리 → 답장 발송
- 📅 **일정 관리**: 업무 일정 등록 및 알림
- 📊 **일일 보고서**: 일일 업무 보고서 생성 및 메일 발송

---

## 🚀 처음 시작하기 (초기 설정)

### 1단계: 프로그램 실행
- `TRADIS_MH.exe` 파일을 더블클릭합니다.
- 처음 실행 시 인트로 화면이 나타난 후 메인 화면이 표시됩니다.

### 2단계: API 키 설정 (필수)
파일 자동 이름 변경 기능을 사용하려면 Gemini API 키가 필요합니다.

1. 좌측 사이드바 상단의 **"API KEY REQUIRED"** 부분을 클릭
2. Gemini API 키를 입력하고 **저장** 클릭
3. "AI STATUS: CONNECTED"로 변경되면 성공

> 💡 API 키가 없으면 파일 자동 이름 변경 기능을 사용할 수 없습니다.

### 3단계: 감시 폴더 설정
1. 좌측 사이드바의 **SELECT** 버튼 클릭
2. 파일을 감시할 폴더 선택 (예: 다운로드 폴더)
3. 폴더가 설정되면 경로가 표시됩니다

### 4단계: 모니터링 시작
- **START** 버튼을 클릭하면 파일 감시가 시작됩니다
- 새 PDF 파일이 해당 폴더에 들어오면 자동으로 분석됩니다

---

## 🖥️ 화면 구성

```
┌────────────────────────────────────────────────────────────┐
│  🔴🟡🟢  창 컨트롤                              ▼ ✕  │
├──────────┬────────────────────────────────────┬────────────┤
│          │                                    │            │
│  좌측    │         중앙 패널                   │  우측      │
│  사이드바 │      (분석 결과 표시)               │  NavBar    │
│          │                                    │            │
│ ▶ START  │                                    │  MK1       │
│ ⏹ STOP   │    이름 변경 제안 카드들            │ VERONICA   │
│ 📁 SET   │        표시 영역                   │  MK3       │
│          │                                    │  REPORT    │
├──────────┼────────────────────────────────────┴────────────┤
│          │              하단 탭 영역                        │
│          │    (MK1 / VERONICA / MK3 / REPORT / SETTINGS)  │
└──────────┴─────────────────────────────────────────────────┘
```

### 좌측 사이드바
| 버튼 | 기능 |
|------|------|
| **START** | 파일 자동 이름 변경 모니터링 시작 |
| **STOP** | 모니터링 중지 |
| **SELECT** | 감시할 폴더 경로 설정 |
| **API** | Gemini API 키 설정 |

### 우측 NavBar (탭 전환)
| 탭 | 기능 |
|-----|------|
| **MK1** | 파일 매니저 (파일 이동/정리) |
| **VERONICA** | 수출 메일 자동화 (1분컷 수출) |
| **MK3** | 일정 및 메모 관리 |
| **REPORT** | 일일 업무 보고서 생성/발송 |
| **⚙** | 환경 설정 |

---

## 📄 파일 자동 분석 및 병합 기능

### 작동 원리
1. 감시 폴더에 새 PDF 파일이 들어옴
2. AI가 PDF 내용을 분석하여 문서 유형 파악
3. 같은 ID의 문서들을 그룹으로 묶음
4. 중앙 패널에 그룹 카드 표시
5. **AI ANALYZE** 또는 **MATCH** 버튼으로 분석/병합 실행

### 사용 방법
1. **SELECT**로 감시 폴더 설정
2. **START** 클릭하여 모니터링 시작
3. PDF 파일을 해당 폴더에 복사/다운로드
4. 잠시 후 중앙 패널에 그룹 카드 표시
5. 카드에서 **AI ANALYZE** 또는 **MATCH** 버튼 클릭

### 그룹 카드 설명
```
┌───────────────────────────────────────────┐
│ ID: IV-123 (삼성전자)        [AI ANALYZE]  │
│ 통관수수료, 정산서, 수입신고필증...        │
├───────────────────────────────────────────┤
│ ▲▼ [파일 선택 콤보박스] 🔍 ➡ 통관수수료   │
│ ▲▼ [파일 선택 콤보박스] 🔍 ➡ 정산서       │
│              [+ ADD ROW]                   │
│            [MERGE EXECUTE]                 │
└───────────────────────────────────────────┘
```

- **AI ANALYZE**: AI가 정산서를 분석하여 파일 순서 자동 결정
- **MATCH**: 파일 유형별로 자동 매칭
- **☰ (드래그 핸들)**: 마우스로 드래그하여 파일 순서를 변경
- **🔍**: 파일 미리보기 (확대된 이미지 제공)
- **+ ADD ROW**: 수동으로 병합할 파일 행 추가
- **MERGE EXECUTE**: 선택된 파일들을 하나의 PDF로 병합

---

## 📁 MK1 탭 - 파일 매니저

### 화면 구성
```
┌─────────────────┬─────────────────────────────────────┐
│  1. MOVE TARGET │           2. FILES TO MOVE          │
│  (이동 대상)     │           (이동할 파일)             │
│                 │                                     │
│  📁 삼성전자    │  📄 파일1.pdf                        │
│  📁 LG전자      │  📄 파일2.pdf                        │
│  📁 현대차      │  📁 폴더1                            │
│                 │                                     │
├─────────────────┴─────────────────────────────────────┤
│  [파일 추가] [폴더 추가] [선택 이동] [IMPORT] [EXPORT] │
├───────────────────────────────────────────────────────┤
│  3. FILE BROWSER (파일 탐색기)                         │
│                                                       │
│  📁 문서 > 📁 2024년 > ...                            │
└───────────────────────────────────────────────────────┘
```

### 기본 사용법

#### 파일 이동하기
1. 좌측 **MOVE TARGET**에서 이동 대상 폴더 클릭
2. 우측 **FILES TO MOVE**에 파일 드래그 앤 드롭
3. 이동할 파일 선택 (클릭)
4. **선택 이동** 버튼 클릭

#### 드래그 앤 드롭
- Windows 탐색기에서 파일을 드래그하여 TRADIS MH 창에 드롭
- 자동으로 FILES TO MOVE 목록에 추가됨

#### 서버로 빠른 이동
- **IMPORT**: 선택된 폴더를 Import 서버 경로로 이동
- **EXPORT**: 선택된 폴더를 Export 서버 경로로 이동

> ⚠️ IMPORT/EXPORT 버튼을 사용하려면 먼저 SETTINGS에서 서버 경로를 설정해야 합니다.

### Everything 검색
1. **🔍 SEARCH** 버튼 클릭
2. 검색창에 파일명 입력
3. Enter 또는 검색 버튼 클릭
4. 검색 결과에서 파일 클릭하면 해당 위치로 이동

> 💡 Everything 검색을 사용하려면 Everything 프로그램이 설치되어 있어야 합니다.

---

## 📧 VERONICA 탭 - 수출 메일 자동화

> ⚠️ **주의**: 현재 이 기능은 **주식회사 와이에스씨** 수출 업무 전용입니다.

### 기능 개요
특정 형식의 수출 요청 메일을 자동 감지하고, 첨부된 엑셀 파일을 분석하여 ReadyKorea 프로그램에 자동 입력합니다.

### 화면 구성
```
┌─────────────────────────────────────────────────────────┐
│  📧 EXPORT MAIL MONITOR                                 │
│  ● 모니터링 중 (IDLE - 실시간)     [START] [STOP]       │
├───────────────────────────┬─────────────────────────────┤
│  수출 요청 목록           │  파싱 결과                   │
│                           │                             │
│  [08:30:15] #292 ICN/BKK  │  품명: 반도체               │
│  [08:25:10] #291 ICN/HKG  │  수량: 100                  │
│                           │  총액: 10,000               │
├───────────────────────────┴─────────────────────────────┤
│  READYKOREA AUTOMATION                                  │
│  [▶ 자동 입력 실행]  [📧 메일 발송]                     │
└─────────────────────────────────────────────────────────┘
```

### 사용 방법

#### 1. 메일 설정 (최초 1회)
1. **SETTINGS** 탭으로 이동
2. **한비로 메일 설정** 영역에서:
   - ID 입력 (예: mhchoi)
   - 비밀번호 입력
3. **연결 테스트** 버튼으로 연결 확인
4. **저장** 버튼 클릭

#### 2. 메일 모니터링
1. VERONICA 탭에서 **START** 버튼 클릭
2. "모니터링 중 (IDLE - 실시간)" 상태 확인
3. 수출 요청 메일이 오면 자동으로 목록에 표시
4. 첨부된 엑셀 파일이 자동으로 다운로드 및 분석

#### 3. ReadyKorea 자동 입력
1. ReadyKorea 프로그램을 먼저 실행
2. 파싱 결과가 표시되면 **▶ 자동 입력 실행** 버튼이 활성화
3. 버튼 클릭 시 ReadyKorea에 데이터 자동 입력

#### 4. 답장 메일 발송
1. 수출신고필증이 감시 폴더에 저장되어 있어야 함
2. **📧 메일 발송** 버튼 클릭
3. 수출신고필증이 첨부된 답장 메일 자동 발송

---

## 📅 MK3 탭 - 일정 및 메모 관리

### 📅 일정 관리 (Schedule)
- **일정 추가**: 날짜/시간 및 메모 입력하여 저장
- **일정 알림**: 설정된 시간에 Windows 알림 및 팝업 표시
- **일정 편집/삭제**: 리스트에서 선택하여 수정 또는 삭제

### 📝 스마트 메모장 (Smart Memo)
- **다중 탭 관리**: `[+]` 버튼으로 여러 메모를 탭으로 관리
- **자동 저장**: 작성 내용은 실시간으로 자동 저장됨
- **AI 정리**:
    1. 메모 내용 작성 후 **[정리]** 버튼 클릭
    2. AI가 내용을 깔끔하게 재구성 (불릿 포인트, 요약)
    3. 결과가 마음에 들면 유지, 아니면 수정 가능

### 화면 구성
```
┌─────────────────────────────────────────────────────────┐
│  📅 SCHEDULE MANAGER                                    │
├────────────────────────┬────────────────────────────────┤
│      미니 캘린더       │         일정 목록              │
│                        │                                │
│    < 2026년 1월 >      │  📌 09:00 - 삼성 미팅          │
│  일 월 화 수 목 금 토  │  📌 14:00 - 서류 제출 마감     │
│     1  2  3  4  5  6   │  📌 16:30 - 통관 확인          │
│  7  8  9 ...           │                                │
├────────────────────────┴────────────────────────────────┤
│  [일정 추가]  [선택 편집]  [선택 삭제]                   │
└─────────────────────────────────────────────────────────┘
```

### 일정 추가하기
1. **일정 추가** 버튼 클릭
2. 일정 정보 입력:
   - 제목
   - 날짜
   - 시간
   - 메모 (선택)
3. **저장** 클릭

### 일정 알림
- 설정된 시간에 Windows 알림 팝업이 표시됩니다
- 화면 우측 하단에 토스트 알림으로 나타남
- 알림 시간은 일정 시작 시간에 맞춰 발생

### 일정 수정/삭제
- **수정**: 일정 선택 후 **선택 편집** 클릭
- **삭제**: 일정 선택 후 **선택 삭제** 클릭

---

## 📊 REPORT 탭 - 일일 업무 보고서

### 기능 개요
일일 업무 보고서를 작성하고 PDF 저장 및 메일 발송을 지원합니다.

### 화면 구성
```
┌──────────────────────────┬──────────────────────────────┐
│     📝 데이터 입력       │      📄 서류 미리보기        │
│                          │                              │
│  보고 날짜: 2026-01-25   │  ┌────────────────────────┐ │
│                          │  │ 일일 업무 보고서        │ │
│  📈 통관 실적            │  │                        │ │
│  당일 건수: 15           │  │ 통관 실적              │ │
│  당일 수수료: 750,000    │  │ 미수금 현황            │ │
│  월 누계 건수: 285       │  │ 대납금 현황            │ │
│  월 누계 수수료: 14.25M  │  │ 특이사항               │ │
│                          │  └────────────────────────┘ │
│  💰 미수금               │                              │
│  [+ 업체, 금액, 예정일]  │                              │
│                          │                              │
│  🏦 대납금       [가져오기]                              │
│  [+ 업체, 금액, 예정일]  │                              │
│                          │                              │
│  📝 특이사항             │                              │
│  [텍스트 입력 영역]       │                              │
├──────────────────────────┴──────────────────────────────┤
│      [📄 PDF 저장]    [📧 메일 발송]    [🗑️ 초기화]     │
└─────────────────────────────────────────────────────────┘
```

### 사용 방법

#### 1. 데이터 입력
1. **보고 날짜** 선택
2. **통관 실적** 입력 (건수, 수수료)
3. **미수금/대납금** 항목 추가 (+버튼)
4. **확인** 체크박스: 입금 확인된 항목 체크
5. **특이사항** 입력

#### 2. 대납금 데이터 가져오기
1. **가져오기** 버튼 클릭
2. Google Sheets 대납장에서 자동으로 데이터 로드
3. 이미 보고된 항목(보고일자 있음)은 제외됨

#### 3. PDF 저장
- **📄 PDF 저장** 버튼 클릭
- `일일보고` 폴더에 날짜별 PDF 파일 저장

#### 4. 메일 발송
1. **📧 메일 발송** 버튼 클릭
2. 받는 사람, 참조 입력
3. 발송 완료 시:
   - **체크된 항목 자동 삭제**
   - **스프레드시트 보고일자 자동 기록**

### 스프레드시트 연동

#### 필요 설정
스프레드시트 대납장에 다음 열이 필요합니다:
| 업체명 | 금액 | 입금예정일 | 확인 | **보고일자** |
|--------|------|------------|------|-------------|

- **확인**: 입금 확인 시 "확인" 또는 "O" 입력
- **보고일자**: 메일 발송 시 TRADIS MH가 자동 기록 (직접 입력 불필요)

#### 동작 흐름
1. 스프레드시트에서 "확인" 입력 (입금됨)
2. TRADIS MH에서 "가져오기" → 확인된 항목 표시
3. 메일 발송 → 스프레드시트에 보고일자 자동 기록
4. 다음 가져오기 시 보고일자가 있는 항목은 제외됨

---

## ⚙ SETTINGS 탭 - 환경 설정

### 설정 항목

#### 1. Import/Export 경로 설정
- **IMPORT 경로**: Import 서버 폴더 경로 설정
- **EXPORT 경로**: Export 서버 폴더 경로 설정
- MK1 탭의 빠른 이동 버튼에서 사용됨

#### 2. 한비로 메일 설정
- **ID**: 한비로 메일 ID (예: mhchoi)
- **비밀번호**: 한비로 메일 비밀번호
- **연결 테스트**: 설정이 올바른지 확인
- **저장**: 설정 저장

#### 3. 사용자 매뉴얼
- 이 매뉴얼을 표시합니다

---

## ❓ 자주 묻는 질문 (FAQ)

### Q: API 키는 어디서 얻나요?
A: Google AI Studio (https://aistudio.google.com)에서 무료로 발급받을 수 있습니다.

### Q: 파일이 자동으로 분석되지 않아요
A: 다음을 확인하세요:
1. API 키가 설정되어 있는지 (AI STATUS: CONNECTED)
2. START 버튼을 눌러 모니터링 중인지
3. 감시 폴더 경로가 올바른지

### Q: 메일 모니터링이 안 돼요
A: 다음을 확인하세요:
1. SETTINGS에서 한비로 메일 설정이 완료되었는지
2. 연결 테스트가 성공했는지
3. VERONICA 탭에서 START를 눌렀는지

### Q: ReadyKorea 자동 입력이 안 돼요
A: 다음을 확인하세요:
1. ReadyKorea 프로그램이 실행 중인지
2. ReadyKorea 창이 화면에 보이는지
3. 수출 데이터가 파싱되어 버튼이 활성화되었는지

### Q: 미니 윈도우로 최소화했는데 복원이 안 돼요
A: 화면 우측 하단에 작은 TRADIS MH 바가 있습니다. ◀ 버튼을 클릭하면 복원됩니다.

### Q: 대납금 가져오기가 안 돼요
A: 다음을 확인하세요:
1. credentials.json 파일이 프로젝트 폴더에 있는지
2. 스프레드시트 대납장에 "보고일자" 열이 있는지
3. 스프레드시트 공유 설정이 올바른지

---

## 🔧 문제 해결

### "API KEY REQUIRED" 오류
→ 좌측 사이드바 상단을 클릭하여 Gemini API 키를 입력하세요.

### "폴더를 찾을 수 없습니다" 오류
→ SELECT 버튼으로 올바른 폴더 경로를 다시 설정하세요.

### 프로그램이 느려졌어요
→ 프로그램을 재시작하거나, 불필요한 로그를 정리하세요.

### Everything 검색이 안 돼요
→ Everything 프로그램이 설치되어 있고 실행 중인지 확인하세요.
   (https://www.voidtools.com 에서 다운로드)

### "스프레드시트에 '보고일자' 열이 없습니다" 오류
→ Google Sheets 대납장에 "보고일자" 열을 추가하세요.

---

## 📋 버전 정보

**현재 버전**: 1.3

### 변경 이력

#### v1.3 (2026-02-07)
- 📝 **스마트 메모장**: 멀티 탭, AI 자동 정리 기능 추가
- 🔄 **정산 병합 개선**: 드래그앤드롭 순서 변경, 미리보기 확대
- 🎨 **UI 개선**: 다크 테마 및 HUD 스타일 최적화

#### v1.2 (2026-01-25)
- 📊 **REPORT 탭 추가**: 일일 업무 보고서 생성/발송 기능
- 🔄 **스프레드시트 연동**: 메일 발송 시 보고일자 자동 기록
- 🗑️ **자동 정리**: 메일 발송 후 체크된 항목 자동 삭제
- 📖 사용자 매뉴얼 업데이트

#### v1.1 (2026-01-17)
- 📧 메일 발송 시 원본 메일의 받는 사람도 CC에 자동 추가
- ⚡ ReadyKorea 자동 입력 속도 약 50% 향상
- 📖 사용자 매뉴얼 전면 개편

#### v1.0 (2026-01-02)
- 🎉 최초 릴리즈
- 파일 자동 이름 변경 기능
- 파일 매니저 (MK1)
- 수출 메일 자동화 (VERONICA)
- 일정 관리 (MK3)

---

**문의**: 해도관세사무소 최명헌
"""
        
        browser.setMarkdown(manual_content)
        layout.addWidget(browser)
        
        # 닫기 버튼
        btn_close = NeonButton("닫기")
        btn_close.setFixedHeight(40)
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)
        
        dlg.exec()

