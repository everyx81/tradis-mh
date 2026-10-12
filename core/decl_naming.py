# JARVIS Core - 업체별 신고필증 이름 규칙
"""업체별 신고필증 이름 규칙 + 이름표 기록 (v1.1.91)

특정 업체는 필증 파일 이름을 자기 형식으로 요구한다.
  예) 13133-26-003099X(ZABC-260930-4A).pdf  ← {신고번호}({ID}).pdf

TRADIS 는 파일 이름에서 회사명·ID·서류 종류를 읽어 카드를 만든다. 업체 형식
이름에는 회사명·서류 종류가 없으므로, 그 이름을 붙일 때 원래 정보를 이름표
기록(data/custom_names.json)에 남기고 parse_renamed_filename 이 먼저 조회한다.
카드 모양·매칭·정리는 기존과 같고 파일 이름만 달라진다.

분석 캐시(.analysis_cache.json)와 따로 두는 이유: 캐시는 '다시 분석' 요청 때
지워지지만 이름표는 파일 이름이 존재하는 한 유지되어야 한다.
"""

import os
import re
import sys
import json
import threading

# 서류 종류 → 규칙 구분 (반송은 수출 규칙에 포함)
DECL_KIND = {
    "수출신고필증": "수출",
    "반송신고필증": "수출",
    "수입신고필증": "수입",
}

TOKENS = ("{신고번호}", "{ID}", "{회사명}", "{서류종류}")
DEFAULT_RULE_PATTERN = "{신고번호}({ID}).pdf"

_REG_FILE = 'custom_names.json'
_LOCK = threading.Lock()
_REG = None   # {파일명: {"company", "identifier", "doc_type"}}

_RE_TOKEN = re.compile(r'\{[^{}]*\}')
_RE_INVALID = re.compile(r'[\\/*?:"<>|]')


def _reg_path():
    run_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, 'frozen', False):
        run_dir = os.path.dirname(sys.executable)
    d = os.path.join(run_dir, 'data')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, _REG_FILE)


def _load():
    """호출자는 _LOCK 을 잡은 상태여야 한다. 이 프로세스만 쓰므로 1회 로드."""
    global _REG
    if _REG is None:
        try:
            with open(_reg_path(), 'r', encoding='utf-8') as f:
                data = json.load(f)
            _REG = data if isinstance(data, dict) else {}
        except Exception:
            _REG = {}
    return _REG


def _save():
    path = _reg_path()
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_REG, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[이름표] 저장 실패: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass


# ─────────────────────────────────────────────
# 이름표 기록
# ─────────────────────────────────────────────

def lookup(name):
    """업체 형식 이름이면 (company, identifier, doc_type, None), 아니면 None."""
    if not name:
        return None
    with _LOCK:
        e = _load().get(name)
    if not isinstance(e, dict) or not e.get('identifier'):
        return None
    return e.get('company') or "", e['identifier'], e.get('doc_type') or "", None


def register(name, company, identifier, doc_type, orig=None):
    """orig: 규칙 적용 전 이름 — 규칙 해제 시 그대로 복원한다 ('(영문)' 같은 표시 보존).
    종류가 바뀌어 다시 기록할 때는 orig 를 넘기지 않는다 (옛 종류 이름 복원 방지)."""
    entry = {'company': company or "", 'identifier': identifier, 'doc_type': doc_type or ""}
    if orig:
        entry['orig'] = orig
    with _LOCK:
        _load()[name] = entry
        _save()


def original_name(name):
    """규칙 적용 전 이름 (기록이 없으면 "")."""
    with _LOCK:
        e = _load().get(name)
    return (e.get('orig') or "") if isinstance(e, dict) else ""


def unregister(name):
    with _LOCK:
        if _load().pop(name, None) is not None:
            _save()


def match_text(name):
    """파일 이름 글자로 서류 종류를 가리던 판정용 문자열.

    업체 형식 이름에는 '수출신고필증' 같은 글자가 없으므로 이름표의 종류를 덧붙인다.
    일반 이름은 그대로 반환한다."""
    e = lookup(name)
    return f"{name} {e[2]}" if e else (name or "")


# ─────────────────────────────────────────────
# 규칙
# ─────────────────────────────────────────────

def _norm_company(name):
    from .utils import cleanup_company_name
    return cleanup_company_name(name or "").upper()


def find_rule(company, doc_type):
    """이 업체·서류에 걸린 규칙. 상호는 정리 후 완전 일치, 없으면 학습된 별칭으로 비교."""
    kind = DECL_KIND.get(doc_type or "")
    if not kind or not company:
        return None
    from .config import get_decl_name_rules
    rules = [r for r in get_decl_name_rules() if kind in r['kinds']]
    if not rules:
        return None
    target = _norm_company(company)
    if not target:
        return None
    for r in rules:
        if _norm_company(r['company']) == target:
            return r
    # 영문 표기 등 별칭 — 한 상호로만 학습된 것(판별력 있음)만 사용
    try:
        from .match_memory import get_aliases
        entry = get_aliases().get(company)
        if isinstance(entry, dict) and len(entry) == 1:
            canon = _norm_company(next(iter(entry)))
            for r in rules:
                if _norm_company(r['company']) == canon:
                    return r
    except Exception:
        pass
    return None


def validate_pattern(pattern):
    """잘못된 패턴이면 오류 문구, 정상이면 ""."""
    p = (pattern or "").strip()
    if not p:
        return "패턴이 비어 있습니다."
    unknown = [t for t in _RE_TOKEN.findall(p) if t not in TOKENS]
    if unknown:
        return f"알 수 없는 항목: {', '.join(unknown)}"
    if "{신고번호}" not in p and "{ID}" not in p:
        return "{신고번호} 또는 {ID} 중 하나는 들어가야 합니다 (건마다 이름이 달라야 함)."
    body = _RE_TOKEN.sub("", p)
    if _RE_INVALID.search(body):
        return '파일 이름에 쓸 수 없는 문자가 있습니다 (\\ / : * ? " < > |).'
    if p.startswith("10.") or p.startswith("미분류_"):
        return "'10.' / '미분류_' 로 시작하는 이름은 쓸 수 없습니다."
    return ""


def render(pattern, company, identifier, doc_type, decl_no):
    """규칙 패턴으로 이름 생성. 필요한 값(신고번호 등)이 없으면 None."""
    if validate_pattern(pattern):
        return None
    values = {"{신고번호}": decl_no or "", "{ID}": identifier or "",
              "{회사명}": company or "", "{서류종류}": doc_type or ""}
    name = pattern.strip()
    for tok, val in values.items():
        if tok in name:
            if not val:
                return None
            name = name.replace(tok, _RE_INVALID.sub("", val).strip())
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def default_name(company, identifier, doc_type):
    """규칙이 없을 때의 기본 이름 (file_processor 정식 이름과 동일 규칙)."""
    from .config import get_custom_naming
    try:
        return get_custom_naming()["file_pattern"].format(
            company=company, bl=identifier, doctype=doc_type, amount="")
    except (KeyError, ValueError):
        return f"{company}({identifier}){doc_type}.pdf"


def same_family(current, wanted):
    """current 가 wanted 그 자체이거나 중복 회피 번호만 붙은 이름인지 ((1), (2) …)."""
    if current == wanted:
        return True
    stem, ext = os.path.splitext(wanted)
    if not current.startswith(stem):
        return False
    return re.fullmatch(r'\(\d+\)' + re.escape(ext), current[len(stem):], re.IGNORECASE) is not None
