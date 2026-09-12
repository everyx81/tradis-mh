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

    # 보더 — 불투명 (반투명 보더는 둥근 모서리 이음새가 점으로 도드라짐)
    # 기존 rgba 값을 배경(bg_1~bg_2)과 미리 합성한 근사치
    "border_soft":   "#23262d",   # rgba(45,48,56,150) over bg_1
    "border":        "#343740",   # rgba(63,66,75,180) over bg_2
    "border_strong": "#484b54",

    # 전경(텍스트) — 브라우저 oklch 렌더와 매치되도록 sRGB 범위에서 톤업
    "fg_0": "#f8fafc",      # primary  (oklch 0.97) — 거의 white, 선명
    "fg_1": "#d5d9df",      # secondary (oklch 0.82) — 살짝 밝게
    "fg_2": "#9ea1a8",      # tertiary  (oklch 0.66)
    "fg_3": "#6a6e76",      # muted    (oklch 0.5)

    # 액센트 (블루)
    "accent":        "#4ba3f7",   # oklch 0.7 0.15 250
    "accent_hi":     "#5ebdff",   # oklch 0.78
    "accent_lo":     "#3284d0",   # oklch 0.6
    "accent_bg":     "rgba(75, 163, 247, 36)",
    "accent_border": "#2c4d6e",   # rgba(75,163,247,90) over bg_2 — 불투명 (모서리 점 방지)

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
