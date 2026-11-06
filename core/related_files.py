"""같은 ID 관련 파일 후보 찾기·정리 폴더로 옮기기 (수출·반송건 폴더 정리용)

수출·반송건은 v1.1.90 부터 같은 ID 파일 자동 수집을 하지 않는다 — 파일명에 ID 가
'포함'만 돼도 끌고 와서 별건 카드(2026.10.09 ↔ 2026.10.09-1)의 서류까지 옮겼다.
대신 후보를 찾아 사용자에게 보여주고 고른 것만 옮긴다.

- 후보: 작업 폴더 바로 아래 파일 중 이름에 ID 가 들어간 것, 그런 파일이 든 하위 폴더
- exact: ID 앞뒤가 다른 글자로 이어지지 않음 (별건 꼬리 '-1'·이어지는 영숫자 없음) → 기본 체크
  그 밖(포함만)은 '별건 의심'으로 기본 해제
"""
import os
import re
import shutil

# 너무 짧은 ID 는 거의 모든 파일명에 들어간다 (ID "0" 으로 49개 파일이 쓸린 사고)
_MIN_ID_LEN = 4


def _norm(text):
    """ID 비교용 — 대문자 + OCR 혼동 문자 통일 (공백은 경계 판단에 쓰므로 유지)."""
    return (text or '').upper().replace('O', '0').replace('I', '1')


def id_hit(target_id, text):
    """text 에 ID 가 있는지: None(없음) / 'exact'(경계 일치) / 'partial'(포함만)."""
    tid = _norm(target_id).replace(' ', '')
    if len(tid) < _MIN_ID_LEN:
        return None
    t = _norm(text)
    if tid not in t.replace(' ', ''):
        return None
    for m in re.finditer(re.escape(tid), t):
        before = t[m.start() - 1] if m.start() > 0 else ''
        after = t[m.end():m.end() + 2]
        if before and before.isalnum():
            continue
        if after[:1].isalnum():
            continue
        if after[:1] == '-' and after[1:2].isalnum():
            continue  # 별건 꼬리 (2026.10.09-1)
        return 'exact'
    return 'partial'


def find_related_candidates(dr, target_id, exclude_names=(), skip_dirs=()):
    """작업 폴더에서 같은 ID 후보 목록. 아무것도 옮기지 않는다.

    반환: [{'path', 'name', 'kind': 'file'|'folder', 'exact': bool, 'count': int}]
    exact 후보가 앞에 온다.
    """
    exclude = set(exclude_names or ())
    skip = set(skip_dirs or ())
    out = []
    if len(_norm(target_id).replace(' ', '')) < _MIN_ID_LEN:
        return out
    try:
        items = sorted(os.listdir(dr))
    except OSError:
        return out
    for item in items:
        path = os.path.join(dr, item)
        if os.path.isfile(path):
            if item in exclude or item.startswith('~$'):
                continue
            hit = id_hit(target_id, item)
            if hit:
                out.append({'path': path, 'name': item, 'kind': 'file',
                            'exact': hit == 'exact', 'count': 1})
        elif os.path.isdir(path):
            if item in skip:
                continue
            try:
                files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
            except OSError:
                continue
            hits = [id_hit(target_id, f) for f in files]
            if not any(hits):
                continue
            exact = id_hit(target_id, item) == 'exact' or 'exact' in hits
            out.append({'path': path, 'name': item, 'kind': 'folder',
                        'exact': exact, 'count': len(files)})
    out.sort(key=lambda c: not c['exact'])
    return out


def move_into_archive(candidates, archive_dir, entry_id=None, log=None):
    """고른 후보를 정리 폴더로 옮기고 되돌리기 기록에 덧붙인다. 옮긴 파일 수 반환.

    폴더 후보는 안의 파일만 옮기고 빈 폴더는 지운다 (예전 자동 수집과 같은 방식).
    같은 이름이 정리 폴더에 이미 있으면 건너뛴다.
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    moves = []
    for c in candidates or ():
        src = c.get('path', '')
        if c.get('kind') == 'folder':
            if not os.path.isdir(src):
                continue
            for f in os.listdir(src):
                fp = os.path.join(src, f)
                if not os.path.isfile(fp):
                    continue
                dst = os.path.join(archive_dir, f)
                if os.path.exists(dst):
                    _log(f" -> [포함 건너뜀] 같은 이름 있음: {f}")
                    continue
                try:
                    shutil.move(fp, dst)
                    moves.append((f, src, archive_dir))
                    _log(f" -> [포함] {f} (from {os.path.basename(src)}/)")
                except Exception as e:
                    _log(f" -> [포함 실패] {f}: {e}")
            try:
                os.rmdir(src)
            except OSError:
                pass
        else:
            if not os.path.isfile(src):
                continue
            name = os.path.basename(src)
            dst = os.path.join(archive_dir, name)
            if os.path.exists(dst):
                _log(f" -> [포함 건너뜀] 같은 이름 있음: {name}")
                continue
            try:
                shutil.move(src, dst)
                moves.append((name, os.path.dirname(src), archive_dir))
                _log(f" -> [포함] {name}")
            except Exception as e:
                _log(f" -> [포함 실패] {name}: {e}")
    if moves and entry_id:
        from . import merge_history
        merge_history.append_moves(entry_id, moves)
    return len(moves)
