# JARVIS Core - 정리 기록 (합치기/폴더 정리 되돌리기)
"""합치기·폴더 정리 작업의 백업 + 되돌리기 저장소

data/backups/<entry_id>/ — 작업 1건당 폴더 하나
  ├─ manifest.json   되돌리기 설명서 (아래 스키마)
  └─ *.pdf           병합 후 삭제될 원본 파일들 (이동 보관)

manifest.json 스키마:
  {
    "id": "20260710-143012_삼성물산_HBL12345",
    "created": "2026-07-10T14:30:12",
    "kind": "merge" | "archive",          # 합치기 / 폴더 정리
    "bl_id": "HBL12345",
    "folder_name": "삼성물산_HBL12345",
    "work_dir": "C:/.../작업폴더",
    "archive_dir": "C:/.../작업폴더/삼성물산_HBL12345",
    "merged_file": "삼성물산(HBL12345)정산서.pdf",   # kind=archive 면 None
    "backed_up": ["a.pdf", ...],          # 백업 폴더에 보관된 원본 (병합 후 삭제 대상이던 것)
    "moved": [{"name": "b.pdf", "from": "원래 폴더", "to": "정리 폴더"}, ...],
    "aliases": [["표기", "한글상호"], ...] # 이 작업에서 학습된 별칭 (되돌리기 시 취소)
  }

되돌리기는 (1) 사전 점검 → (2) 병합 PDF 삭제 → (3) 백업 원본 복귀 →
(4) 이동 파일 원위치 → (5) 별칭 학습 취소 → (6) 백업 폴더 제거 순서로 진행.
정리 폴더가 이미 서버로 이동돼 없으면 (3)(5)만 수행하고 안내를 남긴다.
"""

import os
import sys
import json
import time
import shutil
import threading
from datetime import datetime, timedelta

RETENTION_DAYS = 7
MAX_TOTAL_BYTES = 1024 * 1024 * 1024  # 1GB 초과 시 오래된 것부터 정리

_LOCK = threading.Lock()


def _backup_root():
    run_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, 'frozen', False):
        run_dir = os.path.dirname(sys.executable)
    d = os.path.join(run_dir, 'data', 'backups')
    os.makedirs(d, exist_ok=True)
    return d


def _sanitize(name):
    return "".join(c for c in (name or '') if c not in '\\/:*?"<>|').strip() or 'entry'


def _send_to_trash(path):
    """Windows 휴지통으로 이동 (ctypes, 외부 의존성 없음). 실패 시 완전 삭제."""
    try:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_uint16),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x40
        FOF_NOCONFIRMATION = 0x10
        FOF_SILENT = 0x4

        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = os.path.abspath(path) + '\0\0'
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if result == 0 and not op.fAnyOperationsAborted:
            return True
    except Exception:
        pass
    # 폴백: 완전 삭제
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
# 기록 생성 (file_processor가 병합 중에 사용)
# ─────────────────────────────────────────────

def new_entry(kind, bl_id, folder_name, work_dir, archive_dir, merged_file=None):
    """작업 시작 시 기록 객체 생성 + 백업 폴더 확보. 반환된 dict를 채운 뒤 save_entry()."""
    entry_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{_sanitize(folder_name)}"
    backup_dir = os.path.join(_backup_root(), entry_id)
    os.makedirs(backup_dir, exist_ok=True)
    return {
        'id': entry_id,
        'created': datetime.now().isoformat(timespec='seconds'),
        'kind': kind,
        'bl_id': bl_id or '',
        'folder_name': folder_name,
        'work_dir': work_dir,
        'archive_dir': archive_dir,
        'merged_file': merged_file,
        'backed_up': [],
        'moved': [],
        'aliases': [],
    }


def backup_dir_of(entry):
    entry_id = entry['id'] if isinstance(entry, dict) else entry
    return os.path.join(_backup_root(), entry_id)


def backup_file(entry, src_path):
    """삭제 대신 파일을 백업 폴더로 이동. 성공 시 True."""
    name = os.path.basename(src_path)
    dst = os.path.join(backup_dir_of(entry), name)
    if os.path.exists(dst):
        base, ext = os.path.splitext(name)
        dst = os.path.join(backup_dir_of(entry), f"{base}_{int(time.time())}{ext}")
        name = os.path.basename(dst)
    try:
        shutil.move(src_path, dst)
        entry['backed_up'].append(name)
        return True
    except Exception:
        return False


def record_move(entry, name, src_dir, dst_dir):
    """정리 폴더로 이동된 파일 기록 (되돌리기 시 원위치)."""
    entry['moved'].append({'name': name, 'from': src_dir, 'to': dst_dir})


def record_alias(entry, alias, canonical):
    entry['aliases'].append([alias, canonical])


def save_entry(entry):
    """작업 성공 시 manifest 저장. 실패/취소 시 discard_entry()를 호출할 것."""
    path = os.path.join(backup_dir_of(entry), 'manifest.json')
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(entry, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def discard_entry(entry):
    """작업이 취소/실패했을 때: 백업했던 파일을 작업 폴더로 되돌리고 백업 폴더 삭제."""
    bdir = backup_dir_of(entry)
    for name in entry.get('backed_up', []):
        src = os.path.join(bdir, name)
        dst = os.path.join(entry.get('work_dir', ''), name)
        try:
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.move(src, dst)
        except Exception:
            pass
    shutil.rmtree(bdir, ignore_errors=True)


# ─────────────────────────────────────────────
# 기록 조회 / 되돌리기 (GUI가 사용)
# ─────────────────────────────────────────────

def list_entries():
    """manifest가 있는 백업 목록을 최신순으로 반환."""
    root = _backup_root()
    entries = []
    with _LOCK:
        try:
            dirs = os.listdir(root)
        except Exception:
            return []
        for d in dirs:
            mpath = os.path.join(root, d, 'manifest.json')
            if not os.path.isfile(mpath):
                continue
            try:
                with open(mpath, 'r', encoding='utf-8') as f:
                    entry = json.load(f)
                if isinstance(entry, dict) and entry.get('id'):
                    entries.append(entry)
            except Exception:
                continue  # 손상된 기록은 조용히 건너뜀
    entries.sort(key=lambda e: e.get('created', ''), reverse=True)
    return entries


def get_entry(entry_id):
    mpath = os.path.join(_backup_root(), entry_id, 'manifest.json')
    try:
        with open(mpath, 'r', encoding='utf-8') as f:
            entry = json.load(f)
        return entry if isinstance(entry, dict) else None
    except Exception:
        return None


def file_count(entry):
    return len(entry.get('backed_up', [])) + len(entry.get('moved', []))


def undo_entry(entry_id, log=None):
    """되돌리기 실행.

    Returns:
        (ok: bool, messages: list[str])
        ok=False 면 아무것도 변경되지 않았거나(잠김 등) 심각한 실패.
        ok=True 라도 messages에 부분 실패 안내가 있을 수 있음.
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    with _LOCK:
        entry = get_entry(entry_id)
        if not entry:
            return False, ["기록을 찾을 수 없습니다."]

        bdir = backup_dir_of(entry)
        work_dir = entry.get('work_dir', '')
        archive_dir = entry.get('archive_dir', '')
        merged_file = entry.get('merged_file')
        messages = []

        if not work_dir or not os.path.isdir(work_dir):
            return False, [f"작업 폴더가 없습니다: {work_dir}"]

        archive_exists = bool(archive_dir) and os.path.isdir(archive_dir)

        # ── 1) 사전 점검: 병합 PDF가 열려 있으면 아무것도 하지 않고 중단 ──
        if archive_exists and merged_file:
            merged_path = os.path.join(archive_dir, merged_file)
            if os.path.exists(merged_path):
                try:
                    os.rename(merged_path, merged_path)  # 잠금 검사
                except OSError:
                    return False, ["병합된 PDF가 열려 있습니다.\n파일을 닫고 다시 시도해 주세요."]

        # ── 2) 병합 PDF 삭제 ──
        if archive_exists and merged_file:
            merged_path = os.path.join(archive_dir, merged_file)
            if os.path.exists(merged_path):
                try:
                    os.remove(merged_path)
                    _log(f"[되돌리기] 병합 PDF 삭제: {merged_file}")
                except Exception as e:
                    return False, [f"병합 PDF를 삭제할 수 없습니다: {e}"]

        # ── 3) 백업 원본 → 작업 폴더 복귀 ──
        restored = 0
        for name in entry.get('backed_up', []):
            src = os.path.join(bdir, name)
            dst = os.path.join(work_dir, name)
            if not os.path.exists(src):
                messages.append(f"백업 파일 없음(건너뜀): {name}")
                continue
            if os.path.exists(dst):
                messages.append(f"같은 이름 파일이 이미 있어 건너뜀: {name}")
                continue
            try:
                shutil.move(src, dst)
                restored += 1
            except Exception as e:
                messages.append(f"복구 실패: {name} ({e})")
        if restored:
            _log(f"[되돌리기] 원본 {restored}개 파일 복귀")

        # ── 4) 이동됐던 파일 원위치 ──
        if archive_exists:
            moved_back = 0
            for mv in entry.get('moved', []):
                name = mv.get('name', '')
                src = os.path.join(mv.get('to', ''), name)
                from_dir = mv.get('from', '') or work_dir
                if not os.path.exists(src):
                    continue  # 사용자가 지웠거나 이미 없음
                try:
                    os.makedirs(from_dir, exist_ok=True)
                except Exception:
                    from_dir = work_dir
                dst = os.path.join(from_dir, name)
                if os.path.exists(dst):
                    messages.append(f"같은 이름 파일이 이미 있어 건너뜀: {name}")
                    continue
                try:
                    shutil.move(src, dst)
                    moved_back += 1
                except Exception as e:
                    messages.append(f"원위치 실패: {name} ({e})")
            if moved_back:
                _log(f"[되돌리기] 이동 파일 {moved_back}개 원위치")

            # 정리 폴더가 비었으면 삭제
            try:
                os.rmdir(archive_dir)
                _log(f"[되돌리기] 빈 정리 폴더 삭제: {entry.get('folder_name', '')}")
            except OSError:
                try:
                    leftover = len(os.listdir(archive_dir))
                except Exception:
                    leftover = 0
                if leftover:
                    messages.append(
                        f"정리 폴더에 다른 파일 {leftover}개가 남아 있어 폴더는 유지했습니다.")
        else:
            messages.append(
                "정리 폴더가 이미 이동/삭제되어 원본 파일만 복구했습니다.\n"
                "서버에 올라간 폴더는 직접 정리해 주세요.")

        # ── 5) 별칭 학습 취소 ──
        try:
            from core.match_memory import unlearn_alias
            for pair in entry.get('aliases', []):
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    unlearn_alias(pair[0], pair[1])
                    _log(f"[되돌리기] 별칭 학습 취소: '{pair[0]}' → '{pair[1]}'")
        except Exception:
            pass

        # ── 6) 백업 폴더 제거 (남은 파일 없을 때만 완전 제거) ──
        try:
            remains = [f for f in os.listdir(bdir) if f != 'manifest.json']
        except Exception:
            remains = []
        if remains:
            # 복구 못 한 백업이 남아 있으면 휴지통으로 보내지 않고 보존, manifest만 제거
            try:
                os.remove(os.path.join(bdir, 'manifest.json'))
            except OSError:
                pass
            messages.append(f"복구하지 못한 백업 {len(remains)}개는 data/backups 폴더에 남겨두었습니다.")
        else:
            shutil.rmtree(bdir, ignore_errors=True)

        return True, messages


# ─────────────────────────────────────────────
# 자동 정리 (앱 시작 시 백그라운드 호출)
# ─────────────────────────────────────────────

def _dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def cleanup_old(days=RETENTION_DAYS, max_bytes=MAX_TOTAL_BYTES, log=None):
    """보관 기간이 지난 백업은 휴지통으로. 총 용량 초과 시 오래된 것부터 추가 정리."""
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    root = _backup_root()
    cutoff = datetime.now() - timedelta(days=days)
    with _LOCK:
        entries = []
        try:
            dirs = os.listdir(root)
        except Exception:
            return
        for d in dirs:
            dpath = os.path.join(root, d)
            if not os.path.isdir(dpath):
                continue
            created = None
            mpath = os.path.join(dpath, 'manifest.json')
            try:
                with open(mpath, 'r', encoding='utf-8') as f:
                    created = datetime.fromisoformat(json.load(f).get('created', ''))
            except Exception:
                try:
                    created = datetime.fromtimestamp(os.path.getmtime(dpath))
                except Exception:
                    created = datetime.now()
            entries.append((created, dpath, d))

        # 1) 기간 초과 → 휴지통
        removed = 0
        for created, dpath, name in list(entries):
            if created < cutoff:
                if _send_to_trash(dpath):
                    removed += 1
                    entries.remove((created, dpath, name))
        if removed:
            _log(f"[백업 정리] {days}일 지난 백업 {removed}건 휴지통 이동")

        # 2) 용량 초과 → 오래된 것부터 휴지통
        entries.sort(key=lambda t: t[0])  # 오래된 순
        total = sum(_dir_size(dpath) for _, dpath, _ in entries)
        over_removed = 0
        while total > max_bytes and entries:
            _, dpath, _ = entries.pop(0)
            size = _dir_size(dpath)
            if _send_to_trash(dpath):
                total -= size
                over_removed += 1
        if over_removed:
            _log(f"[백업 정리] 용량 초과로 오래된 백업 {over_removed}건 휴지통 이동")


def cleanup_old_async(log=None):
    threading.Thread(target=cleanup_old, kwargs={'log': log}, daemon=True).start()
