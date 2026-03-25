# JARVIS Core - 유틸리티 함수
"""
공통 유틸리티 함수 및 정규식 패턴
"""

import os
import re
import socket
import threading
from typing import Optional, Tuple

from .constants import PORT

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
RE_DOC_TYPES_PIPE = "|".join(["정산서", "자금정산서", "수입신고필증", "납부고지서", "수입세금계산서", "통관수수료계산서", "수출신고필증", "자금청구서"])
RE_DOC_MATCH = re.compile(fr'\(.*\)({RE_DOC_TYPES_PIPE})')

RE_TAX_PAYER = re.compile(r'납\s*세\s*의\s*무\s*자')
RE_SHIPPER = re.compile(r'실\s*화\s*주')
RE_BIZ_ID = re.compile(r'\s*\d{3}-\d{2}-\d{5}')
RE_BUSINESS_ID_OR_NUM = re.compile(r'\s*\d+')
RE_상호 = re.compile(r'\(\s*상\s*호\s*\)')
RE_수출화주 = re.compile(r'수\s*출\s*화\s*주')
RE_송품장부호 = re.compile(r'송품장부호')
RE_BL_IV_NO = re.compile(r'B/L\s*I/V\s*No', re.IGNORECASE)


def normalize_id(identifier: str) -> str:
    """ID 비교용 정규화 (OCR 혼동 문자 통일: O→0, I→1)"""
    return identifier.replace(" ", "").upper().replace("O", "0").replace("I", "1")


def is_similar_id(id1: str, id2: str, threshold: float = 0.75) -> bool:
    """두 ID가 유사한지 판단 (OCR 오인식 대응)
    
    영문 접두어는 유사도 매칭, 숫자 접미어는 완전 일치 필수.
    예: SNLGSKKLN90606 vs SNLGSKKLIN90606 → 같은 건 (숫자 동일, 접두어 유사)
        HDMU12340001 vs HDMU12340002 → 다른 건 (숫자 다름)
    """
    from difflib import SequenceMatcher
    n1, n2 = normalize_id(id1), normalize_id(id2)
    if n1 == n2:
        return True
    
    # 영문 접두어와 숫자 접미어 분리
    def split_id(s):
        # 끝에서부터 연속된 숫자를 접미어로 분리
        i = len(s)
        while i > 0 and s[i-1].isdigit():
            i -= 1
        return s[:i], s[i:]
    
    prefix1, suffix1 = split_id(n1)
    prefix2, suffix2 = split_id(n2)
    
    # 숫자 접미어가 다르면 다른 ID (연번 B/L 보호)
    if suffix1 != suffix2:
        return False
    
    # 접두어가 없으면 (순수 숫자 ID) 완전 일치만 허용
    if not prefix1 or not prefix2:
        return n1 == n2
    
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


def parse_renamed_filename(filename: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    이름 변경된 파일명 파싱
    Returns: (company, identifier, doc_type, suffix)
    """
    if not filename.lower().endswith('.pdf'):
        return None, None, None, None
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
    return company, identifier, doc_type, suffix
