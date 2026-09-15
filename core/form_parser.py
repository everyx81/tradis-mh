# JARVIS Core - 표준 서식 직독 파서
"""
관세청 표준 서식(납부고지서, 수입세금계산서)의 텍스트 레이어 직독 파서.

이 서류들은 UNI-PASS 전산 출력물이라 텍스트 레이어가 완전하다.
AI 이미지 인식은 상호/성명 라벨-값 짝짓기를 틀릴 수 있으므로
(대표자 성명이 로마자인 경우 성명을 상호로 오독한 사례),
구조 마커가 모두 일치하고 상호·BL 파싱까지 성공한 경우에만 확정 결과를 반환한다.
실패하면 None을 반환해 기존 AI OCR 경로로 폴백한다 (fail-open).
"""

import os
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


# ── 신고서 / 신고필증 오분류 보완 ──
# 판별 주체는 AI 다. 이 모듈은 AI 가 '신고필증'으로 읽은 결과가 **명백히** 틀린
# 경우에만 뒤집는 보완 레이어이며, 확신이 서지 않으면 아무것도 하지 않는다.
#
# 실측 근거 (E:\수입신고·E:\수출신고 아카이브 4,450건 개봉):
#   신고필증  : "* 본 신고필증은 전자문서(PDF파일)로 발급된 신고필증입니다" +
#               "시점확인필" + 하단 "발 행 번 호" (셋 중 최소 하나는 반드시 존재)
#   신고서    : 위 마커가 하나도 없고 제목이 "수 입 신 고 서"
#   임시용견본: 제목이 "견   본 (수입)", 상·하단 "이 문서는 임시용 견본입니다"

# 신고 서식이 아닌 문서(계산서 본문의 단어 언급 등)에 규칙이 닿지 않게 하는 관문
_DECL_GATE_KWS = ('화물관리번호', '송품장부호', '적재의무기한')
_DECL_EXPORT_KWS = ('송품장부호', '수출대행자', '적재의무기한')
_DECL_SAMPLE_KWS = ('이문서는임시용견본입니다', '견본(수입)', '견본(수출)')
# 신고필증에만 인쇄되는 마커 (수리 후 발급본의 증거)
_DECL_RECEIPT_MARKS = ('발급된신고필증입니다', '시점확인필', '발행번호')
_CERT_TYPES = ('수입신고필증', '수출신고필증', '반송신고필증')

# 화물관리번호 서식 (예: 26ZIMU0112I-7057, 26TW008222I-0005-0001)
# ④B/L(AWB)번호 바로 오른쪽 칸이라 AI 가 한 칸 밀려 집어오는 일이 잦다.
RE_CARGO_MGMT_NO = re.compile(r'^\d{2}[A-Z0-9]{4,10}[IE]-\d{4}(?:-\d{4})?$')


def declaration_evidence(text):
    """신고 서식에서 종류 판별 증거만 수집. 신고 서식이 아니면 None."""
    if not text:
        return None
    t = ''.join(text.split())  # 모든 공백 제거 ("수 입 신 고 서" → "수입신고서")
    if not any(k in t for k in _DECL_GATE_KWS):
        return None

    is_export = any(k in t for k in _DECL_EXPORT_KWS)

    sample_type = None
    if any(k in t for k in _DECL_SAMPLE_KWS):
        if '견본(수입)' in t:
            sample_type = '수입신고서'
        elif '견본(수출)' in t or is_export:
            sample_type = '수출신고서'
        else:
            sample_type = '수입신고서'

    return {
        'is_export': is_export,
        'sample_type': sample_type,
        'title_decl': ('수출신고서' if '수출신고서' in t
                       else ('수입신고서' if '수입신고서' in t else None)),
        'title_cert': next((n for n in _CERT_TYPES if n in t), None),
        'receipt_marks': sum(1 for m in _DECL_RECEIPT_MARKS if m in t),
    }


def correct_misread_declaration(ai_doc_type, text):
    """AI 가 신고필증으로 읽은 결과가 명백히 틀렸을 때만 교정값을 반환.

    뒤집는 경우는 아래 둘뿐이다.
      (1) 임시용 견본 표기가 있는데 신고필증이라 한 경우
      (2) 제목이 신고서이고 문서 어디에도 '신고필증' 제목이 없는데 신고필증이라 한 경우
    그 밖에는 None 을 반환해 AI 판정을 그대로 쓴다. 반대 방향(AI 가 신고서라
    한 것을 신고필증으로 올리는 것)은 다루지 않는다.

    [주의] 상단 안내문("본 신고필증은 전자문서…")과 "시점확인필" 문구는 신고서
    출력물에도 그대로 인쇄되는 서식 보일러플레이트다 (실측 신고서 573건 중 246건).
    판정 근거로 쓰면 안 되며, receipt_marks 는 진단·로그용으로만 남긴다.
    """
    if ai_doc_type not in _CERT_TYPES:
        return None
    ev = declaration_evidence(text)
    if not ev:
        return None
    if ev['sample_type']:
        return ev['sample_type'] if ev['sample_type'] != ai_doc_type else None
    if ev['title_decl'] and not ev['title_cert']:
        return ev['title_decl']
    return None


# ── 서식 제목 직독 서류 종류 확정 ──
# 1페이지에 서식 제목이 그대로 인쇄되는 문서는 그 제목을 서류 종류로 쓴다.
# AI 가 실행마다 비슷한 다른 종류(적합성평가확인서 등)로 스냅하는 오분류 차단.
TITLE_DOC_TYPES = [
    "전기용품 및 생활용품 세관장확인물품 확인 신청서",
]


def correct_doc_type_by_title(ai_doc_type, text):
    """1페이지 텍스트에 등록된 서식 제목이 있으면 그 제목을 서류 종류로 반환.
    제목이 없거나 AI 분류가 이미 일치하면 None (AI 판정 유지)."""
    if not text:
        return None
    t = ''.join(text.split())
    for title in TITLE_DOC_TYPES:
        if title.replace(' ', '') in t:
            return title if title != (ai_doc_type or '') else None
    return None


# ── 계산서 vs 청구서 판별 · 해도 발행 판별 (v1.1.80) ──
# 제3자(포워더·창고 등) 문서는 전자세금계산서 승인번호 유무로 계산서/청구서를 나눈다.
# 폴더 실측: 정상 계산서는 전부 국세청 승인번호(작성일 8자리+8자리+영숫자 8자리)가
# 있고, 운임 청구내역서(BILLING STATEMENT)는 공급가액·세액 칸이 있어도 승인번호가 없다.
# 수기 세금계산서는 제목으로 예외 인정한다.

# 전자세금계산서 승인번호: 2026071341000061gf6nhcdi / 202607284100000151955819
RE_TAX_INVOICE_APPROVAL = re.compile(r'20\d{14}[0-9a-zA-Z]{8}')

# 청구서 계열 제목 (공백 제거·소문자 비교)
BILL_TITLE_KEYWORDS = [
    "청구서", "청구내역서", "운임내역서", "거래명세서", "거래명세표",
    "billingstatement", "freightinvoice", "invoice", "debitnote", "arrivalnotice",
]

# 영수증 급 제목 (공백 제거·소문자 비교) — 계산서 대체 서류. 영수증에는 참조란에
# "INVOICE NO." 같은 글자가 흔히 인쇄되므로, 이 제목이 있으면 청구서로 뒤집지 않는다.
RECEIPT_TITLE_KEYWORDS = [
    "영수증", "입금표", "입금증",
    "officialreceipt", "receivedwiththanks", "receipt",
]

# 청구서로 뒤집지 않는 종류 (세관·해도 양식, 계산서 대체 서류)
_BILL_FIX_EXEMPT = {
    "수입세금계산서", "납부고지서", "자금청구서", "자금정산서",
    "입금표", "영수증", "이체증",
}


def has_tax_invoice_approval(text):
    """1페이지 텍스트에 전자세금계산서 승인번호가 있는지."""
    if not text:
        return False
    t = ''.join(text.split())
    return bool(RE_TAX_INVOICE_APPROVAL.search(t))


def is_tax_invoice_text(text):
    """계산서(세금계산서) 문서인지 — 승인번호가 있거나, 제목 영역에 '세금계산서'가 인쇄됨."""
    if not text:
        return False
    if has_tax_invoice_approval(text):
        return True
    head = ''.join(text.split())[:200]
    return "세금계산서" in head


def has_bill_title(text):
    """청구서 계열 제목(청구서·청구내역서·BILLING STATEMENT·INVOICE·A/N 등)이 있는지."""
    if not text:
        return False
    t = ''.join(text.split()).lower()
    return any(k in t for k in BILL_TITLE_KEYWORDS)


def has_receipt_title(text):
    """영수증 급 제목(영수증·입금표·RECEIPT·OFFICIAL RECEIPT 등)이 있는지."""
    if not text:
        return False
    t = ''.join(text.split()).lower()
    return any(k in t for k in RECEIPT_TITLE_KEYWORDS)


def correct_bill_vs_invoice(ai_doc_type, text):
    """AI 가 청구서를 비용 계산서(항공운임계산서 등)로 분류했을 때 '청구서'로 되돌린다.

    조건: AI 종류가 '…계산서' 이고, 텍스트에 승인번호·세금계산서 제목이 없고,
    영수증 급 제목도 없으며, 청구서 계열 제목이 있을 때만.
    텍스트 레이어가 없는 스캔본은 None (AI 판정 유지).
    """
    dt = (ai_doc_type or '').replace(' ', '')
    if not text or not dt or not dt.endswith("계산서"):
        return None
    if dt in _BILL_FIX_EXEMPT:
        return None
    if is_tax_invoice_text(text):
        return None
    if has_receipt_title(text):
        return None   # 영수증(계산서 대체 서류) — "INVOICE NO." 참조란 때문에 청구서로 오판하지 않음
    if has_bill_title(text):
        return "청구서"
    return None


def detect_haedo_issuer(result, text):
    """문서 발행처가 해도관세사무소인지.

    AI 가 공급자 사업자번호를 읽었으면 그 값만 신뢰하고, 못 읽었을 때만
    텍스트 레이어에서 해도 사업자번호·상호를 찾는다 (자금청구서·자금정산서는
    본문에 168-76-00091 과 '해도관세' 가 인쇄됨).
    """
    from .constants import HAEDO_BUSINESS_NO
    haedo = re.sub(r'\D', '', HAEDO_BUSINESS_NO)
    sup = str((result or {}).get('supplier_business_no') or '')
    sup_digits = re.sub(r'\D', '', sup)
    if len(sup_digits) == 10:
        return sup_digits == haedo
    if not text:
        return False
    t = ''.join(text.split())
    return HAEDO_BUSINESS_NO in t or haedo in t or "해도관세" in t


# ── 수입신고필증 징수형태·세액 직독 ──
# AI 가 감면 필증에서 '세액' 칸(감면 후 납부세액) 대신 '감면액' 칸을 부가세로
# 읽는 오독이 있어 (감면율 100% → 실제 세액 0 인데 감면액 19,392,130 을 vat 로 반환),
# 텍스트 레이어가 있는 전자발급 필증은 세액 필드를 직독으로 확정한다.
# 찾지 못한 필드는 None 으로 두어 AI 값을 유지한다 (fail-open).

# '63 총세액합계' 라벨 뒤 첫 숫자 (값은 보통 다음 줄 첫 토큰)
RE_TOTAL_TAX = re.compile(r'총\s*세\s*액\s*합\s*계[\s\S]{0,12}?([\d,]+)')


def _leading_amount(line):
    """줄 맨 앞의 금액 토큰만 추출 (예: '0 67 담당자' → 0). 없으면 None."""
    m = re.match(r'([\d,]+)', line.strip())
    return int(m.group(1).replace(',', '')) if m else None


def extract_import_cert_tax(text):
    """수입신고필증 텍스트 레이어에서 징수형태·세액을 직독.

    반환: {'levy_type', 'total_tax', 'customs_duty', 'vat'} (미확인 필드는 None).
    수입신고필증 텍스트가 아니거나 아무 필드도 못 읽으면 None.
    """
    if not text:
        return None
    t_flat = ''.join(text.split())
    if '수입신고필증' not in t_flat or '징수형태' not in t_flat:
        return None

    lines = [ln.strip() for ln in text.split('\n')]
    info = {'levy_type': None, 'total_tax': None, 'customs_duty': None, 'vat': None}

    # 징수형태: 라벨 줄 이후 8줄 안의 단독 2자리 숫자
    # (사이에 B/L·화물관리번호·날짜 값이 끼지만 어느 것도 단독 2자리가 아님)
    for i, ln in enumerate(lines):
        if ''.join(ln.split()) in ('징수형태', '9징수형태'):
            for nxt in lines[i + 1:i + 9]:
                if re.fullmatch(r'\d{2}', nxt):
                    info['levy_type'] = nxt
                    break
            break

    # 62 세액 블록: '관   세' / '부가가치세' 단독 라벨 줄 다음 줄 첫 숫자
    # ('관세법…', '부가가치세과표' 등 다른 등장은 단독 라벨이 아니라 걸리지 않음)
    for i, ln in enumerate(lines[:-1]):
        key = ''.join(ln.split())
        if key == '관세' and info['customs_duty'] is None:
            info['customs_duty'] = _leading_amount(lines[i + 1])
        elif key == '부가가치세' and info['vat'] is None:
            info['vat'] = _leading_amount(lines[i + 1])

    m = RE_TOTAL_TAX.search(text)
    if m:
        info['total_tax'] = int(m.group(1).replace(',', ''))

    if all(v is None for v in info.values()):
        return None
    return info


# ── 신고번호 직독 추출 ──
# 신고번호 서식: 신고인부호(5) - 연도(2) - 일련번호(6) + 검증문자(1)
# 예: 13133-26-002604X, 13133-26-001733M
RE_DECLARATION_NO = re.compile(r'\b(\d{5}-\d{2}-\d{6}[0-9A-Z])\b')

_DECL_NO_MEMO = {}  # {(경로, mtime): 신고번호} — 스캔 주기마다 PDF 재개봉 방지


def extract_declaration_no(fp):
    """신고필증/신고서 1페이지 텍스트 레이어에서 신고번호 추출.

    통관수수료계산서 등 비용 계산서가 BL 대신 신고번호를 괄호 ID 로 달고
    오는 경우가 있어, 카드(그룹)의 보조 ID 로 등록해 편입 근거로 쓴다.
    텍스트 레이어가 없거나(스캔본) 서식이 다르면 "" 반환 (fail-open).
    """
    try:
        key = (fp, os.path.getmtime(fp))
    except OSError:
        return ""
    if key in _DECL_NO_MEMO:
        return _DECL_NO_MEMO[key]
    val = ""
    try:
        text = _first_page_text(fp)
        if text:
            m = RE_DECLARATION_NO.search(text)
            if m:
                val = m.group(1).upper()
    except Exception:
        val = ""
    _DECL_NO_MEMO[key] = val
    return val


def is_cargo_mgmt_no(value, text):
    """AI 가 B/L 로 집어온 값이 실제로는 ⑤화물관리번호인지 판단.

    서식(연도2자리+선사코드+I/E-숫자)과 문서 원문 등장 여부를 **둘 다** 만족할
    때만 True. 정상 B/L 을 잘못 거부하지 않도록 보수적으로 판단한다.
    """
    if not value or not text:
        return False
    v = value.replace(' ', '').upper()
    if not RE_CARGO_MGMT_NO.match(v):
        return False
    return v in ''.join(text.split()).upper()
