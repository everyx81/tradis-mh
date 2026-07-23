# 메모 트레이 — 전역 단축키(기본 Ctrl+M, 설정에서 변경 가능)로 여는 항상-위 미니 메모장
"""
보내기 트레이(send_tray.py)와 같은 창 틀(항상 위, 프레임리스, 모니터별
위치·크기 기억, 전역 단축키 토글)의 메모장 버전.

레이아웃(시안 D):
 - 헤더 한 줄: 아이콘 + 현재 메모 이름 + 저장 상태 + 닫기
 - 편집 영역: 카드 형태 (bg_2 + 라운드)
 - 하단 칩 탭: 메모 전환 / [+] 새 메모 / [정리] AI 정리
   칩 더블클릭 = 이름 변경, 우클릭 = 이름 변경·잠금·삭제 메뉴

메모 데이터·저장 로직은 일정 탭의 MK3MemoOnlyWidget을 상속해 그대로 쓰고
(같은 schedule_manager 인스턴스 공유), UI만 트레이용으로 재구성한다.
양쪽 편집 내용이 서로를 덮어쓰지 않도록:
 - 표시 직전: 트레이 메모를 저장소 기준으로 다시 읽음 (reload_memos)
   ※ 메인 메모의 미저장 내용 flush 는 gui_jarvis 토글 코드가 먼저 수행
 - 숨김 시: 트레이 메모 저장 후 on_hidden 콜백 (메인 메모 reload)
"""

import os
import json
import ctypes

from PyQt6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QSizeGrip, QTabWidget, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QCursor, QGuiApplication, QIcon

from .file_browser import ICON_FONT, GLYPH_CLOSE
from .mk3_widgets import MK3MemoOnlyWidget
from .claude_theme import C as CT, FONT_UI
from .claude_icons import pixmap
from core.config import get_config_path

CONFIG_KEY = "memo_tray_geo"  # {모니터이름: [x, y, w, h]}

# 칩 높이 24px 기준 — Qt는 border-radius가 높이/2를 넘으면 사각형으로 그리므로 12px 고정
_CHIP_H = 24
CHIP_NORMAL = f"""
    QPushButton {{
        background-color: {CT['bg_2']}; color: {CT['fg_2']};
        border: 1px solid {CT['border_soft']}; border-radius: {_CHIP_H // 2}px;
        padding: 0px 12px; font-family: {FONT_UI}; font-size: 8.5pt;
    }}
    QPushButton:hover {{ background-color: {CT['bg_3']}; color: {CT['fg_0']}; }}
"""
CHIP_SELECTED = f"""
    QPushButton {{
        background-color: {CT['accent_bg']}; color: {CT['accent_hi']};
        border: 1px solid {CT['accent_border']}; border-radius: {_CHIP_H // 2}px;
        padding: 0px 12px; font-family: {FONT_UI}; font-size: 8.5pt; font-weight: 600;
    }}
"""


class ChipButton(QPushButton):
    """더블클릭 시그널을 지원하는 칩 버튼"""
    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        event.accept()


class TrayMemoWidget(MK3MemoOnlyWidget):
    """MK3 메모 로직 + 시안 D 트레이 레이아웃 (편집 카드 + 하단 칩 탭)"""
    title_changed = pyqtSignal(str)       # 현재 메모 이름 → 창 헤더
    save_state_changed = pyqtSignal(str)  # "입력 중…" / "저장됨" → 창 헤더

    def __init__(self, schedule_manager=None, parent=None):
        super().__init__(schedule_manager=schedule_manager, parent=parent)
        # 디바운스 저장이 실행되는 시점 = 저장 완료 표시
        self.save_timer.timeout.connect(lambda: self.save_state_changed.emit("저장됨"))
        # 초기 로드 시 currentChanged 는 첫 탭에서만 발화 → 전체 칩 동기화 1회 필요
        self._sync_chips()

    def init_ui(self):
        """베이스의 헤더/상단 탭 UI 를 트레이용으로 대체 (__init__ 에서 호출됨)"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 편집 카드 — 탭 바는 숨기고 하단 칩으로 전환
        self.tab_widget = QTabWidget()
        self.tab_widget.tabBar().hide()
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                background-color: {CT['bg_2']};
                border: 1px solid {CT['border_soft']};
                border-radius: 10px;
            }}
        """)
        self.tab_widget.currentChanged.connect(self._on_tab_changed)  # 전환 시 저장 (베이스)
        self.tab_widget.currentChanged.connect(self._sync_chips)
        layout.addWidget(self.tab_widget, 1)

        # 하단 칩 바
        self._chip_row = QHBoxLayout()
        self._chip_row.setSpacing(5)
        layout.addLayout(self._chip_row)

    # ---------- 칩 바 ----------
    def _sync_chips(self, *_):
        """탭 상태를 하단 칩 바에 반영 (탭 추가/삭제/전환/이름변경 후 호출)"""
        while self._chip_row.count():
            item = self._chip_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        cur = self.tab_widget.currentIndex()
        for i in range(self.tab_widget.count()):
            chip = ChipButton(self.tab_widget.tabText(i))
            chip.setFixedHeight(_CHIP_H)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(CHIP_SELECTED if i == cur else CHIP_NORMAL)
            chip.setToolTip("더블클릭: 이름 변경 · 우클릭: 메뉴")
            chip.clicked.connect(lambda _, idx=i: self.tab_widget.setCurrentIndex(idx))
            chip.double_clicked.connect(lambda idx=i: self._rename_chip(idx))
            chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            chip.customContextMenuRequested.connect(
                lambda pos, idx=i, c=chip: self._show_chip_menu(idx, c, pos))
            self._chip_row.addWidget(chip)

        btn_add = QPushButton()
        btn_add.setIcon(QIcon(pixmap("Plus", size=12, color=CT['fg_2'])))
        btn_add.setIconSize(QSize(12, 12))
        btn_add.setFixedSize(30, _CHIP_H)
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.setStyleSheet(CHIP_NORMAL)
        btn_add.setToolTip("새 메모 추가")
        btn_add.clicked.connect(self._add_new_memo)  # setCurrentIndex → _sync_chips 재호출
        self._chip_row.addWidget(btn_add)

        self._chip_row.addStretch()

        btn_ai = QPushButton("정리")
        btn_ai.setIcon(QIcon(pixmap("Sparkles", size=12, color=CT['fg_2'])))
        btn_ai.setIconSize(QSize(12, 12))
        btn_ai.setFixedHeight(_CHIP_H)
        btn_ai.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ai.setStyleSheet(CHIP_NORMAL)
        btn_ai.setToolTip("AI로 메모 내용 정리")
        btn_ai.clicked.connect(self._organize_memo_with_ai)
        self._chip_row.addWidget(btn_ai)

        if cur >= 0:
            self.title_changed.emit(self.tab_widget.tabText(cur))

    def _rename_chip(self, idx):
        self._rename_tab(idx)  # 베이스: 입력 다이얼로그 + 저장소 반영
        self._sync_chips()

    def _show_chip_menu(self, idx, chip, pos):
        editor = self.tab_widget.widget(idx)
        is_locked = bool(editor.property("locked")) if editor else False

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {CT['bg_2']}; color: {CT['fg_0']};
                border: 1px solid {CT['border']}; border-radius: 8px;
            }}
            QMenu::item:selected {{
                background-color: {CT['accent_bg']}; color: {CT['accent_hi']};
            }}
        """)
        act_rename = menu.addAction("이름 변경")
        act_lock = menu.addAction("🔓 잠금 해제" if is_locked else "🔒 잠금")
        act_delete = menu.addAction("삭제")

        action = menu.exec(chip.mapToGlobal(pos))
        if action == act_rename:
            self._rename_chip(idx)
        elif action == act_lock:
            self._toggle_lock(idx)   # 베이스: 읽기전용 + 🔒 제목 + 저장
            self._sync_chips()
        elif action == act_delete:
            self._close_tab(idx)     # 베이스: 잠금/내용 확인 후 삭제
            self._sync_chips()

    # ---------- 상태 표시 ----------
    def _on_text_changed(self):
        super()._on_text_changed()
        self.save_state_changed.emit("입력 중…")

    def reload_memos(self):
        super().reload_memos()
        self._sync_chips()
        self.save_state_changed.emit("저장됨")


class MemoTrayWindow(QWidget):
    """메모 트레이 메인 창"""

    def __init__(self, schedule_manager, on_hidden=None):
        super().__init__()
        self._drag_offset = None
        self._geo_map = self._load_geo_map()
        self._on_hidden = on_hidden

        # 보내기 트레이와 동일: Tool 플래그 없이 프레임리스 + 항상 위
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("메모 트레이")
        self.resize(400, 480)
        self.setMinimumSize(300, 340)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("MemoTrayContainer")
        container.setStyleSheet(f"""
            QFrame#MemoTrayContainer {{
                background-color: {CT["bg_1"]};
                border: 1px solid {CT["border"]};
                border-radius: 14px;
            }}
        """)
        outer.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(6)

        # ----- 헤더 한 줄: 아이콘 + 메모 이름 + 저장 상태 + 닫기 (드래그로 창 이동) -----
        header = QHBoxLayout()
        header.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(pixmap("Book", size=15, color=CT['accent']))
        icon_lbl.setStyleSheet("border: none; background: transparent;")
        header.addWidget(icon_lbl)

        self.lbl_title = QLabel("메모")
        self.lbl_title.setStyleSheet(f"color: {CT['fg_0']}; font-family: {FONT_UI}; "
                                     f"font-size: 10.5pt; font-weight: 600; border: none; background: transparent;")
        header.addWidget(self.lbl_title)

        self.lbl_status = QLabel("저장됨")
        self.lbl_status.setStyleSheet(f"color: {CT['fg_3']}; font-family: {FONT_UI}; "
                                      f"font-size: 8pt; border: none; background: transparent;")
        header.addWidget(self.lbl_status)
        header.addStretch()

        self.btn_close = QPushButton(GLYPH_CLOSE)
        self.btn_close.setToolTip("닫기 (Esc)")
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 7px;
                color: {CT['fg_2']};
                font-family: {ICON_FONT};
                font-size: 10pt;
                min-width: 30px; min-height: 26px;
            }}
            QPushButton:hover {{ background-color: rgba(250, 104, 99, 40); color: {CT['red']}; }}
            QPushButton:pressed {{ background-color: {CT['bg_4']}; }}
        """)
        self.btn_close.clicked.connect(self.hide_tray)
        header.addWidget(self.btn_close)
        layout.addLayout(header)

        # ----- 메모 위젯 (일정 탭과 저장소 공유, 시안 D 레이아웃) -----
        self.memo = TrayMemoWidget(schedule_manager=schedule_manager)
        self.memo.title_changed.connect(self.lbl_title.setText)
        self.memo.save_state_changed.connect(self.lbl_status.setText)
        layout.addWidget(self.memo, 1)

        # 초기 헤더 제목 반영 (시그널 연결 전에 위젯이 구성되므로 수동 1회)
        cur = self.memo.tab_widget.currentIndex()
        if cur >= 0:
            self.lbl_title.setText(self.memo.tab_widget.tabText(cur))

        # ----- 푸터: 크기 조절 그립 -----
        footer = QHBoxLayout()
        footer.addStretch()
        grip = QSizeGrip(container)
        grip.setStyleSheet("background: transparent;")
        footer.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        layout.addLayout(footer)

    # ---------- 표시 / 숨김 ----------
    def toggle(self):
        if self.isVisible():
            self.hide_tray()
        else:
            self.show_at_cursor()

    def show_at_cursor(self):
        """마우스 커서가 있는 모니터에 표시 (모니터별 위치·크기 기억)"""
        # 메인 창에서 수정된 메모 반영 (호출 측에서 먼저 flush 해줌)
        self.memo.reload_memos()

        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        saved = self._geo_map.get(screen.name())
        if saved and len(saved) == 4:
            x, y, w, h = saved
            w = max(self.minimumWidth(), min(w, geo.width()))
            h = max(self.minimumHeight(), min(h, geo.height()))
            x = max(geo.left(), min(x, geo.right() - w))
            y = max(geo.top(), min(y, geo.bottom() - h))
            self.setGeometry(x, y, w, h)
        else:
            # 기본: 해당 모니터 오른쪽 아래
            self.resize(400, 480)
            self.move(geo.right() - self.width() - 16,
                      geo.bottom() - self.height() - 16)

        self.show()
        self.raise_()
        self.activateWindow()
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except (ValueError, OSError):
            pass
        self.memo.focus_current_memo()

    def hide_tray(self):
        if self.isVisible():
            self._save_geometry()
            self.memo.save_all_memos()
        self.hide()
        if self._on_hidden:
            try:
                self._on_hidden()
            except Exception as e:
                print(f"메모 트레이 동기화 오류: {e}")

    # ---------- 위치·크기 기억 ----------
    def _load_geo_map(self):
        try:
            cfg = get_config_path()
            if os.path.exists(cfg):
                with open(cfg, 'r', encoding='utf-8') as f:
                    return json.load(f).get(CONFIG_KEY, {})
        except Exception as e:
            print(f"메모 트레이 위치 로드 오류: {e}")
        return {}

    def _save_geometry(self):
        screen = self.screen()
        if not screen:
            return
        g = self.geometry()
        self._geo_map[screen.name()] = [g.x(), g.y(), g.width(), g.height()]
        try:
            cfg = get_config_path()
            data = {}
            if os.path.exists(cfg):
                with open(cfg, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            data[CONFIG_KEY] = self._geo_map
            tmp = cfg + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp, cfg)
        except Exception as e:
            print(f"메모 트레이 위치 저장 오류: {e}")

    # ---------- 창 이동 / 키 ----------
    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and event.position().y() <= 42):
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        else:
            self._drag_offset = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide_tray()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.isVisible():
            self._save_geometry()
            self.memo.save_all_memos()
        event.accept()
