# JARVIS Core - 일정 빠른 입력 파서
"""
"내일 14시 검역 서류 확인" 같은 한 줄 텍스트를 (제목, 일시)로 파싱.

지원 문법:
  날짜: 오늘 / 내일 / 모레 / M월 D일 / M/D / D일 / 요일(월요일~일요일, 다음 발생일)
  시간: 오전·오후 H시[ M분 | 반] / H시[ M분 | 반] / H:MM
  나머지 텍스트 = 제목

기본값 규칙:
  날짜 생략 → base_date(달력에서 선택한 날짜) 또는 오늘
  시간 생략 → 09:00
  날짜를 안 썼는데 시간이 이미 지난 경우 → 다음날로 넘김 ("9시 전화"를 저녁에 입력하면 내일 9시)
"""

import re
import calendar as _cal
from datetime import datetime, date, timedelta

_WEEKDAYS = {
    "월요일": 0, "화요일": 1, "수요일": 2, "목요일": 3,
    "금요일": 4, "토요일": 5, "일요일": 6,
}

RE_TODAY = re.compile(r'(오늘|금일)')
RE_TOMORROW = re.compile(r'내일')
RE_DAY_AFTER = re.compile(r'모레')
RE_MONTH_DAY = re.compile(r'(\d{1,2})\s*월\s*(\d{1,2})\s*일')
RE_SLASH_DATE = re.compile(r'\b(\d{1,2})/(\d{1,2})\b')
RE_DAY_ONLY = re.compile(r'(?<![\d/월시:])\b(\d{1,2})\s*일\b')
RE_WEEKDAY = re.compile(r'(월요일|화요일|수요일|목요일|금요일|토요일|일요일)')

RE_HOUR_MIN = re.compile(r'(오전|오후)?\s*(\d{1,2})\s*시\s*(반|(\d{1,2})\s*분)?')
RE_COLON_TIME = re.compile(r'\b(\d{1,2}):(\d{2})\b')


def _next_weekday(base: date, weekday: int) -> date:
    """base 이후(당일 제외) 가장 가까운 해당 요일"""
    days_ahead = (weekday - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)


def parse_quick_schedule(text: str, base_date: date = None, now: datetime = None,
                         allow_empty_title: bool = False) -> dict:
    """빠른 입력 텍스트 파싱.

    Args:
        allow_empty_title: True면 제목 없이 날짜/시간만 있는 입력("내일 14시")도 허용
                           (편집 팝업의 기한 빠른 지정용). 단 날짜·시간 둘 다 없으면 None.

    Returns:
        {'title': str, 'datetime': datetime, 'date_explicit': bool, 'time_explicit': bool}
        제목이 비면 None (allow_empty_title=False일 때).
    """
    if not text or not text.strip():
        return None
    if now is None:
        now = datetime.now()
    today = now.date()

    remaining = text.strip()
    target_date = None
    date_explicit = False

    # ── 날짜 파싱 (구체적 표현부터) ──
    m = RE_MONTH_DAY.search(remaining)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = today.year
        try:
            cand = date(year, month, day)
            # 이미 두 달 이상 지난 날짜면 내년으로 해석
            if cand < today - timedelta(days=60):
                cand = date(year + 1, month, day)
            target_date = cand
            date_explicit = True
            remaining = RE_MONTH_DAY.sub(' ', remaining, count=1)
        except ValueError:
            pass

    if target_date is None:
        m = RE_SLASH_DATE.search(remaining)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            try:
                cand = date(today.year, month, day)
                if cand < today - timedelta(days=60):
                    cand = date(today.year + 1, month, day)
                target_date = cand
                date_explicit = True
                remaining = RE_SLASH_DATE.sub(' ', remaining, count=1)
            except ValueError:
                pass

    if target_date is None and RE_DAY_AFTER.search(remaining):
        target_date = today + timedelta(days=2)
        date_explicit = True
        remaining = RE_DAY_AFTER.sub(' ', remaining, count=1)

    if target_date is None and RE_TOMORROW.search(remaining):
        target_date = today + timedelta(days=1)
        date_explicit = True
        remaining = RE_TOMORROW.sub(' ', remaining, count=1)

    if target_date is None:
        m = RE_TODAY.search(remaining)
        if m:
            target_date = today
            date_explicit = True
            remaining = RE_TODAY.sub(' ', remaining, count=1)

    if target_date is None:
        m = RE_WEEKDAY.search(remaining)
        if m:
            target_date = _next_weekday(today, _WEEKDAYS[m.group(1)])
            date_explicit = True
            remaining = RE_WEEKDAY.sub(' ', remaining, count=1)

    if target_date is None:
        m = RE_DAY_ONLY.search(remaining)
        if m:
            day = int(m.group(1))
            max_day = _cal.monthrange(today.year, today.month)[1]
            if 1 <= day <= max_day:
                cand = date(today.year, today.month, day)
                # 이미 지난 날이면 다음 달의 그 날로
                if cand < today:
                    ny, nm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
                    day2 = min(day, _cal.monthrange(ny, nm)[1])
                    cand = date(ny, nm, day2)
                target_date = cand
                date_explicit = True
                remaining = RE_DAY_ONLY.sub(' ', remaining, count=1)

    # ── 시간 파싱 ──
    hour, minute = None, 0
    time_explicit = False

    m = RE_COLON_TIME.search(remaining)
    if m and 0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59:
        hour, minute = int(m.group(1)), int(m.group(2))
        time_explicit = True
        remaining = RE_COLON_TIME.sub(' ', remaining, count=1)
    else:
        m = RE_HOUR_MIN.search(remaining)
        if m and 0 <= int(m.group(2)) <= 24:
            ampm = m.group(1)
            hour = int(m.group(2))
            if m.group(3):
                if m.group(3) == '반':
                    minute = 30
                elif m.group(4):
                    minute = int(m.group(4))
            if ampm == '오후' and hour < 12:
                hour += 12
            elif ampm == '오전' and hour == 12:
                hour = 0
            if hour == 24:
                hour = 0
            time_explicit = True
            remaining = RE_HOUR_MIN.sub(' ', remaining, count=1)

    # ── 기본값 적용 ──
    if target_date is None:
        target_date = base_date if base_date else today
    if hour is None:
        hour, minute = 9, 0

    dt = datetime(target_date.year, target_date.month, target_date.day, hour, minute)

    # 날짜를 안 썼는데 시간이 이미 지난 경우 → 다음날 (base_date가 오늘이거나 미지정일 때만)
    if not date_explicit and dt <= now and (base_date is None or base_date == today):
        dt += timedelta(days=1)

    title = re.sub(r'\s+', ' ', remaining).strip()
    if not title:
        if not (allow_empty_title and (date_explicit or time_explicit)):
            return None

    return {
        'title': title,
        'datetime': dt,
        'date_explicit': date_explicit,
        'time_explicit': time_explicit,
    }
