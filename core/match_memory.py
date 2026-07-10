# JARVIS Core - 매칭 메모리
"""회사명 별칭 사전 + 금액-only 매칭 사용자 결정 저장소

company_aliases.json — 병합 확정 시 자동 학습되는 회사명 표기 ↔ 한글 상호 매핑
  {"GOBIX": {"고빅스": {"count": 2, "last": "2026-07-09"}}}
  같은 표기가 서로 다른 상호와 짝지어지면(1:N) 판별력이 없는 것으로 보고
  매칭에 사용하지 않는다 (정산업체·지불대행사 표기 오학습 방어).

match_decisions.json — 금액-only(tier3) 제안에 대한 사용자 승인/거부 기록
  {"파일명.pdf|BL번호": {"action": "accept" | "reject", "date": "2026-07-09"}}
  그룹핑은 매 스캔 stateless 재구성이므로 결정을 파일로 영속화해야
  승인이 유지되고 거부한 제안이 다시 뜨지 않는다.
"""

import os
import sys
import json
import threading
from datetime import date

ALIAS_FILE = 'company_aliases.json'
DECISION_FILE = 'match_decisions.json'

_LOCK = threading.Lock()


def _data_dir():
    run_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, 'frozen', False):
        run_dir = os.path.dirname(sys.executable)
    d = os.path.join(run_dir, 'data')
    os.makedirs(d, exist_ok=True)
    return d


def _load(name):
    path = os.path.join(_data_dir(), name)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(name, data):
    path = os.path.join(_data_dir(), name)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ─────────────────────────────────────────────
# 회사명 별칭
# ─────────────────────────────────────────────

def get_aliases():
    """전체 별칭 맵 반환 (1회 로드 후 재사용 용도)."""
    with _LOCK:
        return _load(ALIAS_FILE)


def lookup_alias(name):
    """별칭 표기 → 한글 상호. 1:N 별칭은 판별력 없음으로 간주해 None."""
    name = (name or '').strip()
    if not name:
        return None
    entry = get_aliases().get(name)
    if not isinstance(entry, dict) or len(entry) != 1:
        return None
    return next(iter(entry))


def learn_alias(alias, canonical):
    """병합 확정 시 표기 ↔ 상호 짝 학습. 호출 측에서 강증거(BL 일치) 필터링 필수."""
    alias = (alias or '').strip()
    canonical = (canonical or '').strip()
    if not alias or not canonical or alias == canonical:
        return
    with _LOCK:
        data = _load(ALIAS_FILE)
        entry = data.setdefault(alias, {})
        rec = entry.setdefault(canonical, {'count': 0, 'last': ''})
        rec['count'] = int(rec.get('count', 0)) + 1
        rec['last'] = date.today().isoformat()
        _save(ALIAS_FILE, data)


def remove_alias(alias):
    """별칭 삭제 (설정 화면에서 오학습 제거용)."""
    with _LOCK:
        data = _load(ALIAS_FILE)
        if alias in data:
            del data[alias]
            _save(ALIAS_FILE, data)


def unlearn_alias(alias, canonical):
    """되돌리기 시 학습 1회 취소 (count 감소, 0이 되면 짝 제거)."""
    alias = (alias or '').strip()
    canonical = (canonical or '').strip()
    if not alias or not canonical:
        return
    with _LOCK:
        data = _load(ALIAS_FILE)
        entry = data.get(alias)
        if not isinstance(entry, dict) or canonical not in entry:
            return
        rec = entry[canonical]
        count = int(rec.get('count', 0)) - 1 if isinstance(rec, dict) else 0
        if count <= 0:
            del entry[canonical]
            if not entry:
                del data[alias]
        else:
            rec['count'] = count
        _save(ALIAS_FILE, data)


# ─────────────────────────────────────────────
# 금액-only 매칭 사용자 결정
# ─────────────────────────────────────────────

def _dkey(filename, bl):
    return f"{filename}|{bl}"


def get_decisions():
    """전체 결정 맵 {key: action} 반환 (1회 로드 후 재사용 용도)."""
    with _LOCK:
        data = _load(DECISION_FILE)
    return {k: v.get('action', '') for k, v in data.items() if isinstance(v, dict)}


def record_decision(filename, bl, accept):
    with _LOCK:
        data = _load(DECISION_FILE)
        data[_dkey(filename, bl)] = {
            'action': 'accept' if accept else 'reject',
            'date': date.today().isoformat(),
        }
        _save(DECISION_FILE, data)


def prune_decisions(existing_filenames):
    """폴더에 더 이상 없는 파일의 결정 기록 청소 (병합·삭제 후 누수 방지)."""
    existing = set(existing_filenames)
    with _LOCK:
        data = _load(DECISION_FILE)
        keep = {k: v for k, v in data.items() if k.split('|', 1)[0] in existing}
        if len(keep) != len(data):
            _save(DECISION_FILE, keep)
