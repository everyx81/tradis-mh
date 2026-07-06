# 보내기 트레이 — 전역 단축키(기본 Ctrl+G, 설정에서 변경 가능)로 여는 항상-위 미니 파일 창
"""
지정 폴더(target_path)의 파일을 카카오톡·네이트온·메일 창으로 바로
드래그해서 보낼 수 있는 소형 always-on-top 창.

파일 목록 기능은 gui/file_browser.py의 FileBrowserWidget을 사용
(정산 패널 [파일] 뷰와 공용). 이 파일은 창 틀(항상 위, 위치 기억,
전역 단축키 토글)만 담당한다.
"""

import os
import json
import ctypes

from PyQt6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QSizeGrip)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor, QGuiApplication

# move_to_recycle_bin, SUB_ROLE은 기존 사용처 호환을 위해 재노출
from .file_browser import (FileBrowserWidget, move_to_recycle_bin, SUB_ROLE,
                           ICON_FONT, GLYPH_CLOSE)
from .claude_theme import C as CT, FONT_UI
from core.config import get_config_path

CONFIG_KEY = "send_tray_geo"  # {모니터이름: [x, y, w, h]}


class SendTrayWindow(QWidget):
    """보내기 트레이 메인 창"""

    def __init__(self, path_callback):
        super().__init__()
        self._drag_offset = None
        self._geo_map = self._load_geo_map()

        # 미니 윈도우와 동일: Tool 플래그 없이 프레임리스 + 항상 위
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("보내기 트레이")
        self.resize(340, 470)
        self.setMinimumSize(270, 320)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("TrayContainer")
        container.setStyleSheet(f"""
            QFrame#TrayContainer {{
                background-color: {CT["bg_1"]};
                border: 1px solid {CT["border"]};
                border-radius: 14px;
            }}
        """)
        outer.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(6)

        # ----- 헤더 (드래그로 창 이동) -----
        header = QHBoxLayout()
        header.setSpacing(2)

        title = QLabel("보내기 트레이")
        title.setStyleSheet(f"color: {CT['fg_0']}; font-family: {FONT_UI}; "
                            f"font-size: 10.5pt; font-weight: 600; border: none; background: transparent;")
        header.addWidget(title)
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

        # ----- 파일 브라우저 (공용 위젯) -----
        self.browser = FileBrowserWidget(path_callback)
        self.browser.escape_pressed.connect(self.hide_tray)
        layout.addWidget(self.browser, 1)

        # ----- 푸터: 힌트 + 크기 조절 그립 -----
        footer = QHBoxLayout()
        hint = QLabel("드래그로 보내기  ·  Del 휴지통  ·  F2 이름변경")
        hint.setStyleSheet(f"color: {CT['fg_3']}; font-family: {FONT_UI}; "
                           f"font-size: 7.5pt; border: none; background: transparent;")
        footer.addWidget(hint)
        footer.addStretch()
        grip = QSizeGrip(container)
        grip.setStyleSheet("background: transparent;")
        footer.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        layout.addLayout(footer)

    # ---------- 브라우저 위임 (기존 사용처 호환) ----------
    @property
    def list(self):
        return self.browser.list

    @property
    def current_folder(self):
        return self.browser.current_folder

    def go_home(self):
        self.browser.go_home()

    def go_up(self):
        self.browser.go_up()

    def navigate_to(self, folder):
        self.browser.navigate_to(folder)

    # ---------- 표시 / 숨김 ----------
    def toggle(self):
        if self.isVisible():
            self.hide_tray()
        else:
            self.show_at_cursor()

    def show_at_cursor(self):
        """마우스 커서가 있는 모니터에 표시 (모니터별 위치·크기 기억)"""
        self.browser.go_home()

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
            self.resize(340, 470)
            self.move(geo.right() - self.width() - 16,
                      geo.bottom() - self.height() - 16)

        self.show()
        self.raise_()
        self.activateWindow()
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except (ValueError, OSError):
            pass

    def hide_tray(self):
        if self.isVisible():
            self._save_geometry()
        self.hide()

    # ---------- 위치·크기 기억 ----------
    def _load_geo_map(self):
        try:
            cfg = get_config_path()
            if os.path.exists(cfg):
                with open(cfg, 'r', encoding='utf-8') as f:
                    return json.load(f).get(CONFIG_KEY, {})
        except Exception as e:
            print(f"트레이 위치 로드 오류: {e}")
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
            print(f"트레이 위치 저장 오류: {e}")

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
        event.accept()
