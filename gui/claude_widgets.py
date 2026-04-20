# Claude Design — Sidebar hero CircleToggle
"""
120x120 원형 모니터링 토글.
- on 상태: 녹색 링 + 외곽 glow + pulse 애니메이션
- 호버: 살짝 확대 (scale 1.03)
- 프레스: 살짝 축소 (scale 0.97)
"""
from PyQt6.QtCore import Qt, QSize, QRectF, QPropertyAnimation, QEasingCurve, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QRadialGradient, QPainterPath
from PyQt6.QtWidgets import QWidget

from .claude_theme import C as CT
from .claude_icons import pixmap as _icpx


class CircleToggle(QWidget):
    """Play/Stop 토글 — Claude Design hero-toggle"""

    clicked = pyqtSignal()  # 토글 요청 시그널

    def __init__(self, parent=None, size: int = 120):
        super().__init__(parent)
        self._monitoring = False
        self._hover = False
        self._pressed = False
        self._size = size
        self._scale = 1.0
        self._pulse_progress = 0.0   # 0.0 ~ 1.0 반복
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # pulse 애니메이션 (2.4초 루프, ON 상태일 때만)
        self._pulse_anim = QPropertyAnimation(self, b"pulse_progress")
        self._pulse_anim.setDuration(2400)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._pulse_anim.setLoopCount(-1)  # 무한 루프

        # scale 애니메이션 (호버/프레스)
        self._scale_anim = QPropertyAnimation(self, b"scale")
        self._scale_anim.setDuration(200)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ────────────── 외부 API ──────────────
    def set_monitoring(self, on: bool):
        if self._monitoring == on:
            return
        self._monitoring = on
        if on:
            self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._pulse_progress = 0.0
        self.update()

    def monitoring(self) -> bool:
        return self._monitoring

    # ────────────── 애니메이션 속성 ──────────────
    def _get_pulse(self):
        return self._pulse_progress

    def _set_pulse(self, v):
        self._pulse_progress = float(v)
        self.update()

    pulse_progress = pyqtProperty(float, fget=_get_pulse, fset=_set_pulse)

    def _get_scale(self):
        return self._scale

    def _set_scale(self, v):
        self._scale = float(v)
        self.update()

    scale = pyqtProperty(float, fget=_get_scale, fset=_set_scale)

    # ────────────── 이벤트 ──────────────
    def enterEvent(self, event):
        self._hover = True
        self._start_scale_to(1.03)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._pressed = False
        self._start_scale_to(1.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._start_scale_to(0.97)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self._start_scale_to(1.03 if self._hover else 1.0)
            # 클릭 emit — 위치가 위젯 안에 있을 때만
            if self.rect().contains(event.pos()):
                self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _start_scale_to(self, target: float):
        self._scale_anim.stop()
        self._scale_anim.setStartValue(self._scale)
        self._scale_anim.setEndValue(target)
        self._scale_anim.start()

    # ────────────── 그리기 ──────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        # scale transform
        p.translate(cx, cy)
        p.scale(self._scale, self._scale)
        p.translate(-cx, -cy)

        # 외곽 ring 크기 — 위젯 폭의 거의 전체
        ring_inset = 0.5   # 외곽선 두께 절반
        outer_r = self._size / 2.0 - ring_inset

        # ── on 상태: 외곽 glow (여러 겹의 원) ──
        if self._monitoring:
            green = QColor("#59c886")
            # 부드러운 외곽 glow (6px 두께, 투명도 낮게)
            glow_pen = QPen(QColor(89, 200, 134, 22))
            glow_pen.setWidth(12)
            p.setPen(glow_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(ring_inset, ring_inset,
                                 self._size - 2*ring_inset, self._size - 2*ring_inset))

            # ── pulse 링 (애니메이션) ──
            # pulse_progress 0.0 → 1.0 로 진행
            # scale 0.9 → 1.25, opacity 0.5 → 0
            t = self._pulse_progress
            pulse_scale = 0.9 + 0.35 * t
            pulse_opacity = max(0.0, 0.5 * (1.0 - t))
            pulse_alpha = int(255 * pulse_opacity * 0.4)
            if pulse_alpha > 0:
                pulse_pen = QPen(QColor(89, 200, 134, pulse_alpha))
                pulse_pen.setWidth(2)
                p.setPen(pulse_pen)
                rx = self._size / 2.0 * pulse_scale
                p.drawEllipse(QRectF(cx - rx, cy - rx, 2 * rx, 2 * rx))

        # ── 외곽 링 테두리 ──
        if self._monitoring:
            ring_color = QColor("#59c886")  # green
        else:
            ring_color = QColor(63, 66, 75)  # border
        ring_pen = QPen(ring_color)
        ring_pen.setWidth(2)
        p.setPen(ring_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(ring_inset, ring_inset,
                             self._size - 2*ring_inset, self._size - 2*ring_inset))

        # ── 내부 원 (72px) ──
        inner_r = 36.0
        if self._monitoring:
            inner_bg = QColor(89, 200, 134, int(255 * 0.12))
            inner_border = QColor(89, 200, 134, int(255 * 0.30))
            if self._hover:
                inner_bg = QColor(89, 200, 134, int(255 * 0.18))
        else:
            inner_bg = QColor(27, 30, 36)  # bg_2
            inner_border = QColor(45, 48, 56, 150)  # border_soft
            if self._hover:
                inner_bg = QColor(35, 38, 45)  # bg_3

        p.setBrush(inner_bg)
        inner_pen = QPen(inner_border)
        inner_pen.setWidth(1)
        p.setPen(inner_pen)
        p.drawEllipse(QRectF(cx - inner_r, cy - inner_r, 2 * inner_r, 2 * inner_r))

        # ── 아이콘 (Play 또는 Stop) ──
        icon_color = "#59c886" if self._monitoring else "#c1c4c9"  # green or fg_1
        icon_name = "Stop" if self._monitoring else "Play"
        icon_pm = _icpx(icon_name, size=28, color=icon_color, stroke_width=1.5)
        # 28x28 아이콘을 중앙에 배치
        p.drawPixmap(int(cx - 14), int(cy - 14), icon_pm)

        p.end()
