# 파일 브라우저 공용 위젯 — 보내기 트레이(기본 Ctrl+G)와 정산 패널 [파일] 뷰가 함께 사용
"""
지정 폴더(target_path)의 파일을 최신순으로 보여주는 브라우저.

- 드래그: DropListWidget의 OLE 드래그 재사용 — 카카오톡/네이트온 호환
- Del: 휴지통으로 삭제 (복구 가능)
- F2: 이름 변경 (DropListWidget 기본 동작)
- 더블클릭: 폴더는 안에서 이동, 파일은 실행
- 외부 파일을 떨어뜨리면 현재 폴더로 복사
- 폴더 내용이 바뀌면 자동 새로고침 (QFileSystemWatcher)
"""

import os
import time
import shutil
import ctypes
import datetime
from ctypes import wintypes

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QListWidgetItem, QStyledItemDelegate,
                             QStyle, QFileIconProvider, QAbstractItemView,
                             QLineEdit)
from PyQt6.QtCore import (Qt, QTimer, QFileSystemWatcher, QSize, QRect,
                          QFileInfo, pyqtSignal, QEvent)
from PyQt6.QtGui import QFontMetrics, QColor, QPainter, QFont

from .widgets import DropListWidget
from .claude_theme import C as CT, FONT_UI

SUB_ROLE = Qt.ItemDataRole.UserRole + 1  # 부제목 (시간·크기)

# Windows 11 Fluent / Win10 MDL2 시스템 아이콘 폰트
ICON_FONT = "'Segoe Fluent Icons', 'Segoe MDL2 Assets'"
GLYPH_HOME = "\uE80F"
GLYPH_UP = "\uE74A"
GLYPH_DOWN = "\uE74B"
GLYPH_FOLDER = "\uE838"
GLYPH_CLOSE = "\uE8BB"


# ------------------------------------------------------------
# 휴지통 삭제 (SHFileOperationW + FOF_ALLOWUNDO)
# ------------------------------------------------------------
class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", ctypes.c_uint),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def move_to_recycle_bin(paths):
    """파일/폴더를 휴지통으로 이동. 성공 시 True."""
    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40
    FOF_NOCONFIRMATION = 0x10
    FOF_SILENT = 0x04
    valid = [os.path.abspath(p) for p in paths if p and os.path.exists(p)]
    if not valid:
        return False
    # pFrom은 이중 널 종료 문자열 (ctypes가 마지막 널 하나를 추가)
    src = "\0".join(valid) + "\0"
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = src
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
    try:
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return result == 0 and not op.fAnyOperationsAborted
    except Exception as e:
        print(f"휴지통 이동 오류: {e}")
        return False


def _rel_time(ts):
    """수정 시각 → '방금 전', '3분 전', '어제' 등 상대 시간 문자열"""
    diff = time.time() - ts
    if diff < 60:
        return "방금 전"
    if diff < 3600:
        return f"{int(diff // 60)}분 전"
    if diff < 86400:
        return f"{int(diff // 3600)}시간 전"
    if diff < 172800:
        return "어제"
    dt = datetime.datetime.fromtimestamp(ts)
    return f"{dt.month}월 {dt.day}일"


def _fmt_size(num):
    """바이트 → 사람이 읽기 좋은 크기"""
    if num < 1024:
        return f"{num} B"
    if num < 1024 ** 2:
        return f"{num / 1024:.0f} KB"
    if num < 1024 ** 3:
        return f"{num / 1024 ** 2:.1f} MB"
    return f"{num / 1024 ** 3:.1f} GB"


# ------------------------------------------------------------
# 리스트 아이템 델리게이트 — 아이콘 + 파일명 + 부제목 2줄 렌더링
# ------------------------------------------------------------
class FileItemDelegate(QStyledItemDelegate):
    ROW_H = 46

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.ROW_H)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(2, 1, -2, -1)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(75, 163, 247, 42))
            painter.drawRoundedRect(rect, 8, 8)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 12))
            painter.drawRoundedRect(rect, 8, 8)

        # 파일 아이콘 (탐색기와 동일한 시스템 아이콘)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        icon_x = rect.left() + 10
        if icon and not icon.isNull():
            icon.paint(painter, icon_x, rect.center().y() - 12, 24, 24)

        text_x = icon_x + 34
        text_w = rect.right() - text_x - 8

        # 1줄: 파일명
        name = index.data(Qt.ItemDataRole.DisplayRole) or ""
        name_font = QFont(option.font)
        name_font.setPointSizeF(9.5)
        painter.setFont(name_font)
        painter.setPen(QColor(CT["fg_0"]))
        fm = QFontMetrics(name_font)
        elided = fm.elidedText(name, Qt.TextElideMode.ElideMiddle, text_w)
        painter.drawText(QRect(text_x, rect.top() + 6, text_w, fm.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        # 2줄: 시간 · 크기
        sub = index.data(SUB_ROLE) or ""
        if sub:
            sub_font = QFont(option.font)
            sub_font.setPointSizeF(8.0)
            painter.setFont(sub_font)
            painter.setPen(QColor(CT["fg_3"]))
            sfm = QFontMetrics(sub_font)
            painter.drawText(QRect(text_x, rect.top() + 8 + fm.height(), text_w, sfm.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub)

        painter.restore()


# ------------------------------------------------------------
# 파일 목록 위젯 — DropListWidget 재사용 + 브라우저 전용 동작
# ------------------------------------------------------------
class FileListWidget(DropListWidget):
    """Del=휴지통, 더블클릭 폴더=브라우저 내 이동, 외부 드롭=현재 폴더로 복사"""

    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser
        self.items_dropped.connect(self._copy_dropped_into_folder)
        self.setItemDelegate(FileItemDelegate(self))
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def _on_item_double_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.isdir(path):
            self.browser.navigate_to(path)
            return
        super()._on_item_double_clicked(item)

    def _delete_item(self, item, path):
        # 컨텍스트 메뉴 '삭제'도 휴지통으로 (완전 삭제 방지)
        if move_to_recycle_bin([path]):
            self.takeItem(self.row(item))
            self.refresh_needed.emit()

    def keyPressEvent(self, event):
        items = self.selectedItems()
        if event.key() == Qt.Key.Key_Delete and items:
            paths = [i.data(Qt.ItemDataRole.UserRole) for i in items]
            if move_to_recycle_bin(paths):
                for item in items:
                    row = self.row(item)
                    if row >= 0:
                        self.takeItem(row)
                self.refresh_needed.emit()
        elif event.key() == Qt.Key.Key_Escape:
            self.browser.escape_pressed.emit()
        else:
            # F2(이름 변경) 등은 DropListWidget 기본 동작 사용
            super().keyPressEvent(event)

    def _copy_dropped_into_folder(self, paths):
        """외부(탐색기 등)에서 드롭된 파일을 현재 폴더로 복사"""
        folder = self.current_folder
        if not folder or not os.path.isdir(folder):
            return
        copied = 0
        for src in paths:
            if not src or not os.path.exists(src):
                continue
            dest = os.path.join(folder, os.path.basename(src))
            if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dest)):
                continue
            if os.path.exists(dest):
                print(f"복사 건너뜀 (같은 이름 존재): {os.path.basename(src)}")
                continue
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
                copied += 1
            except Exception as e:
                print(f"파일 복사 실패: {e}")
        if copied:
            self.refresh_needed.emit()


# ------------------------------------------------------------
# 파일 브라우저 위젯 (툴바 + 경로 + 목록)
# ------------------------------------------------------------
class FileBrowserWidget(QWidget):
    """지정 폴더 파일 브라우저 — 트레이/정산 패널 공용"""

    escape_pressed = pyqtSignal()
    MAX_FILES = 200
    SORT_MODES = (("mtime", "최신순"), ("name", "이름순"))

    def __init__(self, path_callback, parent=None):
        super().__init__(parent)
        self.path_callback = path_callback
        self.current_folder = None
        self._icon_provider = QFileIconProvider()
        self._sort_idx = 0        # 기본 최신순
        self._sort_desc = True    # 기본 내림차순 (최신 파일이 맨 위)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ----- 툴바: 이동 버튼 + 현재 경로 -----
        toolbar = QHBoxLayout()
        toolbar.setSpacing(2)

        btn_style = f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 7px;
                color: {CT['fg_2']};
                font-family: {ICON_FONT};
                font-size: 10pt;
                min-width: 30px; min-height: 26px;
            }}
            QPushButton:hover {{ background-color: {CT['bg_3']}; color: {CT['fg_0']}; }}
            QPushButton:pressed {{ background-color: {CT['bg_4']}; }}
        """
        self.btn_home = QPushButton(GLYPH_HOME)
        self.btn_home.setToolTip("지정 폴더로 돌아가기")
        self.btn_up = QPushButton(GLYPH_UP)
        self.btn_up.setToolTip("상위 폴더로")
        self.btn_explorer = QPushButton(GLYPH_FOLDER)
        self.btn_explorer.setToolTip("탐색기에서 열기")
        for b in (self.btn_home, self.btn_up, self.btn_explorer):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(btn_style)
            toolbar.addWidget(b)

        self.lbl_path = QLabel("")
        self.lbl_path.setStyleSheet(f"color: {CT['fg_3']}; font-family: {FONT_UI}; "
                                    f"font-size: 8pt; border: none; background: transparent; padding-left: 6px;")
        toolbar.addWidget(self.lbl_path, 1)

        self.btn_home.clicked.connect(self.go_home)
        self.btn_up.clicked.connect(self.go_up)
        self.btn_explorer.clicked.connect(self._open_in_explorer)
        layout.addLayout(toolbar)

        # ----- 검색 + 정렬 -----
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("파일명 검색")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {CT['bg_2']};
                color: {CT['fg_0']};
                border: 1px solid {CT['border_soft']};
                border-radius: 8px;
                padding: 5px 10px;
                font-family: {FONT_UI};
                font-size: 9pt;
            }}
            QLineEdit:focus {{ border: 1px solid {CT['accent_border']}; }}
            QLineEdit[hasText="true"] {{
                border: 1px solid {CT['accent_border']};
                background-color: {CT['accent_bg']};
            }}
        """)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.installEventFilter(self)  # ESC로 검색어 지우기
        search_row.addWidget(self.search_input, 1)

        _sort_btn_css = f"""
            QPushButton {{
                background-color: {CT['bg_2']};
                color: {CT['fg_1']};
                border: 1px solid {CT['border_soft']};
                border-radius: 8px;
                padding: 5px 8px;
                font-family: {FONT_UI};
                font-size: 8.5pt;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {CT['bg_3']};
                color: {CT['fg_0']};
                border: 1px solid {CT['border']};
            }}
        """
        self.btn_sort = QPushButton(self.SORT_MODES[0][1])
        self.btn_sort.setToolTip("정렬 기준 변경 (최신순 ↔ 이름순)")
        self.btn_sort.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sort.setFixedWidth(62)
        self.btn_sort.setStyleSheet(_sort_btn_css)
        self.btn_sort.clicked.connect(self._cycle_sort)
        search_row.addWidget(self.btn_sort)

        # 오름/내림차순 토글 (▲/▼)
        self.btn_sort_dir = QPushButton(GLYPH_DOWN)
        self.btn_sort_dir.setToolTip("내림차순 — 클릭하면 오름차순으로")
        self.btn_sort_dir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sort_dir.setFixedWidth(30)
        self.btn_sort_dir.setStyleSheet(
            _sort_btn_css.replace(f"font-family: {FONT_UI};", f"font-family: {ICON_FONT};"))
        self.btn_sort_dir.clicked.connect(self._toggle_sort_dir)
        search_row.addWidget(self.btn_sort_dir)
        layout.addLayout(search_row)

        # ----- 파일 목록 -----
        self.list = FileListWidget(self)
        self.list.setStyleSheet(f"""
            QListWidget {{
                background-color: {CT["bg_2"]};
                border: none;
                border-radius: 10px;
                padding: 4px;
                outline: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 4px 2px 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: {CT["border_strong"]};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {CT["fg_3"]};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; background: none; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
            QScrollBar:horizontal {{
                height: 0;
            }}
        """)
        self.list.refresh_needed.connect(self._schedule_refresh)
        layout.addWidget(self.list, 1)

        # ----- 폴더 변경 감시 (자동 새로고침) -----
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule_refresh)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(300)
        self._refresh_timer.timeout.connect(self._populate)

    # ---------- 폴더 탐색 ----------
    def _root_path(self):
        return self.path_callback() if self.path_callback else ""

    def go_home(self):
        """지정 폴더(target_path)로 이동"""
        self.navigate_to(self._root_path())

    def go_up(self):
        """상위 폴더로 (지정 폴더 위로는 안 올라감)"""
        root = os.path.normcase(os.path.abspath(self._root_path() or ""))
        if not self.current_folder:
            return
        cur = os.path.normcase(os.path.abspath(self.current_folder))
        if cur == root:
            return
        self.navigate_to(os.path.dirname(self.current_folder))

    def navigate_to(self, folder):
        old = self._watcher.directories()
        if old:
            self._watcher.removePaths(old)
        self.current_folder = folder
        if folder and os.path.isdir(folder):
            self._watcher.addPath(folder)
        # 폴더 이동 시 검색어 초기화 (검색은 현재 폴더 기준)
        if self.search_input.text():
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
            self._apply_search_style(False)
        self._populate()

    def refresh(self):
        self._populate()

    # ---------- 검색 · 정렬 ----------
    def _apply_search_style(self, has_text):
        """검색어 유무에 따라 입력창 강조 (파란 테두리)"""
        if self.search_input.property("hasText") != has_text:
            self.search_input.setProperty("hasText", has_text)
            st = self.search_input.style()
            st.unpolish(self.search_input)
            st.polish(self.search_input)

    def _on_search_changed(self, text):
        self._apply_search_style(bool(text.strip()))
        self._schedule_refresh()  # 타이핑 디바운스 (300ms)

    def _cycle_sort(self):
        self._sort_idx = (self._sort_idx + 1) % len(self.SORT_MODES)
        self.btn_sort.setText(self.SORT_MODES[self._sort_idx][1])
        # 기준별 자연스러운 기본 방향: 최신순=내림차순(최신 위), 이름순=오름차순(ㄱ→ㅎ)
        self._set_sort_dir(self.SORT_MODES[self._sort_idx][0] == "mtime")

    def _toggle_sort_dir(self):
        self._set_sort_dir(not self._sort_desc)

    def _set_sort_dir(self, desc):
        self._sort_desc = desc
        self.btn_sort_dir.setText(GLYPH_DOWN if desc else GLYPH_UP)
        self.btn_sort_dir.setToolTip(
            "내림차순 — 클릭하면 오름차순으로" if desc else "오름차순 — 클릭하면 내림차순으로")
        self._populate()

    def eventFilter(self, obj, event):
        # 검색창에서 ESC: 검색어 지우기 / 이미 비어 있으면 상위(트레이 닫기 등)로 전달
        if obj is self.search_input and event.type() == QEvent.Type.KeyPress \
                and event.key() == Qt.Key.Key_Escape:
            if self.search_input.text():
                self.search_input.clear()
            else:
                self.escape_pressed.emit()
            return True
        return super().eventFilter(obj, event)

    def _populate(self):
        self.list.clear()
        folder = self.current_folder
        self.list.current_folder = folder

        if not folder or not os.path.isdir(folder):
            self.lbl_path.setText("폴더가 설정되지 않았습니다 — 대상 폴더를 지정하세요")
            return

        # 경로 표시 (길면 앞부분 생략)
        metrics = QFontMetrics(self.lbl_path.font())
        elided = metrics.elidedText(folder, Qt.TextElideMode.ElideLeft, max(self.width() - 130, 100))
        self.lbl_path.setText(elided)
        self.lbl_path.setToolTip(folder)

        dirs, files = [], []
        try:
            with os.scandir(folder) as it:
                for e in it:
                    try:
                        st = e.stat()
                        if e.is_dir():
                            dirs.append((e.name, e.path, st.st_mtime))
                        else:
                            files.append((e.name, e.path, st.st_mtime, st.st_size))
                    except OSError:
                        continue
        except OSError as e:
            self.lbl_path.setText(f"폴더 접근 실패: {e}")
            return

        # 검색 필터 (파일명 부분 일치, 대소문자 무시) — 검색 중엔 표시 개수 제한 해제
        query = self.search_input.text().strip().lower()
        if query:
            dirs = [d for d in dirs if query in d[0].lower()]
            files = [f for f in files if query in f[0].lower()]

        # 폴더는 항상 상단, 파일은 선택된 기준·방향으로 정렬
        sort_mode = self.SORT_MODES[self._sort_idx][0]
        if sort_mode == "name":
            dirs.sort(key=lambda x: x[0].lower(), reverse=self._sort_desc)
            files.sort(key=lambda x: x[0].lower(), reverse=self._sort_desc)
        else:
            dirs.sort(key=lambda x: x[0].lower())
            files.sort(key=lambda x: x[2], reverse=self._sort_desc)

        limit = len(files) if query else self.MAX_FILES

        for name, full, mtime in dirs:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, full)
            item.setData(SUB_ROLE, "폴더")
            item.setIcon(self._icon_provider.icon(QFileInfo(full)))
            self.list.addItem(item)
        for name, full, mtime, size in files[:limit]:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, full)
            item.setData(SUB_ROLE, f"{_rel_time(mtime)}  ·  {_fmt_size(size)}")
            item.setIcon(self._icon_provider.icon(QFileInfo(full)))
            item.setToolTip(name)
            self.list.addItem(item)

    def _schedule_refresh(self):
        self._refresh_timer.start()

    def _open_in_explorer(self):
        if self.current_folder and os.path.isdir(self.current_folder):
            os.startfile(self.current_folder)
