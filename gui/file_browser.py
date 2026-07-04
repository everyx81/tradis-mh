# 파일 브라우저 공용 위젯 — 보내기 트레이(Ctrl+T)와 정산 패널 [파일] 뷰가 함께 사용
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
                             QStyle, QFileIconProvider, QAbstractItemView)
from PyQt6.QtCore import (Qt, QTimer, QFileSystemWatcher, QSize, QRect,
                          QFileInfo, pyqtSignal)
from PyQt6.QtGui import QFontMetrics, QColor, QPainter, QFont

from .widgets import DropListWidget
from .claude_theme import C as CT, FONT_UI

SUB_ROLE = Qt.ItemDataRole.UserRole + 1  # 부제목 (시간·크기)

# Windows 11 Fluent / Win10 MDL2 시스템 아이콘 폰트
ICON_FONT = "'Segoe Fluent Icons', 'Segoe MDL2 Assets'"
GLYPH_HOME = "\uE80F"
GLYPH_UP = "\uE74A"
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

    def __init__(self, path_callback, parent=None):
        super().__init__(parent)
        self.path_callback = path_callback
        self.current_folder = None
        self._icon_provider = QFileIconProvider()

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
        self._populate()

    def refresh(self):
        self._populate()

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

        dirs.sort(key=lambda x: x[0].lower())
        files.sort(key=lambda x: x[2], reverse=True)  # 최신 파일이 맨 위

        for name, full, mtime in dirs:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, full)
            item.setData(SUB_ROLE, "폴더")
            item.setIcon(self._icon_provider.icon(QFileInfo(full)))
            self.list.addItem(item)
        for name, full, mtime, size in files[:self.MAX_FILES]:
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
