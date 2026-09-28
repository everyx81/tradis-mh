# JARVIS Core - 운임 계산서 운송 수단(해상/항공) 판정
"""
선박운임계산서 ↔ 항공운임계산서 보정 (v1.1.86)

HANDLING FEE·DOC FEE 처럼 해상·항공 어디에나 붙는 항목만 있는 포워더 계산서는
문서 한 장만 보고는 운송 수단을 알 수 없다. AI 는 이런 계산서를 무조건
'선박운임계산서'로 불러 왔고, 항공 건에서 정산서 '항공운임' 함산이 깨졌다.

판정 원칙
  - 운송 수단 신호는 닫힌 집합(해상 전용 / 항공 전용 항목)으로 정의한다.
    어느 쪽 신호도 없는 계산서만 '중립'이며, 중립 계산서만 보정 대상이다.
    (신호가 있는 계산서는 AI 판정 유지 — 보정은 보수적으로)
  - 중립 계산서의 운송 수단은 같은 B/L 의 다른 서류가 결정한다.
      · 신호가 있는 운임 계산서 (항공운임계산서 AIR FREIGHT … → 항공)
      · 자금정산서/자금청구서 비용 항목 (항공운임 / 선박운임)
    한쪽 증거만 있을 때만 확정하고, 양쪽 증거가 다 있거나 없으면 그대로 둔다.
"""

import os

from .constants import EXPENSE_SYNONYMS

SEA_FREIGHT_DOC = "선박운임계산서"
AIR_FREIGHT_DOC = "항공운임계산서"
FREIGHT_DOCS = {SEA_FREIGHT_DOC: "sea", AIR_FREIGHT_DOC: "air"}
MODE_DOC = {"sea": SEA_FREIGHT_DOC, "air": AIR_FREIGHT_DOC}

# 운송 수단 전용 항목 (공백 제거·대문자 비교, 부분 일치)
# 양쪽에 다 쓰이는 항목(HANDLING, DOC FEE, D/O 이외 부대비, FUEL SURCHARGE,
# C.C FEE, TRUCKING 등)은 넣지 않는다 — 넣으면 중립 계산서가 한쪽으로 굳는다.
SEA_ITEM_SIGNALS = (
    "OCEAN", "O/F", "SEAFREIGHT", "BAF", "CAF", "LSS", "THC", "WHARFAGE", "W/F",
    "D/O", "DOCHARGE", "DOFEE", "CIC", "EBS", "DRAYAGE", "CFS",
    "해상", "선박", "부두",
)
AIR_ITEM_SIGNALS = (
    "AIR", "A/F", "AWB", "FSC", "SSC", "항공",
)

# 자금정산서/자금청구서 비용 항목 → 운송 수단 (동의어 사전 재사용)
_SETTLEMENT_DOCS = {"자금정산서", "자금청구서"}
_SEA_EXPENSE_KWS = ("선박운임",) + tuple(EXPENSE_SYNONYMS.get("선박운임", []))
_AIR_EXPENSE_KWS = ("항공운임",) + tuple(EXPENSE_SYNONYMS.get("항공운임", []))


def _norm(s):
    return "".join(str(s or "").split()).upper()


def _item_names(result, key="billing_items"):
    items = (result or {}).get(key) or []
    names = []
    for it in items:
        if isinstance(it, dict):
            names.append(it.get("name", ""))
        elif isinstance(it, str):
            names.append(it)
    return [n for n in names if n]


def item_modes(result):
    """계산서 청구 항목에 나타난 운송 수단 신호 집합 ({'sea','air'} 의 부분집합)."""
    modes = set()
    for name in _item_names(result):
        n = _norm(name)
        if n == "OF" or any(k in n for k in SEA_ITEM_SIGNALS):
            modes.add("sea")
        if any(k in n for k in AIR_ITEM_SIGNALS):
            modes.add("air")
    return modes


def is_neutral_freight(result):
    """운임 계산서인데 청구 항목에 운송 수단 신호가 하나도 없는지 (보정 대상)."""
    if not result or result.get("doc_type") not in FREIGHT_DOCS:
        return False
    if result.get("doc_type_src") == "manual":
        return False   # 사용자가 카드에서 직접 교정한 종류는 건드리지 않는다
    if not _item_names(result):
        return False   # 항목을 못 읽었으면 근거 부족 — AI 판정 유지
    return not item_modes(result)


def evidence_modes(result):
    """다른 서류 한 장이 가리키는 운송 수단 집합 (증거 없으면 빈 집합)."""
    if not result:
        return set()
    dt = result.get("doc_type")
    if dt in FREIGHT_DOCS:
        modes = item_modes(result)
        # 자기 종류와 항목 신호가 일치하는 계산서만 증거로 쓴다
        # (중립 계산서끼리 서로를 근거로 삼는 순환 방지)
        own = FREIGHT_DOCS[dt]
        return {own} if modes == {own} else set()
    if dt in _SETTLEMENT_DOCS:
        names = (_item_names(result)
                 + _item_names(result.get("merge_info") or {}, "expense_items"))
        modes = set()
        for name in names:
            n = _norm(name)
            if any(_norm(k) in n for k in _SEA_EXPENSE_KWS):
                modes.add("sea")
            if any(_norm(k) in n for k in _AIR_EXPENSE_KWS):
                modes.add("air")
        return modes
    return set()


def resolve_group_mode(sibling_results):
    """같은 B/L 서류들의 증거로 운송 수단 확정. 한쪽만 가리킬 때만 'sea'/'air', 아니면 None."""
    modes = set()
    for r in sibling_results:
        modes |= evidence_modes(r)
    if len(modes) == 1:
        return next(iter(modes))
    return None


def corrected_freight_doc(result, sibling_results):
    """중립 운임 계산서의 올바른 종류. 보정이 필요 없으면 None."""
    if not is_neutral_freight(result):
        return None
    mode = resolve_group_mode(sibling_results)
    if not mode:
        return None
    new_dt = MODE_DOC[mode]
    return new_dt if new_dt != result.get("doc_type") else None


def same_bl_files(dir_name, identifier, exclude=None):
    """폴더에서 같은 B/L 로 이름 붙은 PDF 경로 목록 (파일명 기준)."""
    from .utils import parse_renamed_filename
    ident = _norm(identifier)
    if not ident or ident == "UNKNOWN":
        return []
    out = []
    try:
        names = os.listdir(dir_name)
    except OSError:
        return []
    for name in names:
        if not name.lower().endswith(".pdf") or name == exclude:
            continue
        if identifier not in name and ident not in name.upper():
            continue   # 빠른 거르기 — 파싱은 후보에만
        try:
            _c, i, _d, _s = parse_renamed_filename(name)
        except Exception:
            continue
        if i and _norm(i) == ident:
            out.append(os.path.join(dir_name, name))
    return out
