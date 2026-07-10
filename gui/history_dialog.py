# 정리 기록 (합치기/폴더 정리 되돌리기) UI — Claude Design
"""
MergeHistoryDialog — 카드 목록 헤더의 History 버튼으로 여는 기록 팝업.
UndoToast        — 합치기 완료 직후 뜨는 다크 토스트 (되돌리기 버튼 포함).
둘 다 core.merge_history 를 통해 되돌리기를 실행한다.
"""

import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QScrollArea, QFrame, QGraphicsDropShadowEffect, QApplication, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QSize
from PyQt6.QtGui import QIcon, QColor, QPainter, QPalette

from .claude_theme import C as CT
from .claude_icons import pixmap as icpx

from core import merge_history


def _fmt_when(iso_str):
    """ISO 시각 → '오늘 14:30' / '어제 11:02' / '7/4 09:15'"""
    try:
        dt = datetime.fromisoformat(iso_str)
    except Exception:
        return iso_str or ""
    today = datetime.now().date()
    delta = (today - dt.date()).days
    hm = dt.strftime("%H:%M")
    if delta <= 0:
        return f"오늘 {hm}"
    if delta == 1:
        return f"어제 {hm}"
    return f"{dt.month}/{dt.day} {hm}"


def _days_left(iso_str, retention=merge_history.RETENTION_DAYS):
    try:
        dt = datetime.fromisoformat(iso_str)
    except Exception:
        return retention
    return retention - (datetime.now().date() - dt.date()).days


def run_undo(parent, entry_id, log=None, on_done=None):
    """되돌리기 실행 + 결과 팝업. 성공 시 on_done() 호출.

    Returns: 성공 여부(bool)
    """
    from .dialogs import JarvisMessageBox

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        ok, messages = merge_history.undo_entry(entry_id, log=log)
    finally:
        QApplication.restoreOverrideCursor()

    if not ok:
        JarvisMessageBox.warning(parent, "되돌리기 실패", "\n".join(messages))
        return False

    if messages:
        JarvisMessageBox.warning(parent, "되돌리기 완료 (일부 확인 필요)", "\n".join(messages))

    if on_done:
        try:
            on_done()
        except Exception:
            pass
    return True


def confirm_undo(parent, folder_name):
    """되돌리기 확인 팝업 (True=진행)."""
    from .dialogs import JarvisMessageBox
    dlg = JarvisMessageBox(
        parent, "되돌리기",
        f"{folder_name}\n\n합치기 전 상태로 되돌립니다.\n"
        f"병합된 PDF는 삭제되고 원본 파일이 복구됩니다.",
        JarvisMessageBox.Question)
    dlg.add_button("취소", "reject", "gray")
    dlg.add_button("되돌리기", "accept", "cyan")
    return dlg.exec() == QDialog.DialogCode.Accepted


class _ElideLabel(QLabel):
    """폭이 모자라면 스스로 말줄임(…)하는 라벨.

    전역 스타일시트·화면 배율(DPI)에 따라 폰트 크기가 달라져도
    실제 그려지는 폭 기준으로 매번 줄이므로 절대 옆 위젯을 밀지 않는다.
    """

    def __init__(self, text="", mode=Qt.TextElideMode.ElideMiddle):
        super().__init__(text)
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self):
        h = super().minimumSizeHint().height()
        return QSize(60, h)

    def paintEvent(self, event):
        p = QPainter(self)
        elided = self.fontMetrics().elidedText(self.text(), self._mode, self.width())
        p.setPen(self.palette().color(QPalette.ColorRole.WindowText))
        p.drawText(self.rect(),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   elided)


# ============================================================
# 정리 기록 팝업
# ============================================================

class MergeHistoryDialog(QDialog):
    """최근 합치기/폴더 정리 목록 + 골라서 되돌리기"""

    def __init__(self, parent=None, log=None, on_undone=None):
        super().__init__(parent)
        self._log = log
        self._on_undone = on_undone
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(470)
        # 메인 창의 레거시 스타일(QDialog QLabel { padding: 10px; font-size: 11pt } 등)이
        # 이 팝업에 상속돼 아이콘이 잘리고 글자·버튼이 커지는 것을 차단
        self.setStyleSheet("""
            QLabel { padding: 0px; }
            QPushButton { min-width: 0px; padding: 0px; }
        """)
        self._init_ui()
        self._reload()

    def _init_ui(self):
        container = QWidget(self)
        container.setObjectName("history_dlg")
        container.setStyleSheet(f"""
            #history_dlg {{
                background-color: {CT['bg_2']};
                border: 1px solid {CT['border']};
                border-radius: 16px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(5)
        shadow.setColor(Qt.GlobalColor.black)
        container.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 헤더 ──
        header = QHBoxLayout()
        header.setContentsMargins(18, 14, 14, 14)
        header.setSpacing(8)

        ic = QLabel()
        ic.setFixedSize(16, 16)
        ic.setPixmap(icpx("History", size=16, color=CT['fg_2']))
        ic.setStyleSheet("background: transparent; border: none;")
        header.addWidget(ic)

        title = QLabel("파일 합치기 기록")
        title.setStyleSheet(f"color: {CT['fg_0']}; font-size: 11.5pt; font-weight: 600; background: transparent;")
        header.addWidget(title)

        hint = QLabel(f"{merge_history.RETENTION_DAYS}일 보관")
        hint.setStyleSheet(f"color: {CT['fg_3']}; font-size: 8.5pt; background: transparent;")
        header.addWidget(hint)
        header.addStretch()

        btn_close = QPushButton()
        btn_close.setIcon(QIcon(icpx("X", size=15, color=CT['fg_2'])))
        btn_close.setIconSize(QSize(15, 15))
        btn_close.setFixedSize(28, 28)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; border-radius: 8px; }}
            QPushButton:hover {{ background-color: {CT['bg_3']}; }}
        """)
        btn_close.clicked.connect(self.reject)
        header.addWidget(btn_close)
        layout.addLayout(header)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {CT['border_soft']}; border: none;")
        layout.addWidget(sep)

        # ── 목록 ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet("background: transparent; border: none;")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMaximumHeight(420)

        self.list_container = QWidget()
        self.list_container.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(10, 6, 10, 6)
        self.list_layout.setSpacing(0)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.list_container)
        layout.addWidget(self.scroll)

        # ── 푸터 ──
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background-color: {CT['border_soft']}; border: none;")
        layout.addWidget(sep2)

        footer = QLabel(f"{merge_history.RETENTION_DAYS}일이 지난 백업은 휴지통으로 이동됩니다")
        footer.setStyleSheet(f"color: {CT['fg_3']}; font-size: 8.5pt; background: transparent; padding: 10px 18px;")
        layout.addWidget(footer)

    def _reload(self):
        while self.list_layout.count():
            child = self.list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        entries = merge_history.list_entries()
        if not entries:
            empty = QLabel("되돌릴 수 있는 기록이 없습니다.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {CT['fg_3']}; font-size: 9.5pt; background: transparent; padding: 28px 0;")
            self.list_layout.addWidget(empty)
            return

        for i, entry in enumerate(entries):
            self.list_layout.addWidget(self._make_row(entry, last=(i == len(entries) - 1)))

        # 화면 배율/폰트가 커서 한 행의 최소 폭이 기본 폭을 넘으면 팝업을 넓힌다
        # (시간·버튼은 절대 잘리지 않고, 폴더명은 남는 폭에서 말줄임)
        need = (self.list_layout.minimumSize().width()
                + 20   # 리스트 좌우 여백
                + 20   # 팝업 외곽 여백
                + 16)  # 스크롤바 여유
        self.setFixedWidth(max(470, min(need, 760)))

    def _make_row(self, entry, last=False):
        """한 줄 리스트 행: [아이콘] 폴더명 ─ 시간·파일수 [되돌리기]"""
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 9, 8, 9)
        h.setSpacing(10)

        kind = entry.get('kind', 'merge')
        archive_gone = not os.path.isdir(entry.get('archive_dir', ''))
        expiring = _days_left(entry.get('created', '')) <= 1

        ic = QLabel()
        ic.setFixedSize(15, 15)
        ic.setPixmap(icpx("File" if kind == 'merge' else "Folder", size=15,
                          color=CT['fg_3'] if expiring else CT['fg_2']))
        ic.setStyleSheet("background: transparent; border: none;")
        ic.setToolTip("합치기" if kind == 'merge' else "폴더 정리")
        h.addWidget(ic)

        # 폴더명 — 자리가 모자라면 스스로 말줄임 (픽셀 계산 없음, DPI 무관)
        full_name = entry.get('folder_name', '')
        lbl_name = _ElideLabel(full_name)
        lbl_name.setStyleSheet(
            f"color: {CT['fg_2'] if expiring else CT['fg_0']}; font-size: 9.5pt; background: transparent;")
        tooltip = full_name
        if archive_gone:
            tooltip += "\n정리 폴더 없음 (서버 이동됨) — 원본만 복구됩니다"
        lbl_name.setToolTip(tooltip)
        h.addWidget(lbl_name, stretch=1)

        # 서버 이동됨 표시 (주황 점 + 툴팁)
        if archive_gone:
            dot = QLabel()
            dot.setFixedSize(6, 6)
            dot.setStyleSheet(f"background-color: {CT['amber']}; border-radius: 3px;")
            dot.setToolTip("정리 폴더 없음 (서버 이동됨) — 원본만 복구됩니다")
            h.addWidget(dot)

        # 시간 · 파일 수 (삭제 임박이면 상태로 대체) — 고정폭 없이 필요한 만큼 차지
        info_txt = f"{_fmt_when(entry.get('created', ''))} · {merge_history.file_count(entry)}개"
        if expiring:
            info_txt = f"내일 삭제 · {merge_history.file_count(entry)}개"
        lbl_info = QLabel(info_txt)
        lbl_info.setStyleSheet(f"color: {CT['fg_3']}; font-size: 8.5pt; background: transparent;")
        h.addWidget(lbl_info)

        # 되돌리기 버튼 — 크기를 고정하지 않고 패딩으로 여백 확보 (글자 잘림 방지)
        btn = QPushButton("되돌리기")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_style_common = "border-radius: 6px; font-size: 8.5pt; font-weight: 600; padding: 4px 13px;"
        if expiring:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {CT['fg_2']};
                    border: 1px solid {CT['border']};
                    {btn_style_common}
                }}
                QPushButton:hover {{ background-color: {CT['bg_3']}; color: {CT['fg_0']}; }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {CT['accent_bg']};
                    color: {CT['accent_hi']};
                    border: 1px solid {CT['accent_border']};
                    {btn_style_common}
                }}
                QPushButton:hover {{ background-color: rgba(75, 163, 247, 60); }}
            """)
        btn.clicked.connect(lambda _, eid=entry['id'], name=entry.get('folder_name', ''): self._undo_clicked(eid, name))
        h.addWidget(btn)

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(row)
        if not last:
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background-color: rgba(45, 48, 56, 90); border: none; margin: 0 8px;")
            v.addWidget(line)
        return wrap

    def _undo_clicked(self, entry_id, folder_name):
        if not confirm_undo(self, folder_name):
            return
        if run_undo(self, entry_id, log=self._log, on_done=self._on_undone):
            self._reload()


# ============================================================
# 되돌리기 토스트 (다크, 합치기 완료 직후)
# ============================================================

class UndoToast(QWidget):
    """합치기/폴더 정리 완료 알림 + [되돌리기] 버튼 (Claude Design 다크)"""

    _active = []
    DURATION_SEC = 12

    def __init__(self, folder_name, sub_text, undo_callback):
        super().__init__(None)
        self.undo_callback = undo_callback
        self._closing = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(380)

        container = QFrame(self)
        container.setObjectName("undo_toast")
        container.setStyleSheet(f"""
            #undo_toast {{
                background-color: {CT['bg_2']};
                border: 1px solid {CT['border']};
                border-radius: 16px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setXOffset(0)
        shadow.setYOffset(6)
        shadow.setColor(QColor(0, 0, 0, 160))
        container.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(container)

        v = QVBoxLayout(container)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)

        tile = QLabel()
        tile.setFixedSize(34, 34)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setStyleSheet("background-color: rgba(89, 200, 134, 36); border-radius: 10px;")
        tile.setPixmap(icpx("Check", size=18, color=CT['green']))
        top.addWidget(tile)

        col = QVBoxLayout()
        col.setSpacing(2)
        lbl_title = QLabel("정리 완료")
        lbl_title.setStyleSheet(f"color: {CT['fg_0']}; font-size: 10.5pt; font-weight: 600; background: transparent;")
        col.addWidget(lbl_title)
        lbl_sub = QLabel(f"{folder_name} · {sub_text}" if sub_text else folder_name)
        lbl_sub.setStyleSheet(f"color: {CT['fg_2']}; font-size: 9pt; background: transparent;")
        lbl_sub.setWordWrap(True)
        col.addWidget(lbl_sub)
        top.addLayout(col, stretch=1)

        btn_x = QPushButton()
        btn_x.setIcon(QIcon(icpx("X", size=13, color=CT['fg_3'])))
        btn_x.setIconSize(QSize(13, 13))
        btn_x.setFixedSize(24, 24)
        btn_x.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_x.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; border-radius: 7px; }}
            QPushButton:hover {{ background-color: {CT['bg_3']}; }}
        """)
        btn_x.clicked.connect(self.close_toast)
        top.addWidget(btn_x, alignment=Qt.AlignmentFlag.AlignTop)
        v.addLayout(top)

        bottom = QHBoxLayout()
        bottom.addStretch()
        btn_undo = QPushButton("  되돌리기")
        btn_undo.setIcon(QIcon(icpx("Undo", size=13, color=CT['accent_hi'])))
        btn_undo.setIconSize(QSize(13, 13))
        btn_undo.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_undo.setFixedHeight(28)
        btn_undo.setStyleSheet(f"""
            QPushButton {{
                background-color: {CT['accent_bg']};
                color: {CT['accent_hi']};
                border: 1px solid {CT['accent_border']};
                border-radius: 7px;
                padding: 0 14px;
                font-size: 9pt;
                font-weight: 600;
            }}
            QPushButton:hover {{ background-color: rgba(75, 163, 247, 60); }}
        """)
        btn_undo.clicked.connect(self._on_undo)
        bottom.addWidget(btn_undo)
        v.addLayout(bottom)

        self.adjustSize()

        self.slide_anim = QPropertyAnimation(self, b"pos")
        self.slide_anim.setDuration(450)
        self.slide_anim.setEasingCurve(QEasingCurve.Type.OutQuint)
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(350)
        self.fade_anim.setStartValue(1.0)
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.finished.connect(self._on_fade_done)

    def _on_undo(self):
        cb = self.undo_callback
        self.undo_callback = None  # 중복 클릭 방지
        self.close_toast()
        if cb:
            try:
                cb()
            except Exception as e:
                print(f"[UndoToast] callback error: {e}")

    def show_toast(self):
        # 이전 되돌리기 토스트는 정리 (한 번에 하나만)
        for t in list(UndoToast._active):
            t.close_toast()

        screen = QApplication.primaryScreen().availableGeometry()
        end_x = (screen.width() - self.width()) // 2 + screen.x()
        start_y = screen.bottom() + 10
        end_y = screen.bottom() - self.height() - 14

        self.move(int(end_x), int(start_y))
        self.show()
        UndoToast._active.append(self)

        self.slide_anim.setStartValue(QPoint(int(end_x), int(start_y)))
        self.slide_anim.setEndValue(QPoint(int(end_x), int(end_y)))
        self.slide_anim.start()

        QTimer.singleShot(self.DURATION_SEC * 1000, self.close_toast)

    def close_toast(self):
        if self._closing:
            return
        self._closing = True
        if self.fade_anim.state() != QPropertyAnimation.State.Running:
            self.fade_anim.start()

    def _on_fade_done(self):
        if self in UndoToast._active:
            UndoToast._active.remove(self)
        self.deleteLater()
