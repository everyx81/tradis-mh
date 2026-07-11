# Claude Design — Sidebar hero CircleToggle
"""
120x120 원형 모니터링 토글.
- on 상태: 녹색 링 + 외곽 glow + pulse 애니메이션
- 호버: 살짝 확대 (scale 1.03)
- 프레스: 살짝 축소 (scale 0.97)
"""
from PyQt6.QtCore import Qt, QSize, QRectF, QPropertyAnimation, QEasingCurve, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QRadialGradient, QPainterPath, QPixmap
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
        self._size = size              # 실제 토글 원 크기
        self._glow_margin = 32         # 외곽 glow를 그릴 여백
        self._scale = 1.0
        self._pulse_progress = 0.0   # 0.0 ~ 1.0 반복
        # 위젯 전체 크기 = 토글 + glow 여백
        self.setFixedSize(size + 2 * self._glow_margin, size + 2 * self._glow_margin)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # pulse 애니메이션: QTimer 로 저프레임 직접 구동 (QPropertyAnimation 60fps 는 idle CPU 를 크게 쓰므로 회피)
        # 주기 6초 × 8fps = 48 step/cycle — 느긋한 호흡, 부드러운 전환
        self._PULSE_DURATION_MS = 6000
        self._PULSE_INTERVAL_MS = 125  # 8fps
        self._pulse_elapsed_ms = 0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(self._PULSE_INTERVAL_MS)
        self._pulse_timer.timeout.connect(self._tick_pulse)

        # scale 애니메이션 (호버/프레스) — 일회성이라 CPU 영향 없음
        self._scale_anim = QPropertyAnimation(self, b"scale")
        self._scale_anim.setDuration(200)
        self._scale_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # paintEvent 캐시: SVG 아이콘과 5겹 glow 를 매 프레임 재생성하지 않도록
        self._cached_icon = None
        self._cached_glow = None

    # ────────────── 외부 API ──────────────
    def set_monitoring(self, on: bool):
        if self._monitoring == on:
            return
        self._monitoring = on
        self._cached_icon = None
        self._cached_glow = None
        if on:
            self._pulse_elapsed_ms = 0
            self._pulse_progress = 0.0
            self._pulse_timer.start()
        else:
            self._pulse_timer.stop()
            self._pulse_progress = 0.0
        self.update()

    def _tick_pulse(self):
        # 위젯이 실제 화면에 안 보이면 (창 최소화·다른 탭에 가림) 리페인트 생략
        if self.visibleRegion().isEmpty():
            return
        self._pulse_elapsed_ms = (self._pulse_elapsed_ms + self._PULSE_INTERVAL_MS) % self._PULSE_DURATION_MS
        self._pulse_progress = self._pulse_elapsed_ms / self._PULSE_DURATION_MS
        self.update()

    def monitoring(self) -> bool:
        return self._monitoring

    # ────────────── 애니메이션 속성 ──────────────
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
    def _build_glow_pixmap(self) -> QPixmap:
        """5겹 radial gradient 를 pixmap 으로 한 번만 렌더링해 캐싱."""
        w, h = self.width(), self.height()
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.transparent)
        gp = QPainter(pm)
        gp.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = w / 2.0
        cy = h / 2.0
        outer_r = self._size / 2.0
        glow_layers = [(28, 10), (22, 18), (16, 28), (10, 45), (5, 70)]
        gp.setPen(Qt.PenStyle.NoPen)
        for dr, alpha in glow_layers:
            r = outer_r + dr
            grad = QRadialGradient(cx, cy, r)
            grad.setColorAt(0.0, QColor(89, 200, 134, 0))
            inner_stop = (outer_r - 2) / r
            grad.setColorAt(max(0.0, inner_stop), QColor(89, 200, 134, 0))
            grad.setColorAt(min(1.0, inner_stop + 0.05), QColor(89, 200, 134, alpha))
            grad.setColorAt(1.0, QColor(89, 200, 134, 0))
            gp.setBrush(QBrush(grad))
            gp.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        gp.end()
        return pm

    def _build_icon_pixmap(self):
        color = "#59c886" if self._monitoring else "#c1c4c9"
        name = "Stop" if self._monitoring else "Play"
        return _icpx(name, size=28, color=color, stroke_width=1.5)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 위젯 전체 중앙 (glow 여백 포함된 크기)
        cx = self.width() / 2.0
        cy = self.height() / 2.0

        # scale transform
        p.translate(cx, cy)
        p.scale(self._scale, self._scale)
        p.translate(-cx, -cy)

        outer_r = self._size / 2.0   # 토글 원 반지름 60
        margin = self._glow_margin   # 32px glow 여백

        # ── on 상태: 캐시된 glow pixmap + 애니메이션 pulse 링 ──
        if self._monitoring:
            if self._cached_glow is None:
                self._cached_glow = self._build_glow_pixmap()

            t = self._pulse_progress
            # 메인 glow 맥동: 충격 순간(t=0) 밝고 잔향으로 감에 따라 어두워짐
            # ease-in 커브로 묵직하게 떨어짐
            glow_breath = 0.70 + 0.30 * ((1.0 - t) ** 1.5)
            p.setOpacity(glow_breath)
            p.drawPixmap(0, 0, self._cached_glow)
            p.setOpacity(1.0)

            # ── pulse 링: 빠른 확장(attack) + 느긋한 잔향(decay) ──
            if t < 0.22:
                # attack: ease-out cubic, 밝게 등장
                a = t / 0.22
                ae = 1.0 - (1.0 - a) ** 3
                pulse_scale = 0.82 + 0.38 * ae      # 0.82 → 1.20
                alpha_factor = ae                     # 0 → 1
            else:
                # decay: 완만히 계속 확산, 느긋하게 페이드
                d = (t - 0.22) / 0.78
                pulse_scale = 1.20 + 0.50 * d        # 1.20 → 1.70
                alpha_factor = (1.0 - d) ** 1.3      # 잔향이 오래 남도록 ease-out

            pulse_alpha = int(255 * alpha_factor * 0.55)
            if pulse_alpha > 0:
                pulse_pen = QPen(QColor(89, 200, 134, pulse_alpha))
                pulse_pen.setWidth(2)
                p.setPen(pulse_pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                rx = outer_r * pulse_scale
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
        p.drawEllipse(QRectF(cx - outer_r + 1, cy - outer_r + 1,
                             2 * outer_r - 2, 2 * outer_r - 2))

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

        # ── 아이콘 (Play 또는 Stop) — 매 프레임 SVG 파싱 방지 위해 캐싱 ──
        if self._cached_icon is None:
            self._cached_icon = self._build_icon_pixmap()
        p.drawPixmap(int(cx - 14), int(cy - 14), self._cached_icon)

        p.end()
