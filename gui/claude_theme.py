# Claude Design — warm dark theme (Arc/Notion inspired)
"""
TRADIS MH를 Claude Design 시안에 맞춰 리디자인하기 위한 테마 상수.
원본 디자인의 oklch 값을 sRGB로 근사 변환했다.

- 기존 styles.py(JARVIS 네온 시안)와 공존한다.
- Phase별로 위젯이 이 팔레트를 사용하도록 점진 이관한다.
"""

# ============================================================
# COLOR PALETTE (oklch → sRGB 근사치)
# ============================================================
C = {
    # 배경 (oklch → sRGB 정확 변환, 어두운 → 밝은 순)
    "bg_0": "#0d0f15",      # 최외곽 (oklch 0.17 0.012 265)
    "bg_1": "#14171d",      # 패널    (oklch 0.205)
    "bg_2": "#1b1e24",      # 카드    (oklch 0.235)
    "bg_3": "#23262d",      # 엘리베이티드 (oklch 0.27)
    "bg_4": "#2d3038",      # 호버    (oklch 0.31)

    # 보더
    "border_soft":   "rgba(45, 48, 56, 150)",
    "border":        "rgba(63, 66, 75, 180)",
    "border_strong": "#484b54",

    # 전경(텍스트)
    "fg_0": "#f3f5f9",      # primary  (oklch 0.97)
    "fg_1": "#c1c4c9",      # secondary (oklch 0.82)
    "fg_2": "#8f9298",      # tertiary  (oklch 0.66)
    "fg_3": "#5f636a",      # muted    (oklch 0.5)

    # 액센트 (블루)
    "accent":        "#4ba3f7",   # oklch 0.7 0.15 250
    "accent_hi":     "#5ebdff",   # oklch 0.78
    "accent_lo":     "#3284d0",   # oklch 0.6
    "accent_bg":     "rgba(75, 163, 247, 36)",
    "accent_border": "rgba(75, 163, 247, 90)",

    # 상태
    "green":  "#59c886",     # oklch 0.75 0.14 155
    "amber":  "#e9ab2b",     # oklch 0.78 0.15 80
    "red":    "#fa6863",     # oklch 0.7 0.18 25
    "purple": "#b48df4",     # oklch 0.72 0.15 300

    # 로그 배경(더 어두움)
    "logs_bg": "#07090e",    # oklch 0.14

    # 트래픽 라이트 (macOS)
    "tl_close": "#ff5f57",
    "tl_min":   "#febc2e",
    "tl_max":   "#28c840",
}

# ============================================================
# FONTS — 시스템 폰트 fallback
# ============================================================
FONT_UI   = "'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif"
FONT_MONO = "'JetBrains Mono', 'Consolas', 'D2Coding', monospace"

# ============================================================
# RADIUS
# ============================================================
R_SM = 6
R_MD = 10
R_LG = 14
R_XL = 18


# ============================================================
# BASE APP STYLESHEET
# ============================================================
APP_STYLESHEET = f"""
QWidget {{
    background-color: {C["bg_0"]};
    color: {C["fg_0"]};
    font-family: {FONT_UI};
    font-size: 10pt;
}}

QToolTip {{
    background-color: {C["bg_3"]};
    color: {C["fg_0"]};
    border: 1px solid {C["border"]};
    border-radius: 6px;
    padding: 6px 10px;
    font-family: {FONT_UI};
    font-size: 9pt;
}}

/* 스크롤바 — 얇고 조용하게 */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C["border"]};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C["border_strong"]};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    background: transparent;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {C["border"]};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {C["border_strong"]};
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
    background: transparent;
}}
"""

# ============================================================
# 버튼 스타일 (default / primary / ghost / danger-ghost)
# ============================================================
BTN_DEFAULT = f"""
QPushButton {{
    background-color: {C["bg_2"]};
    color: {C["fg_1"]};
    border: 1px solid {C["border_soft"]};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 9.5pt;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {C["bg_3"]};
    color: {C["fg_0"]};
    border: 1px solid {C["border"]};
}}
QPushButton:pressed {{
    background-color: {C["bg_4"]};
}}
QPushButton:disabled {{
    color: {C["fg_3"]};
    background-color: {C["bg_1"]};
}}
"""

BTN_PRIMARY = f"""
QPushButton {{
    background-color: {C["accent"]};
    color: #ffffff;
    border: 1px solid {C["accent_hi"]};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 9.5pt;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: {C["accent_hi"]};
}}
QPushButton:pressed {{
    background-color: {C["accent_lo"]};
}}
QPushButton:disabled {{
    background-color: {C["bg_2"]};
    color: {C["fg_3"]};
    border: 1px solid {C["border_soft"]};
}}
"""

BTN_GHOST = f"""
QPushButton {{
    background-color: transparent;
    color: {C["fg_2"]};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 9.5pt;
}}
QPushButton:hover {{
    background-color: {C["bg_3"]};
    color: {C["fg_0"]};
}}
"""

BTN_DANGER_GHOST = f"""
QPushButton {{
    background-color: transparent;
    color: {C["red"]};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 9.5pt;
}}
QPushButton:hover {{
    background-color: rgba(228, 113, 95, 30);
}}
"""

# ============================================================
# 입력 필드
# ============================================================
INPUT_STYLE = f"""
QLineEdit {{
    background-color: {C["bg_2"]};
    color: {C["fg_0"]};
    border: 1px solid {C["border_soft"]};
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 10pt;
    selection-background-color: {C["accent_bg"]};
}}
QLineEdit:focus {{
    border: 1px solid {C["accent_border"]};
}}
QLineEdit::placeholder {{
    color: {C["fg_3"]};
}}
"""

# ============================================================
# 카드(section-card)
# ============================================================
CARD_STYLE = f"""
QFrame#sectionCard {{
    background-color: {C["bg_2"]};
    border: 1px solid {C["border_soft"]};
    border-radius: 12px;
}}
"""

# ============================================================
# 리스트 (폴더 행)
# ============================================================
LIST_STYLE = f"""
QListWidget {{
    background-color: transparent;
    border: none;
    outline: 0;
    font-family: {FONT_MONO};
    font-size: 9.5pt;
    color: {C["fg_1"]};
}}
QListWidget::item {{
    padding: 7px 10px;
    border-radius: 8px;
    margin: 1px 0;
}}
QListWidget::item:hover {{
    background-color: {C["bg_3"]};
    color: {C["fg_0"]};
}}
QListWidget::item:selected {{
    background-color: {C["accent_bg"]};
    color: {C["fg_0"]};
    border: 1px solid {C["accent_border"]};
}}
"""

# ============================================================
# 상태 뱃지 / 칩
# ============================================================
CHIP_STYLE = f"""
QPushButton#chip {{
    background-color: {C["bg_2"]};
    color: {C["fg_1"]};
    border: 1px solid {C["border_soft"]};
    border-radius: 999px;
    padding: 4px 11px;
    font-size: 9pt;
    font-weight: 500;
}}
QPushButton#chip:hover {{
    background-color: {C["bg_3"]};
    color: {C["fg_0"]};
}}
QPushButton#chip:checked {{
    background-color: {C["accent_bg"]};
    border: 1px solid {C["accent_border"]};
    color: {C["accent_hi"]};
}}
"""

# ============================================================
# 세로 NAV 탭 (right-side rail)
# ============================================================
SIDE_TAB_STYLE = f"""
QPushButton#sideTab {{
    background-color: transparent;
    color: {C["fg_2"]};
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 10px 4px;
    font-size: 9.5pt;
    font-weight: 600;
    text-align: center;
}}
QPushButton#sideTab:hover {{
    background-color: {C["bg_2"]};
    color: {C["fg_0"]};
    border: 1px solid {C["border_soft"]};
}}
QPushButton#sideTab:checked {{
    background-color: {C["accent_bg"]};
    color: {C["accent_hi"]};
    border: 1px solid {C["accent_border"]};
}}
"""
