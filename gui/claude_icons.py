# Claude Design 아이콘 (SVG) → PyQt6 QIcon 변환 유틸리티
"""
handoff 번들의 icons.jsx 에 있는 SVG 패스를 그대로 가져와
런타임에 QIcon으로 만들어 쓴다.

사용:
    from gui.claude_icons import ic, pixmap_icon
    btn.setIcon(ic("Folder", color="#c9ccd3"))
    btn.setIconSize(QSize(16, 16))
"""
from PyQt6.QtCore import QByteArray, Qt, QSize
from PyQt6.QtGui import QIcon, QPixmap, QColor, QPainter
from PyQt6.QtSvg import QSvgRenderer


# icons.jsx에서 추출한 SVG 내부 (path/circle/rect 등)
# 기본: 24x24 viewBox, stroke-width 1.6, fill none
_SVG_SHAPES = {
    "Folder":    '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4l2 2H19.5A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5v-11Z"/>',
    "FolderPlus":'<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4l2 2H19.5A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1 19.5 19h-15A1.5 1.5 0 0 1 3 17.5v-11Z"/><path d="M12 11v5M9.5 13.5h5"/>',
    "File":      '<path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M14 3v5h5"/>',
    "Search":    '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "Play":      '<path d="M7 5v14l12-7L7 5Z" fill="{fill}" stroke="none"/>',
    "Stop":      '<rect x="6" y="6" width="12" height="12" rx="2" fill="{fill}" stroke="none"/>',
    "Refresh":   '<path d="M20 12a8 8 0 1 1-2.3-5.6"/><path d="M20 4v5h-5"/>',
    "Settings":  '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>',
    "Check":     '<path d="m5 12 5 5L20 7"/>',
    "X":         '<path d="M6 6l12 12M18 6 6 18"/>',
    "ArrowDown": '<path d="M12 5v14M5 12l7 7 7-7"/>',
    "ArrowUp":   '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "Home":      '<path d="m3 11 9-8 9 8"/><path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5"/>',
    "Download":  '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 21h14"/>',
    "Upload":    '<path d="M12 21V9M7 14l5-5 5 5"/><path d="M5 3h14"/>',
    "Chevron":   '<path d="m9 6 6 6-6 6"/>',
    "ChevronUp":   '<path d="m6 15 6-6 6 6"/>',
    "ChevronDown": '<path d="m6 9 6 6 6-6"/>',
    "MoreV":     '<circle cx="12" cy="6" r="1.2" fill="{fill}" stroke="none"/><circle cx="12" cy="12" r="1.2" fill="{fill}" stroke="none"/><circle cx="12" cy="18" r="1.2" fill="{fill}" stroke="none"/>',
    "Zap":       '<path d="M13 3 4 14h7l-1 7 9-11h-7l1-7Z"/>',
    "Scan":      '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M3 12h18"/>',
    "Calendar":  '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "Activity":  '<path d="M4 12h3l3-8 4 16 3-8h3"/>',
    "Book":      '<path d="M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4V4Z"/><path d="M4 16a4 4 0 0 1 4-4h12"/>',
    "Cog":       '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    "Sparkles":  '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.5 5.5l2.8 2.8M15.7 15.7l2.8 2.8M18.5 5.5l-2.8 2.8M8.3 15.7l-2.8 2.8"/>',
    "Filter":    '<path d="M3 5h18l-7 9v5l-4 2v-7L3 5Z"/>',
    "Sort":      '<path d="M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4"/>',
    "Plus":      '<path d="M12 5v14M5 12h14"/>',
    "Moon":      '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>',
    "Sun":       '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "Inbox":     '<path d="M3 13l3-8h12l3 8"/><path d="M3 13v6a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6h-6l-2 2h-4l-2-2H3Z"/>',
    "Layers":    '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5M3 18l9 5 9-5"/>',
    "Bolt":      '<path d="m13 2-9 12h7l-1 8 9-12h-7l1-8Z"/>',
    "Merge":     '<path d="M6 3v6a6 6 0 0 0 6 6h6"/><path d="M18 3v6"/><path d="m15 12 3 3 3-3"/>',
    "Split":     '<path d="M6 3v6M6 15v6M18 3v6a6 6 0 0 1-6 6H6"/><path d="m3 6 3-3 3 3"/>',
    "Tag":       '<path d="M7 3h7l7 7-10 10L4 13V6a3 3 0 0 1 3-3Z"/><circle cx="9" cy="9" r="1.2" fill="{fill}" stroke="none"/>',
    "History":   '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3.5 2"/>',
    "Undo":      '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
}


def _svg_for(name: str, color: str = "#c9ccd3", stroke_width: float = 1.6) -> str:
    """지정 색상으로 SVG 문자열 생성."""
    shape = _SVG_SHAPES.get(name)
    if shape is None:
        return ""
    # {fill} 플레이스홀더 처리 (Play/Stop 등 fill 아이콘)
    shape = shape.replace("{fill}", color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="24" height="24" fill="none" stroke="{color}" '
        f'stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-linejoin="round">{shape}</svg>'
    )


def pixmap(name: str, size: int = 16, color: str = "#c9ccd3", stroke_width: float = 1.6) -> QPixmap:
    """이름 + 색상 + 크기로 QPixmap 생성.

    화면 배율(DPI)에 맞춰 실제 픽셀 해상도로 렌더링 — 확대 화면에서도 선명.
    """
    svg_str = _svg_for(name, color, stroke_width)
    if not svg_str:
        return QPixmap()

    # 디바이스 픽셀 비율 (150% 화면 = 1.5) — 흐릿한 업스케일 방지
    dpr = 1.0
    try:
        from PyQt6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if app is not None:
            dpr = max(1.0, float(app.devicePixelRatio()))
    except Exception:
        pass

    renderer = QSvgRenderer(QByteArray(svg_str.encode("utf-8")))
    px = max(1, round(size * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def ic(name: str, size: int = 16, color: str = "#c9ccd3", stroke_width: float = 1.6) -> QIcon:
    """QIcon 반환."""
    return QIcon(pixmap(name, size, color, stroke_width))
