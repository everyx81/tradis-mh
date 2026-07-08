# JARVIS Core - 유틸리티 함수
"""
공통 유틸리티 함수 및 정규식 패턴
"""

import os
import re
import socket
import threading
from typing import Optional, Tuple

from .constants import PORT, STANDARD_DOC_TYPES, DOC_TYPE_ALIAS


def normalize_doc_type(raw):
    """OCR/파일명에서 추출된 doc_type을 표준 서류 이름으로 정규화.

    처리 순서:
      1. 빈/Unknown은 그대로 반환
      2. 공백 정리
      3. 표준 목록에 있으면 그대로
      4. ALIAS 매핑 적용
      5. 끝 괄호 부가설명 제거 후 표준/ALIAS 재시도
      6. 모두 실패하면 원본 반환
    """
    if not raw or raw == "Unknown":
        return raw

    cleaned = str(raw).strip()

    # 1차: 그대로 매칭
    if cleaned in STANDARD_DOC_TYPES:
        return cleaned
    if cleaned in DOC_TYPE_ALIAS:
        return DOC_TYPE_ALIAS[cleaned]

    # 2차: 끝 괄호 부가설명 제거 ("자금정산서 (수입)" → "자금정산서")
    no_paren = re.sub(r'\s*\([^)]*\)\s*$', '', cleaned).strip()
    if no_paren != cleaned:
        if no_paren in STANDARD_DOC_TYPES:
            return no_paren
        if no_paren in DOC_TYPE_ALIAS:
            return DOC_TYPE_ALIAS[no_paren]

    # 3차: 공백 제거 후 매칭 시도
    no_space = cleaned.replace(" ", "")
    if no_space in STANDARD_DOC_TYPES:
        return no_space
    if no_space in DOC_TYPE_ALIAS:
        return DOC_TYPE_ALIAS[no_space]

    # 표준에도 ALIAS에도 없으면 원본 유지
    return cleaned

# --- Thread Locks ---
pdf_lock = threading.Lock()
cache_lock = threading.Lock()  # 캐시 파일 쓰기 락

# --- Regex Patterns (Compiled for Performance) ---
RE_COMPANY_CLEAN_1 = re.compile(r'\(\s*주\s*\)')
RE_COMPANY_CLEAN_2 = re.compile(r'주\s*식\s*회\s*사')
RE_COMPANY_CLEAN_3 = re.compile(r'[\(（]\s*주\s*[\)）]')
RE_COMPANY_KOREAN = re.compile(r'[가-힣]')
RE_COMPANY_SPLIT = re.compile(r'([가-힣\s]+?)([\s\(]*[a-zA-Z])')

RE_BL_GENERAL = re.compile(r'B/L\s*(No|NO|번호)?[\s.:]*([A-Za-z0-9_\-\(\) \t]+)', re.IGNORECASE)
RE_INV_GENERAL = re.compile(r'(Invoice|P/O|Ref|송품장)\s*(No|NO|번호|부호)?[\s.:]*([A-Za-z0-9_\-\(\)]+(?:\s*[A-Za-z0-9_\-\(\)]+)*)', re.IGNORECASE)

# File pattern for renamed files: Company(ID)DocType.pdf
RE_FILE_PATTERN = re.compile(r'^.+?\(.+?\).+?\.pdf$')
RE_INVALID_CHARS = re.compile(r'[\\/*?:"<>|]')
RE_ID_PAREN = re.compile(r'\(([^()]+)\)')
RE_DOC_TYPES_PIPE = "|".join(["정산서", "자금정산서", "수입신고필증", "납부고지서", "수입세금계산서", "통관수수료계산서", "수출신고필증", "반송신고필증", "자금청구서"])
RE_DOC_MATCH = re.compile(fr'\(.*\)({RE_DOC_TYPES_PIPE})')

RE_TAX_PAYER = re.compile(r'납\s*세\s*의\s*무\s*자')
RE_SHIPPER = re.compile(r'실\s*화\s*주')
RE_BIZ_ID = re.compile(r'\s*\d{3}-\d{2}-\d{5}')
RE_BUSINESS_ID_OR_NUM = re.compile(r'\s*\d+')
RE_상호 = re.compile(r'\(\s*상\s*호\s*\)')
RE_수출화주 = re.compile(r'수\s*출\s*화\s*주')
RE_송품장부호 = re.compile(r'송품장부호')
RE_BL_IV_NO = re.compile(r'B/L\s*I/V\s*No', re.IGNORECASE)


# --- 한글 자모 분해 (OCR 회사명 유사도 비교용) ---
_CHOSUNG = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
_JUNGSUNG = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
_JONGSUNG = ('', 'ㄱ','ㄲ','ㄳ','ㄴ','ㄵ','ㄶ','ㄷ','ㄹ','ㄺ','ㄻ','ㄼ','ㄽ','ㄾ','ㄿ','ㅀ',
             'ㅁ','ㅂ','ㅄ','ㅅ','ㅆ','ㅇ','ㅈ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ')


def decompose_hangul(text: str) -> str:
    """한글을 초성/중성/종성으로 분해. 영문/숫자는 그대로 유지."""
    result = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            result.append(_CHOSUNG[code // 588])
            result.append(_JUNGSUNG[(code % 588) // 28])
            jong = code % 28
            if jong > 0:
                result.append(_JONGSUNG[jong])
        else:
            result.append(ch)
    return ''.join(result)


def company_name_similarity(a: str, b: str) -> float:
    """자모 분해 기반 회사명 유사도 (0.0 ~ 1.0)"""
    from difflib import SequenceMatcher
    a = a.replace("★", "").replace(" ", "").strip()
    b = b.replace("★", "").replace(" ", "").strip()
    if not a or not b:
        return 0.0
    # 길이 차이 30% 이상이면 빠른 제외
    if abs(len(a) - len(b)) / max(len(a), len(b)) > 0.3:
        return 0.0
    da = decompose_hangul(a.upper())
    db = decompose_hangul(b.upper())
    return SequenceMatcher(None, da, db).ratio()


def normalize_id(identifier: str) -> str:
    """ID 비교용 정규화 (OCR 혼동 문자 통일: O→0, I→1)"""
    return identifier.replace(" ", "").upper().replace("O", "0").replace("I", "1")


def is_prefix_match_id(id1: str, id2: str) -> bool:
    """한쪽이 다른쪽의 prefix인지 판단 (suffix 1글자 차이만 허용)

    예: COHEAR597YN074 vs COHEAR597YN074A → True  (숫자 뒤 영문 1글자 차이)
        COHEAR597YN074A vs COHEAR597YN074AB → False (영문 뒤 영문 → 합산BL, 별건)
        COHEAR597YN074 vs COHEAR597YN999 → False (다른 번호)
    """
    n1, n2 = normalize_id(id1), normalize_id(id2)
    if n1 == n2:
        return True
    # 짧은 쪽이 긴 쪽의 prefix이고, 차이가 영문 1글자(연번 suffix)인 경우만 허용
    short, long = (n1, n2) if len(n1) <= len(n2) else (n2, n1)
    if long.startswith(short) and len(long) - len(short) == 1 and long[-1].isalpha():
        # 짧은 쪽이 숫자로 끝나야 함 (074 → 074A ✓, 074A → 074AB ✗)
        if short and short[-1].isdigit():
            return True
    return False


def is_similar_id(id1: str, id2: str, threshold: float = 0.75) -> bool:
    """두 ID가 유사한지 판단 (OCR 오인식 대응)

    영문 접두어는 유사도 매칭, 숫자 접미어는 완전 일치 필수.
    예: SNLGSKKLN90606 vs SNLGSKKLIN90606 → 같은 건 (숫자 동일, 접두어 유사)
        HDMU12340001 vs HDMU12340002 → 다른 건 (숫자 다름)
        2324117007 vs OOLU2324117007 → 같은 건 (숫자 부분 동일, 선사코드 누락)
    """
    from difflib import SequenceMatcher
    # normalize 전 원본으로 선사코드 누락 체크 (O→0 치환 전)
    u1, u2 = id1.replace(" ", "").upper(), id2.replace(" ", "").upper()
    if u1 == u2:
        return True

    # 하이픈 구분 ID (예: B260424-1, INVOICE-001 등) — 각 세그먼트 정확 일치 필수
    # prefix 유사도 매칭에 현혹되어 다른 날짜 BL 이 같은 그룹에 묶이는 문제 방지
    # (예: B260420-1 vs B260424-1 은 prefix 87.5% 유사하지만 다른 건)
    if '-' in u1 or '-' in u2:
        n1_hy = normalize_id(id1)
        n2_hy = normalize_id(id2)
        parts1 = n1_hy.split('-')
        parts2 = n2_hy.split('-')
        if len(parts1) != len(parts2):
            return False
        return all(p1 == p2 for p1, p2 in zip(parts1, parts2))

    # 한쪽이 순수 숫자이고, 다른 쪽이 영문+숫자이며 숫자 부분이 일치하면 같은 BL
    if u1.isdigit() or u2.isdigit():
        num_only, full = (u1, u2) if u1.isdigit() else (u2, u1)
        # full에서 숫자 부분 추출
        import re
        full_digits = re.sub(r'[^0-9]', '', full)
        if full_digits == num_only and len(num_only) >= 6:
            return True

    n1, n2 = normalize_id(id1), normalize_id(id2)
    if n1 == n2:
        return True
    
    # 영문 접두어와 숫자/영문 접미어 분리
    def split_id(s):
        # 끝에서부터 연속된 숫자를 접미어로 분리
        i = len(s)
        while i > 0 and s[i-1].isdigit():
            i -= 1
        # 숫자 접미어가 없고 끝 1글자가 영문이면 연번(A/B/C)으로 간주
        # 단, 바로 앞 글자가 숫자일 때만 (074C → suffix C, 074ABC → suffix 아님)
        if i == len(s) and len(s) >= 2 and s[-1].isalpha() and s[-2].isdigit():
            return s[:-1], s[-1]
        return s[:i], s[i:]
    
    prefix1, suffix1 = split_id(n1)
    prefix2, suffix2 = split_id(n2)

    # 숫자 접미어가 다르면 다른 ID (연번 B/L 보호)
    if suffix1 != suffix2:
        return False

    # 접두어가 없으면 (순수 숫자 ID) 완전 일치만 허용
    if not prefix1 or not prefix2:
        return n1 == n2

    # 숫자열 완전 일치 필수 — 유사도 허용은 영문 오인식(I/L 누락 등)만.
    # 연번 문자로 끝나는 ID 는 숫자 전체가 접두어로 분리되므로 이 검사가 없으면
    # GSPC26024E852A vs GSPC26025E853A (다른 필증) 가 유사도 84%로 같은 건 처리됨.
    # 정규화(O→0, I→1)가 영문 오인식을 숫자로 바꿀 수 있으므로
    # 원본/정규화 중 한쪽이라도 숫자열이 일치하면 통과.
    import re as _re
    _digits = lambda s: _re.sub(r'[^0-9]', '', s)
    if _digits(u1) != _digits(u2) and _digits(n1) != _digits(n2):
        return False

    # 영문열 비교 — 숫자가 같아도 선사코드가 명백히 다르면 다른 건
    # (MAEU267065552A vs HDMU267065552A). 한쪽이 영문 없는 경우(선사코드 누락)는 허용.
    letters1 = _re.sub(r'[^A-Z]', '', prefix1)
    letters2 = _re.sub(r'[^A-Z]', '', prefix2)
    if letters1 and letters2 and letters1 != letters2:
        if SequenceMatcher(None, letters1, letters2).ratio() < threshold:
            return False

    # 접두어 유사도 비교
    if abs(len(prefix1) - len(prefix2)) > 3:
        return False
    return SequenceMatcher(None, prefix1, prefix2).ratio() >= threshold


def sanitize_filename(name: str) -> str:
    """파일명에서 유효하지 않은 문자 제거"""
    return RE_INVALID_CHARS.sub("", name).strip()


def get_unique_filename(filename: str) -> str:
    """Generate a unique filename by appending (1), (2), etc. if it exists."""
    if not os.path.exists(filename):
        return filename
    base, e = os.path.splitext(filename)
    counter = 1
    new_filename = f"{base}({counter}){e}"
    while os.path.exists(new_filename):
        counter += 1
        new_filename = f"{base}({counter}){e}"
    return new_filename


def check_single_instance() -> Optional[socket.socket]:
    """Prevent multiple instances using a socket bind."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', PORT))
        return sock
    except socket.error:
        print("\n" + "="*60)
        print(" [오류] 프로그램이 이미 실행 중입니다!")
        print(" TRADIS MH는 한 번에 하나만 실행할 수 있습니다.")
        print("="*60 + "\n")
        return None


def cleanup_company_name(name: str) -> str:
    """회사명 정리 (주식회사, (주) 등 제거)"""
    name = RE_COMPANY_CLEAN_1.sub('', name)
    name = RE_COMPANY_CLEAN_2.sub('', name)
    name = RE_COMPANY_CLEAN_3.sub('', name)
    name = name.strip()
    if RE_COMPANY_KOREAN.search(name):
        match = RE_COMPANY_SPLIT.search(name)
        if match:
            name = match.group(1).strip()
            name = name.rstrip('(').strip()
    cutoff_keywords = ["정산담당", "담당자", " T ", " F ", "TEL", "FAX"]
    for kw in cutoff_keywords:
        if kw in name:
            name = name.split(kw)[0].strip()
    return name.replace(" ", "").replace("_", "").replace("★", "")


def extract_text(file_path: str) -> str:
    """PDF에서 텍스트 추출"""
    import pdfplumber  # lazy import — 시작 시 로딩 방지
    text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                content = page.extract_text()
                if content:
                    text += content + "\n"
    except Exception as e:
        print(f"텍스트 추출 오류: {e}")
    return text


def _parse_by_custom_pattern(filename: str, pattern: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """커스텀 패턴으로 파일명 파싱. 패턴의 {company},{bl},{doctype}을 정규식 그룹으로 변환."""
    import re as _re
    if not filename.lower().endswith('.pdf'):
        return None, None, None, None
    name = filename[:-4]  # .pdf 제거
    pat_body = pattern
    if pat_body.lower().endswith('.pdf'):
        pat_body = pat_body[:-4]
    # 패턴을 정규식으로 변환: {company} → (?P<company>.+?), {bl} → (?P<bl>[A-Za-z0-9_\-]+)
    regex_pat = _re.escape(pat_body)
    regex_pat = regex_pat.replace(r'\{company\}', '(?P<company>.+?)')
    regex_pat = regex_pat.replace(r'\{bl\}', r'(?P<bl>[A-Za-z0-9_\-]+)')
    regex_pat = regex_pat.replace(r'\{doctype\}', '(?P<doctype>.+?)')
    regex_pat = regex_pat.replace(r'\{amount\}', '(?P<amount>.*?)')
    regex_pat = '^' + regex_pat + '$'
    m = _re.match(regex_pat, name)
    if m:
        dt = m.group('doctype')
        if dt:
            dt = normalize_doc_type(dt)
        return m.group('company'), m.group('bl'), dt, None
    return None, None, None, None


def parse_renamed_filename(filename: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    이름 변경된 파일명 파싱 (기본 패턴 + 커스텀 패턴 지원)
    Returns: (company, identifier, doc_type, suffix)
    """
    if not filename.lower().endswith('.pdf'):
        return None, None, None, None

    # 커스텀 패턴 파싱 시도 (괄호 없는 패턴 대응)
    try:
        from core.config import get_custom_naming, DEFAULT_FILE_PATTERN
        custom = get_custom_naming()
        pat = custom.get("file_pattern", DEFAULT_FILE_PATTERN)
        if pat != DEFAULT_FILE_PATTERN:
            parsed = _parse_by_custom_pattern(filename, pat)
            if parsed and parsed[1]:  # identifier가 있으면 성공
                return parsed
    except Exception:
        pass

    # 기본 패턴 파싱
    if not RE_FILE_PATTERN.match(filename):
        return None, None, None, None
    all_parens = list(RE_ID_PAREN.finditer(filename))
    if not all_parens:
        return None, None, None, None
    best_match = None
    for m in reversed(all_parens):
        content = m.group(1).strip()
        if re.match(r'^[A-Za-z0-9_\-]+$', content):
            if re.match(r'^\d+$', content):
                remaining_after = filename[m.end():]
                if remaining_after == ".pdf" or remaining_after == "":
                    continue
            best_match = m
            break
    if not best_match:
        best_match = all_parens[-1]
    start_idx, end_idx = best_match.span()
    identifier = best_match.group(1).strip()
    company = filename[:start_idx].strip()
    remaining = filename[end_idx:-4].strip()
    suffix = None
    suffix_match = re.search(r'\(\d+\)$', filename[:-4])
    if suffix_match and suffix_match.start() >= end_idx:
        suffix = suffix_match.group(0)
        doc_type = filename[end_idx : suffix_match.start()].strip()
    else:
        doc_type = remaining
    # doc_type 표준 정규화 (기존 파일명에 "자금정산서 (수입)" 같은 변형이 있어도 통일)
    doc_type = normalize_doc_type(doc_type) if doc_type else doc_type
    return company, identifier, doc_type, suffix
