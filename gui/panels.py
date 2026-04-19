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
from .utils import resource_path, get_run_dir
from .styles import TARGET_LIST_STYLESHEET
from .claude_theme import C as CT
from core.config import get_config_path
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
    settings_changed = pyqtSignal()  # 설정 변경 즉시 저장 요청
    startup_guide_requested = pyqtSignal()  # 시작 가이드 재표시 요청
    _mail_search_done = pyqtSignal(str, str, str, object, str)  # company, bl_id, file_path, threads, my_email

    def __init__(self, parent=None, path_callback=None, archiver=None, license_tier="standard"):
        super().__init__(parent)
        self.license_tier = license_tier
        self.path_callback = path_callback
        self.archiver = archiver
        self.target_subfolders = []
        self.move_list_t1 = []
        self.browser_home_path = ""  # 홈 폴더 경로
        # 디렉토리 인덱스 (백그라운드 사전 구축)
        self._dir_index = {}       # root -> company_map
        self._dir_index_ready = {}  # root -> bool
        self._dir_index_lock = threading.Lock()
        
        # Signal 연결: 백그라운드 쓰레드에서 emit되면 메인 쓰레드에서 슬롯 실행
        self.refresh_after_move_signal.connect(self._on_move_complete)
        self.search_result_signal.connect(self._display_search_results)
        self.quick_export_complete_signal.connect(self._on_quick_export_complete)
        self._mail_search_done.connect(self._show_mail_thread_dialog)

        self.init_ui()
        QTimer.singleShot(0, self.refresh_targets)
        self.load_config()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.tabs = QTabWidget()
        
        # TAB 1: Internal (Claude Design warm dark section cards)
        tab1 = QWidget()
        tab1.setStyleSheet("background-color: transparent;")
        t1_layout = QHBoxLayout(tab1)
        t1_layout.setContentsMargins(0, 0, 0, 0)
        t1_layout.setSpacing(5)

        # === 좌측 영역: 섹션 카드 2개 + 하단 버튼 ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(14)

        _CARD_CSS = f"""
            QFrame#SectionCard {{
                background-color: {CT['bg_2']};
                border: 1px solid {CT['border_soft']};
                border-radius: 12px;
            }}
        """
        _NUM_CSS = f"""
            QLabel#SectionNum {{
                color: {CT['fg_1']};
                background-color: {CT['bg_3']};
                border-radius: 9px;
                font-family: 'JetBrains Mono','Consolas',monospace;
                font-size: 8.5pt;
                font-weight: 600;
            }}
        """
        _SECTION_TITLE_CSS = (
            f"color: {CT['fg_2']}; font-size: 9pt; font-weight: 700; "
            f"letter-spacing: 1.5px; background: transparent; border: none;"
        )
        _SECTION_COUNT_CSS = (
            f"color: {CT['fg_3']}; font-family: 'JetBrains Mono','Consolas',monospace; "
            f"font-size: 9pt; background: transparent; border: none;"
        )

        # ============================================================
        # 1) TARGET FOLDERS 섹션 카드
        # ============================================================
        card1 = QFrame()
        card1.setObjectName("SectionCard")
        card1.setStyleSheet(_CARD_CSS + _NUM_CSS)
        card1_layout = QVBoxLayout(card1)
        card1_layout.setContentsMargins(14, 12, 14, 12)
        card1_layout.setSpacing(10)

        c1_header = QHBoxLayout()
        c1_header.setSpacing(8)

        _num1 = QLabel("1")
        _num1.setObjectName("SectionNum")
        _num1.setFixedSize(18, 18)
        _num1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c1_header.addWidget(_num1)

        self.lbl_target_title = QLabel("TARGET FOLDERS")
        self.lbl_target_title.setStyleSheet(_SECTION_TITLE_CSS)
        c1_header.addWidget(self.lbl_target_title)
        c1_header.addStretch()

        self.lbl_target_count = QLabel("0 개")
        self.lbl_target_count.setStyleSheet(_SECTION_COUNT_CSS)
        c1_header.addWidget(self.lbl_target_count)

        from .claude_icons import pixmap as _icpx
        from PyQt6.QtCore import QSize as _QSize
        from PyQt6.QtGui import QIcon as _QIcon
        self.btn_refresh_target = QPushButton()
        self.btn_refresh_target.setIcon(_QIcon(_icpx("Refresh", size=13, color=CT['fg_2'])))
        self.btn_refresh_target.setIconSize(_QSize(13, 13))
        self.btn_refresh_target.setFixedSize(26, 22)
        self.btn_refresh_target.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_target.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {CT['bg_3']};
            }}
        """)
        self.btn_refresh_target.clicked.connect(self.refresh_targets)
        c1_header.addWidget(self.btn_refresh_target)
        card1_layout.addLayout(c1_header)

        self.list_target = TargetListWidget()
        self.list_target.delete_requested.connect(self._delete_target_folder)
        self.list_target.rename_requested.connect(self._rename_target_folder)
        self.list_target.setMaximumHeight(150)
        self.list_target.setStyleSheet(TARGET_LIST_STYLESHEET)
        self.list_target.itemClicked.connect(self._on_target_folder_clicked)
        self.list_target.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_target.customContextMenuRequested.connect(self._show_target_folder_context_menu)
        card1_layout.addWidget(self.list_target)

        left_layout.addWidget(card1)

        # ============================================================
        # 2) ADD FOLDERS 섹션 카드 (드롭존)
        # ============================================================
        card2 = QFrame()
        card2.setObjectName("SectionCard")
        card2.setStyleSheet(_CARD_CSS + _NUM_CSS)
        card2_layout = QVBoxLayout(card2)
        card2_layout.setContentsMargins(14, 12, 14, 12)
        card2_layout.setSpacing(10)

        c2_header = QHBoxLayout()
        c2_header.setSpacing(8)

        _num2 = QLabel("2")
        _num2.setObjectName("SectionNum")
        _num2.setFixedSize(18, 18)
        _num2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c2_header.addWidget(_num2)

        _lbl_add = QLabel("ADD FOLDERS")
        _lbl_add.setStyleSheet(_SECTION_TITLE_CSS)
        c2_header.addWidget(_lbl_add)
        c2_header.addStretch()

        _lbl_dnd = QLabel("drag & drop")
        _lbl_dnd.setStyleSheet(_SECTION_COUNT_CSS)
        c2_header.addWidget(_lbl_dnd)
        card2_layout.addLayout(c2_header)

        self.list_widget = DropListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget._restore_style()
        self.list_widget.items_dropped.connect(self._on_items_dropped)
        self.list_widget.refresh_needed.connect(lambda: self._load_folder_contents(self.list_widget.current_folder) if self.list_widget.current_folder else None)
        self.list_widget.mail_send_requested.connect(self._on_mail_send_requested)
        self.list_widget.mail_preconnect_requested.connect(self._preconnect_imap)

        # 드롭존 빈 상태 오버레이 (warm dark)
        self.drop_overlay = QWidget(self.list_widget.viewport())
        self.drop_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.drop_overlay.setStyleSheet("background: transparent;")
        ov_layout = QVBoxLayout(self.drop_overlay)
        ov_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ov_layout.setSpacing(10)

        from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor

        def _make_tray_down_icon(size=40, color_rgba=(149, 152, 162, 220), stroke=2):
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(*color_rgba))
            pen.setWidth(stroke)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)

            tray_x, tray_y, tray_w, tray_h = 6, 12, size - 12, size - 18
            p.drawRoundedRect(tray_x, tray_y, tray_w, tray_h, 7, 7)
            cx = size // 2
            arrow_top = tray_y + 6
            arrow_bottom = tray_y + tray_h - 8
            p.drawLine(cx, arrow_top, cx, arrow_bottom)
            head = 5
            p.drawLine(cx - head, arrow_bottom - head, cx, arrow_bottom)
            p.drawLine(cx + head, arrow_bottom - head, cx, arrow_bottom)

            p.end()
            return pm

        _icon_wrap = QLabel()
        _icon_wrap.setFixedSize(56, 56)
        _icon_wrap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _icon_wrap.setStyleSheet(f"""
            background-color: {CT['bg_3']};
            border-radius: 12px;
            border: none;
        """)
        _icon_wrap.setPixmap(_make_tray_down_icon(size=36, color_rgba=(149, 152, 162, 220), stroke=2))
        ov_layout.addWidget(_icon_wrap)

        _lbl_empty = QLabel("폴더를 여기로 드래그하세요")
        _lbl_empty.setStyleSheet(f"color: {CT['fg_3']}; font-size: 9.5pt; background: transparent; border: none;")
        _lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ov_layout.addWidget(_lbl_empty)

        orig_resize = self.list_widget.resizeEvent
        def _on_list_resize(ev):
            orig_resize(ev)
            vp = self.list_widget.viewport()
            self.drop_overlay.setGeometry(0, 0, vp.width(), vp.height())
        self.list_widget.resizeEvent = _on_list_resize

        def _update_overlay_visibility():
            self.drop_overlay.setVisible(self.list_widget.count() == 0)
        self.list_widget.model().rowsInserted.connect(lambda *_: _update_overlay_visibility())
        self.list_widget.model().rowsRemoved.connect(lambda *_: _update_overlay_visibility())
        self.list_widget.model().modelReset.connect(_update_overlay_visibility)
        QTimer.singleShot(0, _update_overlay_visibility)

        card2_layout.addWidget(self.list_widget, stretch=1)
        left_layout.addWidget(card2, stretch=1)

        # ============================================================
        # 3) 하단 버튼 바 (수입 / 수출 / 검색) — min-btn 스타일
        # ============================================================
        btn_wrap = QFrame()
        btn_wrap.setStyleSheet(f"""
            QFrame {{
                background-color: transparent;
                border: none;
                border-top: 1px solid {CT['border_soft']};
            }}
        """)
        btn_layout = QHBoxLayout(btn_wrap)
        btn_layout.setContentsMargins(0, 8, 0, 0)
        btn_layout.setSpacing(2)

        _min_btn_css = f"""
            QPushButton {{
                background-color: transparent;
                color: {CT['fg_1']};
                border: none;
                border-radius: 7px;
                padding: 7px 12px;
                font-size: 10pt;
                font-weight: 500;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: {CT['bg_2']};
                color: {CT['accent_hi']};
            }}
            QPushButton:pressed {{
                background-color: {CT['bg_3']};
            }}
        """

        self.btn_to_import = QPushButton("  수입")
        self.btn_to_import.setIcon(_QIcon(_icpx("Download", size=14, color=CT['fg_2'])))
        self.btn_to_import.setIconSize(_QSize(14, 14))
        self.btn_to_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_to_import.setStyleSheet(_min_btn_css)
        self.btn_to_import.clicked.connect(lambda: self._quick_export_to('import'))
        btn_layout.addWidget(self.btn_to_import, stretch=1)

        _sep1 = QFrame()
        _sep1.setFixedWidth(1)
        _sep1.setStyleSheet(f"background-color: {CT['border']}; border: none;")
        btn_layout.addWidget(_sep1)

        self.btn_to_export = QPushButton("  수출")
        self.btn_to_export.setIcon(_QIcon(_icpx("Upload", size=14, color=CT['fg_2'])))
        self.btn_to_export.setIconSize(_QSize(14, 14))
        self.btn_to_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_to_export.setStyleSheet(_min_btn_css)
        self.btn_to_export.clicked.connect(lambda: self._quick_export_to('export'))
        btn_layout.addWidget(self.btn_to_export, stretch=1)

        _sep2 = QFrame()
        _sep2.setFixedWidth(1)
        _sep2.setStyleSheet(f"background-color: {CT['border']}; border: none;")
        btn_layout.addWidget(_sep2)

        self.btn_toggle_search = QPushButton("  검색")
        self.btn_toggle_search.setIcon(_QIcon(_icpx("Search", size=14, color=CT['fg_2'])))
        self.btn_toggle_search.setIconSize(_QSize(14, 14))
        self.btn_toggle_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_search.setStyleSheet(_min_btn_css)
        self.btn_toggle_search.clicked.connect(self._toggle_search_panel)
        btn_layout.addWidget(self.btn_toggle_search, stretch=1)

        left_layout.addWidget(btn_wrap)
        

        
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
        self.lbl_search_text = QLabel("검색")
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
        self.btn_search = NeonButton("검색", color="cyan")
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
        self.lbl_browser_text = QLabel("폴더 탐색")
        self.lbl_browser_text.setStyleSheet("color: #00ffff; font-weight: bold; font-size: 9pt;")
        self.browser_header_layout.addWidget(self.lbl_browser_text)
        self.btn_go_up = NeonButton("⬆", color="cyan")
        self.btn_go_up.setFixedSize(36, 32)
        self.btn_go_up.setStyleSheet(self.btn_go_up.styleSheet() + "font-size: 14pt;")
        self.btn_go_up.clicked.connect(self._browser_go_up)
        self.browser_header_layout.addWidget(self.btn_go_up)
        self.btn_go_home = NeonButton("🏠", color="cyan")
        self.btn_go_home.setFixedSize(36, 32)
        self.btn_go_home.setStyleSheet(self.btn_go_home.styleSheet() + "font-size: 14pt;")
        self.btn_go_home.clicked.connect(self._browser_go_home)
        self.browser_header_layout.addWidget(self.btn_go_home)
        self.btn_set_home = NeonButton("⚙", color="cyan")
        self.btn_set_home.setFixedSize(36, 32)
        self.btn_set_home.setStyleSheet(self.btn_set_home.styleSheet() + "font-size: 14pt;")
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
        self.tabs.addTab(tab1, "정산")
        
        # TAB 2: 일정 (일정관리) - 메모 위젯용 placeholder
        mk3_tab = QWidget()
        mk3_tab.setStyleSheet("background-color: transparent;")
        self.mk3_memo_layout = QVBoxLayout(mk3_tab)
        self.mk3_memo_layout.setContentsMargins(0, 0, 0, 0)
        self.mk3_tab_widget = mk3_tab

        # 일정/통관/REPORT 탭은 항상 생성 (navbar에서 접근 제어)
        self.tabs.addTab(mk3_tab, "일정")

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
        self.tabs.addTab(tab_veronica, "통관")

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
        
        self.btn_set_imp = NeonButton("수입 서버 경로 설정")
        self.btn_set_imp.clicked.connect(lambda: self.set_root('import'))
        self.lbl_imp_root = QLabel("Not Set")
        self.lbl_imp_root.setStyleSheet("color: #555; font-size: 8pt;")
        t4_layout.addWidget(self.btn_set_imp)
        t4_layout.addWidget(self.lbl_imp_root)
        
        self.btn_set_exp = NeonButton("수출 서버 경로 설정")
        self.btn_set_exp.clicked.connect(lambda: self.set_root('export'))
        self.lbl_exp_root = QLabel("Not Set")
        self.lbl_exp_root.setStyleSheet("color: #555; font-size: 8pt;")
        t4_layout.addWidget(self.btn_set_exp)
        t4_layout.addWidget(self.lbl_exp_root)
        
        self.btn_set_exp_docs = NeonButton("선적서류 경로 설정")
        self.btn_set_exp_docs.clicked.connect(lambda: self.set_root('export_docs'))
        self.lbl_exp_docs_root = QLabel("Not Set")
        self.lbl_exp_docs_root.setStyleSheet("color: #555; font-size: 8pt;")
        t4_layout.addWidget(self.btn_set_exp_docs)
        t4_layout.addWidget(self.lbl_exp_docs_root)
        
        # === 매뉴얼 섹션 ===
        t4_layout.addSpacing(10)
        manual_row = QHBoxLayout()
        self.btn_show_manual = NeonButton("📘 사용자 매뉴얼", color="cyan")
        self.btn_show_manual.setFixedHeight(40)
        self.btn_show_manual.clicked.connect(self._show_manual_dialog)
        manual_row.addWidget(self.btn_show_manual)
        self.btn_show_guide = NeonButton("📖 시작 가이드", color="cyan")
        self.btn_show_guide.setFixedHeight(40)
        self.btn_show_guide.clicked.connect(self._request_startup_guide)
        manual_row.addWidget(self.btn_show_guide)
        t4_layout.addLayout(manual_row)

        # === 커스텀 네이밍 설정 (다이얼로그 방식) ===
        t4_layout.addSpacing(10)
        btn_naming_settings = NeonButton("파일 이름 설정", color="cyan")
        btn_naming_settings.setFixedHeight(40)
        btn_naming_settings.clicked.connect(self._show_naming_dialog)
        t4_layout.addWidget(btn_naming_settings)

        # === 한비로 메일 설정 섹션 ===
        t4_layout.addSpacing(20)
        lbl_mail_header = QLabel("한비로 메일 설정")
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
        self.btn_save_mail = NeonButton("저장", color="cyan")
        self.btn_save_mail.clicked.connect(self._save_hanbiro_settings)
        mail_btn_row.addWidget(self.btn_save_mail)
        
        self.btn_test_mail = NeonButton("연결 테스트", color="cyan")
        self.btn_test_mail.clicked.connect(self._test_hanbiro_connection)
        mail_btn_row.addWidget(self.btn_test_mail)
        t4_layout.addLayout(mail_btn_row)
        
        # 연결 상태 표시
        self.lbl_mail_status = QLabel("Status: Not configured")
        self.lbl_mail_status.setStyleSheet("color: #888; font-size: 8pt;")
        t4_layout.addWidget(self.lbl_mail_status)
        
        # === 관리자 잠금 해제 섹션 ===
        t4_layout.addSpacing(20)
        lbl_admin_header = QLabel("관리자 잠금 해제")
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

        self.btn_admin_unlock = NeonButton("해제", color="magenta")
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
        except (AttributeError, TypeError): pass
             
        if x < 10: x = 10
        return QRect(x, y, 480, h)

    def reposition_search_panel(self):
        """외부(Main Window) 리사이즈 시 위치 갱신용"""
        if self.search_panel.isVisible():
            geo = self._calculate_target_geometry()
            self.search_panel.setGeometry(geo)

    def _animate_search_panel(self, show):
        anim_targets = [
            (self.lbl_search_text, 200, 'typing', "검색"),
            (self.lbl_search_icon, 700, 'fade', None),
            (self.lbl_browser_text, 1000, 'typing', "폴더 탐색"),
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
                if hasattr(self, 'lbl_target_count'):
                    self.lbl_target_count.setText(f"{len(self.target_subfolders)} 개")
            else:
                self.list_target.addItem(QListWidgetItem("No Folders"))
                if hasattr(self, 'lbl_target_count'):
                    self.lbl_target_count.setText("0 개")
                # 폴더가 없으면 FILES TO MOVE도 초기화
                self.list_widget.clear()
                self.current_target_folder = None

        except RuntimeError: return
        except Exception as e:
            print(f"Error in refresh_targets: {e}")
            if hasattr(self, 'target_subfolders') and hasattr(self, 'lbl_target_count'):
                self.lbl_target_count.setText(f"{len(self.target_subfolders)} 개")
            elif hasattr(self, 'lbl_target_count'):
                self.lbl_target_count.setText("0 개")

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
                except UnicodeDecodeError: output = result.stdout.decode('utf-8', errors='replace')
                try: stderr = result.stderr.decode('cp949')
                except UnicodeDecodeError: stderr = result.stderr.decode('utf-8', errors='replace')
                
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
            self.settings_changed.emit()
            self.emit_log(f"[탐색기] 홈 폴더 설정: {current_path}")
            JarvisMessageBox.information(self, "홈 폴더 설정", f"홈 폴더가 설정되었습니다:\n{current_path}")
        else:
            JarvisMessageBox.warning(self, "오류", "현재 폴더를 확인할 수 없습니다.")

    def load_config(self):
        try:
            cfg_path = get_config_path()
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
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
                        user_id = email.replace('@raeon.co.kr', '') if email else ''
                        self.input_hanbiro_email.setText(user_id)
                        # 비밀번호는 keyring에서 로드
                        import keyring
                        saved_pw = keyring.get_password("TRADIS_MH", "email_password") or ''
                        self.input_hanbiro_password.setText(saved_pw)
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

        # 인덱스에서 캐시 조회 (미준비 시 타겟 스캔 폴백)
        needed_companies = set()
        for _, folder_name in valid_folders:
            needed_companies.add(folder_name.split('_')[0].replace("★", "").strip().upper())
        dir_cache = self._get_dir_cache(root, needed_companies)

        # 유사 매칭을 위한 전체 폴더명 캐시 (1depth만, 빠름)
        full_cache = None
        def _get_full_cache():
            nonlocal full_cache
            if full_cache is None:
                full_cache = self._build_full_cache(root)
            return full_cache

        # 중복/유사 사전 검사
        new_folders = []
        dup_folders = []        # (src_path, folder_name, existing_full_path)
        similar_folders = []    # (src_path, folder_name, similar_company_path, similar_company_name)
        for src_path, folder_name in valid_folders:
            parts = folder_name.split('_')
            comp = parts[0]
            fid = "_".join(parts[1:])
            existing_rel, is_similar = self._find_id_in_company_dir(root, comp, fid, _cache=dir_cache)
            if existing_rel is None:
                # 정확/유사 매칭 모두 실패 → 전체 캐시에서 유사 검색
                existing_rel, is_similar = self._find_id_in_company_dir(root, comp, fid, _cache=_get_full_cache())
            if existing_rel:
                existing_full = os.path.join(root, existing_rel)
                if is_similar:
                    # 유사 회사 폴더에 같은 BL 존재 → 사용자 확인 필요
                    similar_company_name = os.path.basename(os.path.dirname(existing_full))
                    similar_folders.append((src_path, folder_name, existing_full, similar_company_name))
                else:
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

        # 유사 회사 폴더가 감지되면 사용자에게 확인 (같은 BL이 유사 폴더에 존재)
        similar_approved = []   # 승인된 유사 매칭 (기존 폴더로 병합)
        similar_new = []        # 거부된 유사 매칭 (새 폴더 생성)
        if similar_folders:
            already_decided = {}  # 같은 회사명 조합 중복 팝업 방지
            for src_path, folder_name, existing_full, similar_name in similar_folders:
                comp = folder_name.split('_')[0]
                decision_key = f"{comp}|{similar_name}"
                if decision_key in already_decided:
                    result = already_decided[decision_key]
                else:
                    result = self._show_similar_company_dialog(comp, similar_name)
                    already_decided[decision_key] = result
                if result == "existing":
                    similar_approved.append((src_path, folder_name, existing_full))
                elif result == "new":
                    similar_new.append((src_path, folder_name))
                # result == None (취소) → 이동하지 않음

        # new_folders의 회사 폴더 매칭 미리 결정 (메인 스레드에서 팝업 처리)
        new_folder_dst = {}  # folder_name → dst_parent
        new_folder_decided = {}  # 같은 회사명 중복 팝업 방지
        remaining_new = []
        for src_path, folder_name in new_folders:
            comp = folder_name.split('_')[0]
            fid = "_".join(folder_name.split('_')[1:])

            existing_company_folder, is_sim = self._find_company_folder(root, comp, _cache=dir_cache)
            if existing_company_folder is None:
                existing_company_folder, is_sim = self._find_company_folder(root, comp, _cache=_get_full_cache())

            if existing_company_folder and not is_sim:
                new_folder_dst[folder_name] = existing_company_folder
                remaining_new.append((src_path, folder_name))
            elif existing_company_folder and is_sim:
                similar_name = os.path.basename(existing_company_folder)
                decision_key = f"{comp}|{similar_name}"
                if decision_key in new_folder_decided:
                    result = new_folder_decided[decision_key]
                else:
                    result = self._show_similar_company_dialog(comp, similar_name)
                    new_folder_decided[decision_key] = result
                if result == "existing":
                    new_folder_dst[folder_name] = existing_company_folder
                    remaining_new.append((src_path, folder_name))
                elif result == "new":
                    remaining_new.append((src_path, folder_name))
                # result == None → 이동하지 않음
            else:
                remaining_new.append((src_path, folder_name))
        new_folders = remaining_new

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

                # dst_parent는 이동 전 단계에서 미리 결정됨 (new_folders_with_dst)
                dst_parent = new_folder_dst.get(folder_name)
                if not dst_parent:
                    dst_parent = os.path.join(root, comp)
                    os.makedirs(dst_parent, exist_ok=True)

                dst = os.path.join(dst_parent, fid)
                try:
                    shutil.move(src_path, dst)
                    count += 1
                    moved_dst_paths.append(dst)
                    self._update_index_after_move(root, comp.replace("★", "").strip().upper(), fid, dst_parent)
                    self.emit_log(f" -> [이동 성공] {folder_name} -> {os.path.basename(dst_parent)}/{fid}")
                except Exception as e: self.emit_log(f" -> [이동 실패] {folder_name}: {e}")

            # 유사 회사 승인 폴더 이동 (기존 폴더에 병합)
            for src_path, folder_name, existing_full in similar_approved:
                parts = folder_name.split('_')
                comp = parts[0]
                fid = "_".join(parts[1:])
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
                                shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                            else:
                                shutil.copytree(src_item, dst_item)
                            merged += 1
                    shutil.rmtree(src_path)
                    count += 1
                    moved_dst_paths.append(existing_full)
                    self.emit_log(f" -> [유사 병합] {folder_name} -> {os.path.basename(os.path.dirname(existing_full))}/{fid} ({merged}개 파일)")
                except Exception as e:
                    self.emit_log(f" -> [유사 병합 실패] {folder_name}: {e}")

            # 유사 회사 거부 폴더 이동 (새 폴더 생성)
            for src_path, folder_name in similar_new:
                parts = folder_name.split('_')
                comp = parts[0]
                fid = "_".join(parts[1:])
                dst_parent = os.path.join(root, comp)
                os.makedirs(dst_parent, exist_ok=True)
                dst = os.path.join(dst_parent, fid)
                try:
                    shutil.move(src_path, dst)
                    count += 1
                    moved_dst_paths.append(dst)
                    self._update_index_after_move(root, comp.replace("★", "").strip().upper(), fid, dst_parent)
                    self.emit_log(f" -> [새 폴더] {folder_name} -> {comp}/{fid}")
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

    def _show_similar_company_dialog(self, current_name, similar_name):
        """유사 회사 폴더 감지 시 사용자 확인 다이얼로그

        Returns:
            "existing": 기존 폴더에 이동, "new": 새 폴더 생성, None: 취소
        """
        msg = (f"'{current_name}'과 유사한 폴더가 있습니다.\n\n"
               f"  기존 폴더: {similar_name}\n\n"
               f"기존 폴더에 이동할까요?")

        dlg = JarvisMessageBox(self, "유사 폴더 감지", msg, JarvisMessageBox.Question)
        dlg.add_button("취소", "reject", "gray")
        dlg.add_button("새 폴더", "new", "gray")
        dlg.add_button("기존 폴더", "existing", "cyan")
        dlg.exec()

        if dlg.result_value == "existing":
            return "existing"
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



    # ── 디렉토리 인덱스 (Everything 방식: 사전 구축 + 디스크 캐시) ──

    def _get_index_path(self, root):
        """인덱스 저장 경로"""
        import hashlib
        key = hashlib.md5(root.encode('utf-8')).hexdigest()[:12]
        return os.path.join(os.path.dirname(get_config_path()), f"dir_index_{key}.json")

    def start_background_indexing(self, root):
        """백그라운드에서 디렉토리 인덱스 구축 (프로그램 시작 시 호출)"""
        if not root or not os.path.isdir(root):
            return
        # 1) 디스크 캐시가 있으면 즉시 로드
        idx_path = self._get_index_path(root)
        if os.path.exists(idx_path):
            try:
                with open(idx_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                # JSON은 set 미지원 → list로 저장/set으로 복원
                company_map = {k: (v[0], set(v[1])) for k, v in saved.items()}
                with self._dir_index_lock:
                    self._dir_index[root] = company_map
                    self._dir_index_ready[root] = True
            except Exception:
                pass
        # 2) 백그라운드에서 최신 인덱스 갱신
        threading.Thread(target=self._rebuild_index, args=(root,), daemon=True).start()

    def _rebuild_index(self, root):
        """전체 디렉토리 스캔 후 인덱스 저장"""
        company_map = {}
        try:
            root_items = []
            with os.scandir(root) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False): continue
                    root_items.append((entry.name, entry.path))
                    clean = entry.name.replace("★", "").strip().upper()
                    try:
                        children = {e.name for e in os.scandir(entry.path)}
                    except (PermissionError, OSError):
                        children = set()
                    if clean not in company_map:
                        company_map[clean] = (entry.path, children)
            for folder, folder_path in root_items:
                try:
                    with os.scandir(folder_path) as sub_entries:
                        for sub_entry in sub_entries:
                            if not sub_entry.is_dir(follow_symlinks=False): continue
                            clean_sub = sub_entry.name.replace("★", "").strip().upper()
                            if clean_sub not in company_map:
                                try:
                                    sub_children = {e.name for e in os.scandir(sub_entry.path)}
                                except (PermissionError, OSError):
                                    sub_children = set()
                                company_map[clean_sub] = (sub_entry.path, sub_children)
                except (PermissionError, OSError):
                    continue
        except (OSError, AttributeError):
            pass
        # 메모리 인덱스 업데이트
        with self._dir_index_lock:
            self._dir_index[root] = company_map
            self._dir_index_ready[root] = True
        # 디스크에 저장 (다음 실행 시 즉시 로드)
        try:
            idx_path = self._get_index_path(root)
            os.makedirs(os.path.dirname(idx_path), exist_ok=True)
            serializable = {k: (v[0], list(v[1])) for k, v in company_map.items()}
            with open(idx_path, 'w', encoding='utf-8') as f:
                json.dump(serializable, f, ensure_ascii=False)
        except Exception:
            pass

    def _get_dir_cache(self, root, needed_companies=None):
        """인덱스에서 캐시 반환. 인덱스 미준비 시 타겟 스캔 폴백."""
        with self._dir_index_lock:
            if self._dir_index_ready.get(root):
                return self._dir_index[root]
        # 폴백: 필요한 회사만 타겟 스캔
        if needed_companies:
            return self._build_targeted_cache(root, needed_companies)
        return self._build_full_cache(root)

    def _build_targeted_cache(self, root, needed_companies):
        """필요한 회사만 타겟 스캔 (인덱스 미준비 시 폴백). needed_companies=None이면 전체 스캔."""
        company_map = {}
        scan_all = needed_companies is None
        remaining = set() if scan_all else set(needed_companies)
        try:
            root_items = []
            with os.scandir(root) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False): continue
                    clean = entry.name.replace("★", "").strip().upper()
                    root_items.append((clean, entry.path))
                    if scan_all or clean in remaining:
                        try:
                            children = {e.name for e in os.scandir(entry.path)}
                        except (PermissionError, OSError):
                            children = set()
                        company_map[clean] = (entry.path, children)
                        remaining.discard(clean)
            if scan_all or remaining:
                for _, folder_path in root_items:
                    if not scan_all and not remaining: break
                    try:
                        with os.scandir(folder_path) as sub_entries:
                            for sub_entry in sub_entries:
                                if not scan_all and not remaining: break
                                if not sub_entry.is_dir(follow_symlinks=False): continue
                                clean_sub = sub_entry.name.replace("★", "").strip().upper()
                                if scan_all or clean_sub in remaining:
                                    try:
                                        sub_children = {e.name for e in os.scandir(sub_entry.path)}
                                    except (PermissionError, OSError):
                                        sub_children = set()
                                    company_map[clean_sub] = (sub_entry.path, sub_children)
                                    remaining.discard(clean_sub)
                    except (PermissionError, OSError):
                        continue
        except (OSError, AttributeError):
            pass
        return company_map

    def _build_full_cache(self, root):
        """전체 스캔 (폴백용) — 경량: 폴더명만 수집, children은 필요 시 지연 로드"""
        company_map = {}
        try:
            # 1depth: 회사 폴더
            with os.scandir(root) as entries:
                for entry in entries:
                    if not entry.is_dir(follow_symlinks=False): continue
                    clean = entry.name.replace("★", "").strip().upper()
                    company_map[clean] = (entry.path, None)  # children은 None (지연 로드)
            # 2depth: 하위 회사 폴더
            for clean_key, (folder_path, _) in list(company_map.items()):
                try:
                    with os.scandir(folder_path) as sub_entries:
                        for sub_entry in sub_entries:
                            if not sub_entry.is_dir(follow_symlinks=False): continue
                            clean_sub = sub_entry.name.replace("★", "").strip().upper()
                            if clean_sub not in company_map:
                                company_map[clean_sub] = (sub_entry.path, None)
                except (PermissionError, OSError):
                    continue
        except (OSError, AttributeError):
            pass
        return company_map

    def _update_index_after_move(self, root, company_clean, fid, dst_parent):
        """이동 후 인덱스 부분 업데이트 (전체 재스캔 불필요)"""
        with self._dir_index_lock:
            if root not in self._dir_index:
                return
            idx = self._dir_index[root]
            if company_clean in idx:
                folder_path, children = idx[company_clean]
                children.add(fid)
            else:
                idx[company_clean] = (dst_parent, {fid})

    # ─── 선적서류 자동 검색 ───

    @staticmethod
    def _bl_match_in_text(bl_upper, text):
        """텍스트에서 BL번호 매칭 (정확 매칭 + 괄호 내 유사 매칭)"""
        import re
        from core.utils import is_similar_id
        text_upper = text.upper()
        # 1차: 정확 포함 매칭
        if bl_upper in text_upper:
            return True
        # 2차: 괄호 안의 ID를 추출하여 유사 매칭
        paren_ids = re.findall(r'\(([A-Za-z0-9]+)\)', text)
        for pid in paren_ids:
            if is_similar_id(bl_upper, pid.upper()):
                return True
        return False

    def scan_shipping_docs_for_bl(self, bl_number):
        """선적서류폴더에서 BL번호가 포함된 폴더/파일 검색 (실시간 스캔)

        Returns: [(이동대상폴더경로, 매칭유형'folder'|'file')] 또는 빈 리스트
        """
        shipping_root = getattr(self.archiver, 'export_docs_root', '')
        if not shipping_root or not os.path.exists(shipping_root):
            return []

        # 정규화된 shipping_root (자기 자신 매칭 방지용)
        shipping_root_norm = os.path.normpath(shipping_root)

        # 감시폴더(target directory)를 스캔에서 제외
        exclude_path = self.path_callback() if self.path_callback else ""
        if exclude_path:
            exclude_path = os.path.normpath(exclude_path)

        bl_upper = bl_number.upper()
        results = []
        seen_folders = set()
        max_depth = 4  # depth 3까지 포함 (0-indexed)

        for root_dir, dirs, files in os.walk(shipping_root):
            root_norm = os.path.normpath(root_dir)

            # 감시폴더 및 하위 폴더 제외
            if exclude_path and root_norm.lower().startswith(exclude_path.lower()):
                dirs.clear()
                continue

            depth = root_dir.replace(shipping_root, '').count(os.sep)
            if depth >= max_depth:
                dirs.clear()
                continue

            # [안전장치] shipping_root 자체는 절대 이동 대상이 될 수 없음
            # (root에 있는 파일이 BL과 매칭되어도 root 자체를 이동하면 안 됨)
            if root_norm.lower() == shipping_root_norm.lower():
                continue

            # 폴더명에 BL 포함 (정확 매칭 + 유사 매칭)
            folder_name = os.path.basename(root_dir)
            if root_dir not in seen_folders and self._bl_match_in_text(bl_upper, folder_name):
                results.append((root_dir, 'folder'))
                seen_folders.add(root_dir)
                continue

            # 파일명에 BL 포함 → 부모 폴더를 이동 대상으로
            for f in files:
                if root_dir not in seen_folders and self._bl_match_in_text(bl_upper, f):
                    results.append((root_dir, 'file'))
                    seen_folders.add(root_dir)
                    break

        results = [(p, t) for p, t in results if os.path.exists(p)]
        return results

    def _show_shipping_docs_dialog(self, bl_number, matches, target_folder):
        """선적서류 발견 팝업 (JarvisMessageBox Frosted Glass 스타일)

        Returns:
            (action, selected_matches) — action: "folder"|"extract"|None, selected: 선택된 매칭 리스트
        """
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QCheckBox,
                                     QLabel, QWidget, QGraphicsDropShadowEffect)
        from PyQt6.QtGui import QFont

        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setMinimumWidth(480)

        # Frosted Glass 컨테이너
        container = QWidget(dlg)
        container.setObjectName("shipping_dlg")
        container.setStyleSheet("""
            #shipping_dlg {
                background-color: rgba(45, 50, 60, 230);
                border: 1px solid rgba(100, 110, 120, 0.5);
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
        layout.setContentsMargins(24, 28, 24, 20)
        layout.setSpacing(12)

        # 타이틀
        title = QLabel("선적서류 발견")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; background: transparent;")
        layout.addWidget(title)

        subtitle = QLabel(f"{bl_number} 관련 ({len(matches)}건)")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.7); background: transparent;")
        layout.addWidget(subtitle)

        layout.addSpacing(6)

        # 체크박스 목록
        checkboxes = []
        for path, match_type in matches:
            folder_name = os.path.basename(path)
            cb = QCheckBox(f"  {folder_name}")
            cb.setChecked(True)
            cb.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            cb.setStyleSheet("QCheckBox { color: #ffffff; background: transparent; spacing: 8px; }"
                             "QCheckBox::indicator { width: 16px; height: 16px; }")
            layout.addWidget(cb)

            path_label = QLabel(f"     {path}")
            path_label.setFont(QFont("Segoe UI", 8))
            path_label.setStyleSheet("color: rgba(255, 255, 255, 0.4); background: transparent;")
            path_label.setWordWrap(True)
            layout.addWidget(path_label)

            checkboxes.append((cb, path, match_type))

        layout.addSpacing(10)

        # 버튼
        result = {"action": None}
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        def make_btn(text, value, is_primary=False):
            from PyQt6.QtWidgets import QPushButton
            btn = QPushButton(text)
            btn.setFixedHeight(42)
            btn.setMinimumWidth(100)
            btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if is_primary:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(30, 35, 45, 200);
                        border: 2px solid #00d4ff; border-radius: 12px;
                        color: #00d4ff; padding: 8px 20px;
                    }
                    QPushButton:hover { background-color: rgba(0, 212, 255, 40); border-color: #00ffff; color: #00ffff; }
                    QPushButton:pressed { background-color: rgba(0, 212, 255, 80); }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(100, 105, 115, 180);
                        border: 1px solid rgba(150, 155, 165, 0.5); border-radius: 12px;
                        color: #ffffff; padding: 8px 20px;
                    }
                    QPushButton:hover { background-color: rgba(120, 125, 135, 200); }
                    QPushButton:pressed { background-color: rgba(80, 85, 95, 200); }
                """)
            btn.clicked.connect(lambda: (result.update({"action": value}), dlg.accept()) if value else dlg.reject())
            return btn

        btn_row.addWidget(make_btn("취소", None))
        btn_row.addWidget(make_btn("파일만 꺼내기", "extract"))
        btn_row.addWidget(make_btn("폴더째로", "folder", is_primary=True))
        layout.addLayout(btn_row)

        dlg.exec()

        action = result["action"]
        if action:
            selected = [(p, t) for cb, p, t in checkboxes if cb.isChecked()]
            return action, selected
        return None, []

    def move_shipping_docs(self, matches, target_folder, mode="folder"):
        """선적서류를 감시폴더의 BL 폴더로 이동

        Returns: 실패한 항목 리스트 [(이름, 사유)]
        """
        # [안전장치] 선적서류 루트 자체는 이동 금지 (중요 루트 보호)
        shipping_root = getattr(self.archiver, 'export_docs_root', '')
        shipping_root_norm = os.path.normpath(shipping_root).lower() if shipping_root else ""
        target_norm = os.path.normpath(target_folder).lower()

        failed = []  # [(name, reason)]
        safe_matches = []
        for src_path, match_type in matches:
            src_norm = os.path.normpath(src_path).lower()
            if shipping_root_norm and src_norm == shipping_root_norm:
                self.emit_log(f" -> [선적서류 이동 차단] 루트 폴더 이동 시도 감지: {src_path}")
                failed.append((os.path.basename(src_path), "루트 폴더 이동 차단"))
                continue
            if src_norm == target_norm:
                self.emit_log(f" -> [선적서류 이동 차단] 대상 폴더와 동일: {src_path}")
                failed.append((os.path.basename(src_path), "대상 폴더와 동일"))
                continue
            # 대상 폴더의 상위로 이동 시도 방지
            if target_norm.startswith(src_norm + os.sep):
                self.emit_log(f" -> [선적서류 이동 차단] 대상의 상위 폴더 이동 시도: {src_path}")
                failed.append((os.path.basename(src_path), "대상 상위 폴더 이동 차단"))
                continue
            safe_matches.append((src_path, match_type))

        for src_path, match_type in safe_matches:
            try:
                if mode == "extract":
                    # 파일만 꺼내기 (기존 extract_files 로직 재사용)
                    for item in os.listdir(src_path):
                        item_path = os.path.join(src_path, item)
                        dest = os.path.join(target_folder, item)
                        if os.path.exists(dest):
                            dest = get_unique_filename(dest)
                        shutil.move(item_path, dest)
                    # 빈 폴더 삭제
                    try:
                        os.rmdir(src_path)
                        self.emit_log(f" -> [선적서류] 파일 꺼내기 완료 + 빈 폴더 삭제: {os.path.basename(src_path)}")
                    except OSError:
                        # 폴더가 비어있지 않으면 삭제하지 않음
                        self.emit_log(f" -> [선적서류] 파일 꺼내기 완료: {os.path.basename(src_path)} (하위 폴더 남음)")
                else:
                    # 폴더째로 이동
                    folder_name = os.path.basename(src_path)
                    dest = os.path.join(target_folder, folder_name)
                    if os.path.exists(dest):
                        dest = get_unique_filename(dest)
                    shutil.move(src_path, dest)
                    self.emit_log(f" -> [선적서류] 폴더 이동 완료: {folder_name}")
            except Exception as e:
                # 이동 실패 → 복사로 전환
                try:
                    if mode == "extract":
                        for item in os.listdir(src_path):
                            item_path = os.path.join(src_path, item)
                            dest = os.path.join(target_folder, item)
                            if os.path.exists(dest):
                                dest = get_unique_filename(dest)
                            shutil.copy2(item_path, dest)
                    else:
                        folder_name = os.path.basename(src_path)
                        dest = os.path.join(target_folder, folder_name)
                        if os.path.exists(dest):
                            dest = get_unique_filename(dest)
                        shutil.copytree(src_path, dest)
                    self.emit_log(f" -> [선적서류] 이동 실패 → 복사 완료: {os.path.basename(src_path)} (원본 수동 처리 필요)")
                    failed.append((os.path.basename(src_path), "이동 실패로 복사함. 원본 파일을 수동으로 처리해 주세요."))
                except Exception as copy_err:
                    self.emit_log(f" -> [선적서류 이동/복사 실패] {os.path.basename(src_path)}: {copy_err}")
                    failed.append((os.path.basename(src_path), f"이동/복사 모두 실패: {copy_err}"))

        return failed

    def _find_similar_company_key(self, cache, clean_company, threshold=0.80):
        """캐시에서 유사 회사명 검색 (자모 분해 기반, OCR 오인식 대응)"""
        from core.utils import company_name_similarity
        best_key, best_ratio = None, 0.0
        for key in cache:
            ratio = company_name_similarity(clean_company, key)
            if ratio > best_ratio:
                best_ratio = ratio
                best_key = key
        if best_ratio >= threshold:
            return best_key
        return None

    def _lazy_load_children(self, cache, key):
        """캐시 항목의 children이 None이면 지연 로드"""
        entry = cache.get(key)
        if entry:
            folder_path, children = entry
            if children is None:
                try:
                    children = {e.name for e in os.scandir(folder_path)}
                except (PermissionError, OSError):
                    children = set()
                cache[key] = (folder_path, children)
            return folder_path, children
        return None, set()

    def _find_id_in_company_dir(self, root, company, target_id, _cache=None):
        """BL 중복 검사. 반환: (rel_path, is_similar) 또는 (None, False)"""
        cache = _cache or self._get_dir_cache(root)
        clean_company = company.replace("★", "").strip().upper()
        # 1차: 정확 매칭
        entry = cache.get(clean_company)
        if entry:
            folder_path, children = self._lazy_load_children(cache, clean_company)
            if target_id in children:
                return os.path.relpath(os.path.join(folder_path, target_id), root), False
        # 2차: 유사 회사명에서 같은 BL 검색
        similar_key = self._find_similar_company_key(cache, clean_company)
        if similar_key and similar_key != clean_company:
            folder_path, children = self._lazy_load_children(cache, similar_key)
            if target_id in children:
                return os.path.relpath(os.path.join(folder_path, target_id), root), True
        return None, False

    def _find_company_folder(self, root, company, _cache=None):
        """회사 폴더 검색. 반환: (folder_path, is_similar) 또는 (None, False)"""
        cache = _cache or self._get_dir_cache(root)
        clean_company = company.replace("★", "").strip().upper()
        # 1차: 정확 매칭
        entry = cache.get(clean_company)
        if entry:
            return entry[0], False
        # 2차: 유사 회사명 매칭
        similar_key = self._find_similar_company_key(cache, clean_company)
        if similar_key:
            entry = cache.get(similar_key)
            if entry:
                return entry[0], True
        return None, False

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
                self.start_background_indexing(d)
            elif mode == 'export':
                self.archiver.export_root = d
                self.lbl_exp_root.setText(d)
                self.lbl_exp_root.setStyleSheet("color: #00aaaa; font-size: 8pt;")
                self.start_background_indexing(d)
            elif mode == 'export_docs':
                self.archiver.export_docs_root = d
                self.lbl_exp_docs_root.setText(d)
                self.lbl_exp_docs_root.setStyleSheet("color: #00aaaa; font-size: 8pt;")
            self.settings_changed.emit()

    def emit_log(self, msg):
        if self.archiver and hasattr(self.archiver, 'log_callback') and self.archiver.log_callback:
            self.archiver.log_callback(msg)
        else:
            print(f"[FileManager Log] {msg}")

    def _on_admin_unlock(self):
        """관리자 비밀번호 검증"""
        from version import get_admin_password
        pw = self.input_admin_pw.text().strip()
        if not pw:
            JarvisMessageBox.warning(self, "오류", "비밀번호를 입력해주세요.")
            return

        if pw == get_admin_password():
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
            cfg_path = get_config_path()
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            # 비밀번호는 keyring에 저장 (config.json에 저장하지 않음)
            import keyring
            keyring.set_password("TRADIS_MH", "email_password", password)

            config['hanbiro_mail'] = {
                'imap_server': 'raeon.hanbiro.net',
                'imap_port': 993,
                'email': email
            }

            with open(cfg_path, 'w', encoding='utf-8') as f:
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

    def _preconnect_imap(self):
        """정산서 우클릭 시 IMAP 사전 연결 (메뉴 표시 동안 백그라운드)"""
        def do_preconnect():
            try:
                import json
                config_path = get_config_path()
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                hanbiro = config.get('hanbiro_mail', {})
                email_addr = hanbiro.get('email', '')
                imap_server = hanbiro.get('imap_server', 'raeon.hanbiro.net')
                import keyring
                password = keyring.get_password("TRADIS_MH", "email_password") or ''
                if email_addr and password:
                    from export_mail_sender import ExportMailSender, EmailConfig
                    ec = EmailConfig(imap_server=imap_server, email=email_addr, password=password)
                    sender = ExportMailSender(ec)
                    sender.ensure_connections()
                    print("[메일] IMAP 사전 연결 완료")
            except Exception as e:
                print(f"[메일] 사전 연결 실패 (무시): {e}")

        threading.Thread(target=do_preconnect, daemon=True).start()

    def _on_mail_send_requested(self, file_path: str):
        """정산서 파일 우클릭 → 메일 보내기 처리"""
        print(f"[메일 보내기] _on_mail_send_requested 진입: {file_path}")
        try:
            self._do_mail_send(file_path)
        except Exception as e:
            print(f"[메일 보내기 오류] {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "오류", f"메일 보내기 처리 중 오류:\n{e}")

    def _do_mail_send(self, file_path: str):
        import re
        import datetime
        import threading
        import json
        from export_mail_sender import ExportMailSender, EmailConfig, FoundEmailThread
        from .dialogs import MailThreadSelectDialog, SendMailDialog

        filename = os.path.basename(file_path)
        print(f"[메일 보내기] _do_mail_send 진입: filename={filename}")

        # 파일명에서 B/L, 업체명 파싱: {company}({bl_id})정산서.pdf
        match = re.search(r'^(.+?)\(([^)]+)\)', filename)
        if not match:
            QMessageBox.warning(self, "오류", f"파일명에서 B/L 번호를 추출할 수 없습니다.\n{filename}")
            return
        company = match.group(1).strip()
        bl_id = match.group(2).strip()

        # EmailConfig 구성
        config_path = get_config_path()
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            hanbiro = config.get('hanbiro_mail', {})
            email_addr = hanbiro.get('email', '')
            imap_server = hanbiro.get('imap_server', 'raeon.hanbiro.net')
        except Exception:
            email_addr = ''
            imap_server = 'raeon.hanbiro.net'

        import keyring
        password = keyring.get_password("TRADIS_MH", "email_password") or ''

        if not email_addr or not password:
            QMessageBox.warning(self, "메일 설정 필요", "SETTINGS 탭에서 메일 설정을 먼저 해주세요.")
            return

        email_config = EmailConfig(
            imap_server=imap_server,
            email=email_addr,
            password=password,
        )
        sender = ExportMailSender(email_config)

        # 로딩 표시 (Frosted Glass)
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        from PyQt6.QtGui import QFont, QColor as QC

        self._mail_loading = QDialog(self)
        self._mail_loading.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self._mail_loading.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        loading_lbl = QLabel(f"  메일 검색 중...  ({bl_id})  ")
        loading_lbl.setFont(QFont("Segoe UI", 11))
        loading_lbl.setStyleSheet("""
            background-color: rgba(25, 32, 48, 235);
            border: 1px solid rgba(0, 255, 255, 0.3);
            border-radius: 14px;
            color: #00ddee;
            padding: 18px 28px;
        """)
        loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(QC(0, 0, 0, 160))
        loading_lbl.setGraphicsEffect(shadow)

        ll = QVBoxLayout(self._mail_loading)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(loading_lbl)
        self._mail_loading.adjustSize()
        self._mail_loading.show()
        QApplication.processEvents()

        # IMAP 검색 (백그라운드) → 시그널로 메인 스레드에 전달
        def do_search():
            try:
                results = sender.search_threads_by_bl(bl_id)
            except Exception as e:
                print(f"[메일 검색 오류] {e}")
                results = []
            self._mail_search_done.emit(company, bl_id, file_path, results, email_addr)

        threading.Thread(target=do_search, daemon=True).start()

    def _show_mail_thread_dialog(self, company, bl_id, file_path, threads, my_email):
        """IMAP 검색 결과로 메일 선택 다이얼로그 → SendMailDialog"""
        # 로딩 다이얼로그 닫기
        if hasattr(self, '_mail_loading') and self._mail_loading:
            self._mail_loading.close()
            self._mail_loading = None
        try:
            self._do_show_mail_thread_dialog(company, bl_id, file_path, threads, my_email)
        except Exception as e:
            print(f"[메일 다이얼로그 오류] {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "오류", f"메일 다이얼로그 오류:\n{e}")

    def _do_show_mail_thread_dialog(self, company, bl_id, file_path, threads, my_email):
        import datetime
        from .dialogs import MailThreadSelectDialog, SendMailDialog
        print(f"[메일 다이얼로그] threads={len(threads)}건, company={company}, bl={bl_id}")

        dlg = MailThreadSelectDialog(self, threads=threads, bl_number=bl_id)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dlg.selected_thread

        # 시간대별 인사말 (랜덤 선택)
        import random
        hour = datetime.datetime.now().hour
        if 6 <= hour < 12:
            greeting_first = random.choice([
                "상쾌한 아침입니다.",
                "활기찬 아침이네요!",
                "기분 좋은 아침이네요!",
                "항상 맡겨주셔서 감사합니다.",
            ])
            greeting_last = random.choice([
                "기분 좋은 하루 되시길 바랍니다~",
                "오늘도 좋은 일만 가득하시길 바랍니다~",
                "즐거운 하루 되세요~",
                "오늘도 활기찬 하루 보내세요~",
            ])
        elif 12 <= hour < 18:
            greeting_first = random.choice([
                "항상 감사드립니다.",
                "늘 도움 주셔서 감사합니다.",
                "항상 맡겨주셔서 감사합니다.",
                "늘 잘 부탁드립니다.",
            ])
            greeting_last = random.choice([
                "항상 좋은 일만 가득하시길 바랍니다~",
                "남은 하루도 좋은 하루 되세요~",
                "남은 오후도 힘내세요~",
                "오늘도 좋은 일만 가득하시길 바랍니다~",
            ])
        else:
            greeting_first = random.choice([
                "항상 감사드립니다.",
                "늦은 시간에 보내드립니다.",
                "늘 신경 써주셔서 감사합니다.",
                "덕분에 잘 진행되고 있습니다.",
            ])
            greeting_last = random.choice([
                "편안한 저녁되세요~",
                "편안한 밤 보내세요~",
                "편안하고 여유로운 저녁 되세요~",
                "푹 쉬시고 내일도 힘내세요~",
            ])

        # 본문 템플릿
        body = (
            f"안녕하세요\n\n"
            f"해도관세사무소 최명헌입니다.\n"
            f"{greeting_first}\n\n"
            f"{company}({bl_id})건 정산서 보내드립니다.\n\n"
            f"{greeting_last}\n\n"
            f"감사합니다.\n"
            f"최명헌 드림"
        )

        if selected:
            # 답장: "내가 보낸 메일"이면 to 필드를 원본 수신자로
            my_id = my_email.split('@')[0].lower()
            sender_email = selected.sender.lower()
            if my_id in sender_email or my_email.lower() in sender_email:
                to = selected.to
            else:
                to = selected.sender
            cc = selected.cc or ""
            subject = f"Re: {selected.subject}" if not selected.subject.startswith("Re:") else selected.subject
            in_reply_to = selected.message_id
            references = selected.message_id
        else:
            # 새 메일
            to = ""
            cc = ""
            subject = f"[해도관세사무소] {company}({bl_id}) - 정산서"
            in_reply_to = ""
            references = ""

        mail_dlg = SendMailDialog(
            parent=self,
            subject=subject,
            body=body,
            attachments=[file_path],
            to=to,
            cc=cc,
            in_reply_to=in_reply_to,
            references=references,
        )
        mail_dlg.exec()

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
        except OSError:
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

    def _request_startup_guide(self):
        """시작 가이드 재표시 요청"""
        self.startup_guide_requested.emit()

    def _show_naming_dialog(self):
        """파일 네이밍 설정 다이얼로그 (Frosted Glass 스타일)"""
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
                                     QLabel, QWidget, QGraphicsDropShadowEffect, QListWidget)
        from PyQt6.QtGui import QFont
        from core.config import get_custom_naming, DEFAULT_FILE_PATTERN, DEFAULT_MERGE_PATTERN

        naming = get_custom_naming()

        dlg = QDialog(self)
        dlg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        dlg.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        dlg.setMinimumWidth(520)

        container = QWidget(dlg)
        container.setObjectName("naming_dlg")
        container.setStyleSheet("""
            #naming_dlg {
                background-color: rgba(45, 50, 60, 230);
                border: 1px solid rgba(100, 110, 120, 0.5);
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
        layout.setContentsMargins(24, 28, 24, 20)
        layout.setSpacing(10)

        _input_style = "background: rgba(20,25,35,200); color: #fff; border: 1px solid #555; padding: 6px; border-radius: 6px; font-size: 10pt;"
        _label_style = "color: rgba(255,255,255,0.6); background: transparent; font-size: 8pt;"

        # 타이틀
        title = QLabel("파일 이름 설정")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff; background: transparent;")
        layout.addWidget(title)

        # 파일 이름 패턴
        lbl1 = QLabel("파일 이름 패턴")
        lbl1.setStyleSheet("color: #00cccc; background: transparent; font-weight: bold;")
        layout.addWidget(lbl1)
        row1 = QHBoxLayout()
        input_file = QLineEdit(naming["file_pattern"])
        input_file.setStyleSheet(_input_style)
        row1.addWidget(input_file)
        btn_r1 = NeonButton("초기화", color="gray")
        btn_r1.setFixedSize(50, 30)
        btn_r1.clicked.connect(lambda: input_file.setText(DEFAULT_FILE_PATTERN))
        row1.addWidget(btn_r1)
        layout.addLayout(row1)

        # 병합 결과 이름
        lbl2 = QLabel("병합 결과 이름")
        lbl2.setStyleSheet("color: #00cccc; background: transparent; font-weight: bold;")
        layout.addWidget(lbl2)
        row2 = QHBoxLayout()
        input_merge = QLineEdit(naming["merge_pattern"])
        input_merge.setStyleSheet(_input_style)
        row2.addWidget(input_merge)
        btn_r2 = NeonButton("초기화", color="gray")
        btn_r2.setFixedSize(50, 30)
        btn_r2.clicked.connect(lambda: input_merge.setText(DEFAULT_MERGE_PATTERN))
        row2.addWidget(btn_r2)
        layout.addLayout(row2)

        # 미리보기
        lbl_preview = QLabel("")
        lbl_preview.setStyleSheet(_label_style)
        lbl_preview.setWordWrap(True)
        def update_preview():
            pat = input_file.text() or DEFAULT_FILE_PATTERN
            try:
                preview = pat.format(company="케이즈트레이드", bl="STZFE2603048", doctype="운송료계산서", amount="242000")
                lbl_preview.setText(f"미리보기: {preview}")
                lbl_preview.setStyleSheet(_label_style)
            except (KeyError, ValueError):
                lbl_preview.setText("미리보기: (잘못된 패턴)")
                lbl_preview.setStyleSheet("color: #ff6666; background: transparent; font-size: 8pt;")
        input_file.textChanged.connect(update_preview)
        update_preview()
        layout.addWidget(lbl_preview)

        lbl_vars = QLabel("사용 가능 변수: {company}  {bl}  {doctype}  {amount}")
        lbl_vars.setStyleSheet("color: rgba(255,255,255,0.35); background: transparent; font-size: 7pt;")
        layout.addWidget(lbl_vars)

        layout.addSpacing(5)

        # 병합 순서
        lbl3 = QLabel("병합 순서")
        lbl3.setStyleSheet("color: #00cccc; background: transparent; font-weight: bold;")
        layout.addWidget(lbl3)

        order_row = QHBoxLayout()
        list_order = QListWidget()
        list_order.setFixedHeight(130)
        list_order.setStyleSheet("background: rgba(20,25,35,200); color: #fff; border: 1px solid #555; border-radius: 6px; font-size: 10pt;")
        for name in naming["merge_order"]:
            list_order.addItem(name)
        order_row.addWidget(list_order)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        btn_up = NeonButton("▲", color="cyan")
        btn_up.setFixedSize(34, 30)
        def move_up():
            r = list_order.currentRow()
            if r > 0:
                item = list_order.takeItem(r)
                list_order.insertItem(r-1, item)
                list_order.setCurrentRow(r-1)
        btn_up.clicked.connect(move_up)
        btn_col.addWidget(btn_up)

        btn_down = NeonButton("▼", color="cyan")
        btn_down.setFixedSize(34, 30)
        def move_down():
            r = list_order.currentRow()
            if r < list_order.count()-1:
                item = list_order.takeItem(r)
                list_order.insertItem(r+1, item)
                list_order.setCurrentRow(r+1)
        btn_down.clicked.connect(move_down)
        btn_col.addWidget(btn_down)

        btn_reset = NeonButton("↺", color="gray")
        btn_reset.setFixedSize(34, 30)
        btn_reset.setToolTip("기본 순서로 초기화")
        def reset_order():
            list_order.clear()
            for n in ["정산서", "신고필증", "납부고지서", "세금계산서", "비용계산서"]:
                list_order.addItem(n)
        btn_reset.clicked.connect(reset_order)
        btn_col.addWidget(btn_reset)
        btn_col.addStretch()
        order_row.addLayout(btn_col)
        layout.addLayout(order_row)

        layout.addSpacing(10)

        # 버튼
        from PyQt6.QtWidgets import QPushButton
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_cancel = QPushButton("취소")
        btn_cancel.setFixedHeight(42)
        btn_cancel.setMinimumWidth(100)
        btn_cancel.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton { background-color: rgba(100,105,115,180); border: 1px solid rgba(150,155,165,0.5);
                border-radius: 12px; color: #fff; padding: 8px 20px; }
            QPushButton:hover { background-color: rgba(120,125,135,200); }
        """)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_cancel)

        btn_save = QPushButton("저장")
        btn_save.setFixedHeight(42)
        btn_save.setMinimumWidth(100)
        btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet("""
            QPushButton { background-color: rgba(30,35,45,200); border: 2px solid #00d4ff;
                border-radius: 12px; color: #00d4ff; padding: 8px 20px; }
            QPushButton:hover { background-color: rgba(0,212,255,40); border-color: #00ffff; color: #00ffff; }
        """)

        def on_save():
            file_pat = input_file.text().strip() or DEFAULT_FILE_PATTERN
            merge_pat = input_merge.text().strip() or DEFAULT_MERGE_PATTERN
            order = [list_order.item(i).text() for i in range(list_order.count())]
            try:
                file_pat.format(company="t", bl="t", doctype="t", amount="0")
                merge_pat.format(company="t", bl="t")
            except (KeyError, ValueError) as e:
                JarvisMessageBox.warning(self, "패턴 오류", f"잘못된 패턴: {e}")
                return

            cfg_path = get_config_path()
            try:
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                else:
                    data = {}
                data["custom_naming"] = {"file_pattern": file_pat, "merge_pattern": merge_pat, "merge_order": order}
                tmp = cfg_path + ".tmp"
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                os.replace(tmp, cfg_path)
                dlg.accept()
                JarvisMessageBox.information(self, "저장 완료", "네이밍 설정이 저장되었습니다.")
                self.settings_changed.emit()
            except Exception as e:
                JarvisMessageBox.warning(self, "저장 실패", f"{e}")

        btn_save.clicked.connect(on_save)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        dlg.exec()

    def _update_naming_preview(self):
        """파일 이름 패턴 미리보기 갱신"""
        pattern = self.input_file_pattern.text() or "{company}({bl}){doctype}.pdf"
        try:
            preview = pattern.format(company="케이즈트레이드", bl="STZFE2603048", doctype="운송료계산서", amount="242000")
            self.lbl_naming_preview.setText(f"미리보기: {preview}")
            self.lbl_naming_preview.setStyleSheet("color: rgba(255,255,255,0.5); font-size: 8pt;")
        except (KeyError, ValueError):
            self.lbl_naming_preview.setText("미리보기: (잘못된 패턴 — {company}, {bl}, {doctype} 사용)")
            self.lbl_naming_preview.setStyleSheet("color: #ff6666; font-size: 8pt;")

    def _move_merge_order_up(self):
        row = self.list_merge_order.currentRow()
        if row > 0:
            item = self.list_merge_order.takeItem(row)
            self.list_merge_order.insertItem(row - 1, item)
            self.list_merge_order.setCurrentRow(row - 1)

    def _move_merge_order_down(self):
        row = self.list_merge_order.currentRow()
        if row < self.list_merge_order.count() - 1:
            item = self.list_merge_order.takeItem(row)
            self.list_merge_order.insertItem(row + 1, item)
            self.list_merge_order.setCurrentRow(row + 1)

    def _reset_merge_order(self):
        self.list_merge_order.clear()
        for name in ["정산서", "신고필증", "납부고지서", "세금계산서", "비용계산서"]:
            self.list_merge_order.addItem(name)

    def _save_naming_settings(self):
        """커스텀 네이밍 설정 저장"""
        from core.config import get_config_path, DEFAULT_FILE_PATTERN, DEFAULT_MERGE_PATTERN, DEFAULT_MERGE_ORDER
        import json

        file_pat = self.input_file_pattern.text().strip() or DEFAULT_FILE_PATTERN
        merge_pat = self.input_merge_pattern.text().strip() or DEFAULT_MERGE_PATTERN
        order = [self.list_merge_order.item(i).text() for i in range(self.list_merge_order.count())]

        # 패턴 유효성 검증
        try:
            file_pat.format(company="test", bl="test", doctype="test", amount="0")
            merge_pat.format(company="test", bl="test")
        except (KeyError, ValueError) as e:
            JarvisMessageBox.warning(self, "패턴 오류", f"잘못된 패턴입니다: {e}\n사용 가능: {{company}}, {{bl}}, {{doctype}}, {{amount}}")
            return

        cfg_path = get_config_path()
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {}
            data["custom_naming"] = {
                "file_pattern": file_pat,
                "merge_pattern": merge_pat,
                "merge_order": order,
            }
            tmp = cfg_path + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp, cfg_path)
            JarvisMessageBox.information(self, "저장 완료", "네이밍 설정이 저장되었습니다.")
            self.settings_changed.emit()
        except Exception as e:
            JarvisMessageBox.warning(self, "저장 실패", f"설정 저장 오류: {e}")

    def _load_naming_settings(self):
        """커스텀 네이밍 설정 로드"""
        from core.config import get_custom_naming
        naming = get_custom_naming()
        self.input_file_pattern.setText(naming["file_pattern"])
        self.input_merge_pattern.setText(naming["merge_pattern"])
        self.list_merge_order.clear()
        for name in naming["merge_order"]:
            self.list_merge_order.addItem(name)

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

## 초기 설정

| 항목 | 설정 방법 |
|------|----------|
| **Gemini API 키** | 좌측 사이드바 API 톱니바퀴 → 키 입력 → 저장 |
| **감시 폴더** | 좌측 사이드바 TARGET DIRECTORY → 폴더 선택 |
| **수입 서버 경로** | 설정 탭 → SET IMPORT ROOT |
| **수출 서버 경로** | 설정 탭 → SET EXPORT ROOT |
| **선적서류폴더** | 설정 탭 → SET SHIPPING DOCS |
| **한비로 메일** | 설정 탭 → HANBIRO MAIL SETTING → ID/PW 입력 → SAVE |
| **관리자 잠금 해제** | 설정 탭 → ADMIN UNLOCK → 비밀번호 → UNLOCK |

> 일정, 통관, 보고 탭은 관리자 잠금 해제 후 사용할 수 있습니다.

---

## 정산 탭

수입 통관 서류를 AI로 자동 분석하고, 정산서 기준으로 매칭/병합합니다.

### 워크플로우
1. 좌측 사이드바 **시작** 클릭 → 모니터링 시작
2. 감시 폴더에 PDF 투입 → AI가 서류 유형/회사명/B/L/금액 추출 → 자동 이름변경
3. B/L별 **그룹 카드** 생성 → 서류 체크리스트 확인
4. **합치기 실행** (또는 **폴더 정리**) → 정산서 순서대로 PDF 병합
5. 합치기 완료 후 → **선적서류 자동 검색 팝업** 표시
6. 우측 파일 매니저에서 **수입/수출** 서버로 이동

### 자동 매칭 규칙
- 자금정산서 → 수입신고필증 → 납부고지서 → 세금계산서 순서 고정
- 비용 항목명 ↔ 파일명 키워드 매칭
- 통합 계산서는 내부 청구 항목(billing_items) 분석
- 키워드 매칭 실패 시 금액 기반 보정 매칭
- 식물검역/식품검역/CITES 등 요건 서류 자동 매칭

### 카드 조작
| 버튼 | 기능 |
|------|------|
| AI 분석 | 해당 그룹 재분석 |
| 폴더 정리 | 병합 없이 폴더만 생성하여 이동 |
| ▲ ▼ | 병합 순서 변경 |
| + 행 추가 | 수동으로 파일 추가 |
| 📂 파일 추가 | 첨부 파일 추가 (선적서류 등 수동 첨부) |

### 선적서류 자동 검색
- 합치기/폴더 정리 완료 후 자동으로 선적서류폴더 검색
- BL/Invoice 번호로 매칭되는 폴더/파일을 팝업으로 표시
- 사용자가 선택 → BL 폴더 안으로 자동 이동
- 매칭이 안 되면 카드의 [📂 파일 추가] 버튼으로 수동 첨부

---

## 파일 매니저 (우측)

| 기능 | 설명 |
|------|------|
| **MOVE TARGET** | 감시 폴더 내 폴더 목록 표시 |
| **→ 수입 / → 수출** | 선택 폴더를 서버 경로로 이동 |
| **TRADIS SEARCH** | Everything 기반 전체 드라이브 검색 |
| **파일 탐색기** | 하단 폴더 트리로 직접 탐색/드래그 이동 |
| **홈 폴더** | 탐색기에서 홈 폴더 설정/이동 |

---

## 일정 탭 (관리자)

- 월간 캘린더 + 일정 카드 관리
- 날짜 클릭으로 필터링, 드래그로 기간 일정 생성
- 반복 설정: 30분 / 매시간 / 3시간 / 매일 / 매주 / 매월
- 알림: 정시 / 15분 전 / 1시간 전 / 1일 전 / 2일 전 (Windows 토스트)

---

## 통관 탭 (관리자)

수출 통관 자동화 — 메일 감지부터 ReadyKorea 입력까지.

1. **START** → 한비로 메일 모니터링
2. 수출 요청 메일 감지 → 목록 표시
3. 메일 선택 → Excel 파싱 (품명/수량/단가/중량)
4. **자동 입력** → ReadyKorea에 데이터 입력
5. **메일 발송** → 수출신고필증 회신

> 필요: 한비로 메일 설정 완료, ReadyKorea 실행 중

---

## 보고 탭 (관리자)

일일 업무 보고서 PDF 생성 및 발송.

- 보고 일자, 통관 현황(건수/수수료), 미수금/대납금 테이블, 특이사항 입력
- Google Sheets 대납장 데이터 자동 불러오기
- PDF 저장 / 한비로 메일 발송 / 실시간 미리보기

---

## 퀵 메모 & 단축키

| 기능 | 단축키 |
|------|--------|
| 퀵 메모 팝업 | Ctrl + Shift + M (변경 가능) |
| 텍스트 스니펫 | Ctrl + 1~9 (최대 9개 등록) |

- 메모: 다중 탭, 자동 저장
- 스니펫 설정: 퀵 메모 팝업 → 설정 버튼
- 미니 윈도우: 최소화 시 작은 플로팅 창으로 전환 (드래그 이동 가능)

---

## 자동 업데이트

- 실행 시 GitHub에서 최신 버전 자동 확인
- 업데이트 클릭 → 다운로드 → EXE 교체 → 재시작 안내
- 설정 및 데이터(data/ 폴더)는 유지됩니다

---

## 데이터 저장

| 파일 | 내용 |
|------|------|
| data/config.json | 경로, 메일, 스니펫 등 설정 |
| data/schedules.json | 일정 데이터 |
| data/report_data.json | 보고서 입력값 |
| data/.analysis_cache.json | PDF 분석 캐시 |
| data/credentials.json | Google Sheets 인증 (수동 배치) |

- API 키/메일 비밀번호는 **Windows 자격 증명 관리자**에 저장
- data/ 폴더 백업으로 설정 보존 가능

---

**TRADIS MH** v1.0.36 by M.H. Choi
"""
        
        browser.setMarkdown(manual_content)
        layout.addWidget(browser)
        
        # 닫기 버튼
        btn_close = NeonButton("닫기")
        btn_close.setFixedHeight(40)
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)
        
        dlg.exec()

