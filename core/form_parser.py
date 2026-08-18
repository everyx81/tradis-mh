# JARVIS Core - 표준 서식 직독 파서
"""
관세청 표준 서식(납부고지서, 수입세금계산서)의 텍스트 레이어 직독 파서.

이 서류들은 UNI-PASS 전산 출력물이라 텍스트 레이어가 완전하다.
AI 이미지 인식은 상호/성명 라벨-값 짝짓기를 틀릴 수 있으므로
(대표자 성명이 로마자인 경우 성명을 상호로 오독한 사례),
구조 마커가 모두 일치하고 상호·BL 파싱까지 성공한 경우에만 확정 결과를 반환한다.
실패하면 None을 반환해 기존 AI OCR 경로로 폴백한다 (fail-open).
"""

import re

from .utils import pdf_lock, cleanup_company_name

# 납부고지서
RE_NOTICE_BL = re.compile(r'B/L\s*[:：]\s*([A-Z0-9\-]+)', re.IGNORECASE)
RE_NOTICE_BIZ = re.compile(r'사업자번호\s*[:：]\s*(\d{3}-\d{2}-\d{5})')
RE_NOTICE_TOTAL = re.compile(r'수입징수관\s*\n\s*([\d,]+)\s*\n')
RE_DECL_NO = re.compile(r'[\d\-]+[A-Z]?')  # 신고번호 (예: 13133-26-001733M)

# 수입세금계산서
RE_TAXINV_BL = re.compile(r'B/L\s*NO\s*[:：]?\s*([A-Z0-9\-]+)', re.IGNORECASE)
RE_TAXINV_COMPANY = re.compile(r'상\s{0,6}호\s*\n(.+)')
RE_TAXINV_BIZ = re.compile(r'등록번호\s*\n\s*(\d{3}-\d{2}-\d{5})')
RE_DIGIT_BOX = re.compile(r'(?:\d ){5,}\d')  # 자릿수 박스 행 (예: "1 1 8 5 8 2 9 0")


def _first_page_text(fp):
    import fitz  # lazy import — 시작 시 로딩 방지
    with pdf_lock:
        doc = fitz.open(fp)
        try:
            return doc[0].get_text()
        finally:
            doc.close()


def _parse_notice(t):
    """납부고지서(납부서). 상호는 하단 납부자 블록에 있다
    (상단 '상 호' 라벨 옆은 비어 있고 '(대표자)성명'이 인접 — AI 오독 지점)."""
    if not ('수입징수관' in t and '납기내' in t and '관세청소관' in t):
        return None

    bl = RE_NOTICE_BL.search(t)
    if not bl:
        return None

    # 납부자 블록: '납 부 자' 라벨 뒤 신고번호/세관명 라인을 건너뛴 첫 유효 라인이 상호
    comp = ""
    m = re.search(r'납\s*부\s*자\s*\n(.{0,150})', t, re.DOTALL)
    if m:
        for line in m.group(1).split('\n'):
            line = line.strip()
            if not line:
                continue
            if RE_DECL_NO.fullmatch(line):  # 신고번호
                continue
            if line.endswith('세관'):
                continue
            comp = line
            break
    comp = cleanup_company_name(comp)
    if not comp:
        return None

    totals = RE_NOTICE_TOTAL.findall(t)
    total = int(totals[-1].replace(',', '')) if totals else 0
    biz = RE_NOTICE_BIZ.search(t)

    return {
        'doc_type': '납부고지서',
        'company_name': comp,
        'identifier': bl.group(1).upper(),
        'id_type': 'BL',
        'total_amount': total,
        'product_name': '',
        'supplier_name': '',
        'billing_items': [],
        'supplier_business_no': 'Unknown',
        'buyer_business_no': biz.group(1) if biz else 'Unknown',
        'parsed_by': 'form_parser',
    }


def _parse_import_tax_invoice(t):
    """수입세금계산서/수입계산서(면세). 수입자 블록의 '상 호' 라벨 다음 줄이 상호."""
    tt = t.replace(' ', '').replace('\n', '')
    has_title = '수입세금계산서' in tt or '수입계산서' in tt
    if not (has_title and '보관용' in tt and '세관명' in tt and '과세표준' in tt):
        return None

    bl = RE_TAXINV_BL.search(t)
    if not bl:
        return None

    m = RE_TAXINV_COMPANY.search(t)
    comp = cleanup_company_name(m.group(1).strip()) if m else ""
    if not comp:
        return None

    # 등록번호는 [세관, 수입자] 순 — 수입자는 마지막
    bizs = RE_TAXINV_BIZ.findall(t)
    supplier_biz = bizs[0] if len(bizs) > 1 else 'Unknown'
    buyer_biz = bizs[-1] if bizs else 'Unknown'

    # 자릿수 박스 행: [과세표준, 세액] 2행이면 1/10 관계 검증 후 세액,
    # 1행(면세 수입계산서)이면 그 값, 그 외(일괄발급 등)는 0으로 보수적 처리
    rows = []
    for line in t.split('\n'):
        s = line.strip()
        if RE_DIGIT_BOX.fullmatch(s):
            rows.append(int(s.replace(' ', '')))
    total = 0
    if len(rows) == 2 and rows[1] > 0 and 9 <= rows[0] / rows[1] <= 11:
        total = rows[1]
    elif len(rows) == 1:
        total = rows[0]

    return {
        'doc_type': '수입세금계산서',
        'company_name': comp,
        'identifier': bl.group(1).upper(),
        'id_type': 'BL',
        'total_amount': total,
        'product_name': '',
        'supplier_name': '',
        'billing_items': [],
        'supplier_business_no': supplier_biz,
        'buyer_business_no': buyer_biz,
        'parsed_by': 'form_parser',
    }


def parse_standard_form(fp):
    """1페이지 텍스트 레이어로 표준 서식 확정 파싱. 실패/비대상이면 None."""
    try:
        text = _first_page_text(fp)
    except Exception:
        return None
    if not text or len(text.strip()) < 50:
        return None  # 스캔본 등 텍스트 없음 → AI 경로
    try:
        return _parse_notice(text) or _parse_import_tax_invoice(text)
    except Exception:
        return None


# ── 신고서 / 신고필증 확정 판별 ──
# 실측 근거 (E:\수입신고·E:\수출신고 아카이브 1,879건 개봉, 오판 0건):
#   A. 신고필증  : 최상단 "* 본 신고필증은 전자문서(PDF파일)로 발급된 신고필증입니다"
#                  + 제목 "수 입 신 고 필 증" + "시점확인필" + 하단 "발 행 번 호"
#   B. 신고서    : 제목 "수 입 신 고 서" (견본 표기 없음 — 신형 UNI-PASS 출력물)
#   C. 임시용견본: 제목 칸이 "견   본 (수입)" 이고 상·하단에 "이 문서는 임시용 견본입니다"
#                  (수리 전 단계이므로 신고서와 동일 취급)
#   D. 스캔본    : 텍스트 레이어 없음 → None 반환, 기존 AI 판정으로 폴백
# AI 이미지 판독은 자간이 넓은 "수 입 신 고 서" 를 빈번형인 "수입신고필증" 으로
# 정규화해 읽는 오분류가 반복되므로, 텍스트 레이어가 있으면 이쪽을 신뢰한다.

# 신고 서식이 아닌 문서(계산서 본문의 단어 언급 등)에 규칙이 오작동하지 않도록 하는 관문
_DECL_GATE_KWS = ('화물관리번호', '송품장부호', '적재의무기한')
_DECL_EXPORT_KWS = ('송품장부호', '수출대행자', '적재의무기한')
_DECL_SAMPLE_KWS = ('이문서는임시용견본입니다', '견본(수입)', '견본(수출)')


def classify_declaration(text):
    """수입/수출/반송 신고서·신고필증을 텍스트 레이어로 확정 판별.

    판정 불가(스캔본, 신고 서식 아님)면 None 을 반환해 AI 판정을 그대로 쓴다 (fail-open).
    """
    if not text:
        return None
    t = ''.join(text.split())  # 모든 공백 제거 ("수 입 신 고 서" → "수입신고서")
    if not any(k in t for k in _DECL_GATE_KWS):
        return None

    is_export = any(k in t for k in _DECL_EXPORT_KWS)

    # 1순위: 임시용 견본 — 제목이 "신고필증" 으로 적혀 있어도 견본이 우선한다
    if any(k in t for k in _DECL_SAMPLE_KWS):
        if '견본(수입)' in t:
            return '수입신고서'
        if '견본(수출)' in t or is_export:
            return '수출신고서'
        return '수입신고서'

    # 2순위: 신고필증 (수리 후 발급본)
    for name in ('반송신고필증', '수입신고필증', '수출신고필증'):
        if name in t:
            return name

    # 3순위: 신고서 (수리 전)
    for name in ('수입신고서', '수출신고서'):
        if name in t:
            return name

    return None


def classify_declaration_file(fp):
    """파일 경로로 신고서/신고필증 확정 판별. 실패 시 None."""
    try:
        return classify_declaration(_first_page_text(fp))
    except Exception:
        return None
