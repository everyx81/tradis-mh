# JARVIS Core - 크래시 안전망
"""
처리되지 않은 예외를 파일로 남기고 앱을 살려 두는 안전망.

PyQt6 는 슬롯·오버라이드(paintEvent, keyPressEvent, 시그널 핸들러 등) 안에서
파이썬 예외가 처리되지 않으면 qFatal() 로 프로세스를 즉시 끝낸다(0xc0000409).
단, sys.excepthook 이 기본값이 아니면 그 훅을 호출하고 실행을 계속하므로,
훅을 설치해 traceback 을 data/logs/crash_YYYY-MM-DD.log 에 기록한다.
창 모드 exe 는 stderr 가 없어 이 파일이 유일한 단서다.

- sys.excepthook      : 메인 스레드(Qt 슬롯 포함)의 미처리 예외
- threading.excepthook: threading.Thread 안의 미처리 예외
- faulthandler        : 접근 위반 등 네이티브 크래시 시 파이썬 스택 덤프
"""

import os
import sys
import time
import datetime
import threading
import traceback

_fault_file = None          # faulthandler 가 붙잡고 있을 파일 핸들 (닫히면 안 됨)
_repeat = {}                # (예외종류, 위치) -> [횟수, 마지막 기록 시각]
_REPEAT_WINDOW_SEC = 60     # 같은 예외는 60초에 한 번만 기록 (타이머 슬롯 반복 대비)
_installed = False


def _base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def crash_log_path():
    log_dir = os.path.join(_base_dir(), 'data', 'logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        pass
    return os.path.join(log_dir, f"crash_{datetime.datetime.now().strftime('%Y-%m-%d')}.log")


def _write(text):
    try:
        with open(crash_log_path(), 'a', encoding='utf-8') as f:
            f.write(text)
            if not text.endswith('\n'):
                f.write('\n')
    except Exception:
        pass
    # 개발 모드(콘솔 실행)에서는 화면에도 표시
    try:
        err = sys.__stderr__
        if err is not None:
            err.write(text)
            err.flush()
    except Exception:
        pass


def _location(tb):
    """traceback 의 마지막 프레임 'file:line' (반복 판정 키)."""
    try:
        frames = traceback.extract_tb(tb)
        if frames:
            last = frames[-1]
            return f"{os.path.basename(last.filename)}:{last.lineno}"
    except Exception:
        pass
    return "?"


def _should_write(exc_type, tb):
    key = (getattr(exc_type, '__name__', str(exc_type)), _location(tb))
    now = time.time()
    entry = _repeat.get(key)
    if entry is None:
        _repeat[key] = [1, now]
        return True, 0
    entry[0] += 1
    if now - entry[1] >= _REPEAT_WINDOW_SEC:
        skipped = entry[0] - 1
        entry[0] = 1
        entry[1] = now
        return True, skipped
    return False, 0


def _record(kind, exc_type, exc, tb, thread_name=None):
    try:
        ok, skipped = _should_write(exc_type, tb)
        if not ok:
            return
        stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        head = f"\n===== [{stamp}] {kind}"
        if thread_name:
            head += f" (thread: {thread_name})"
        if skipped:
            head += f" — 같은 예외 {skipped}회 생략"
        body = ''.join(traceback.format_exception(exc_type, exc, tb))
        _write(head + "\n" + body)
    except Exception:
        pass


def _sys_hook(exc_type, exc, tb):
    _record("미처리 예외", exc_type, exc, tb)


def _thread_hook(args):
    _record("스레드 미처리 예외", args.exc_type, args.exc_value, args.exc_traceback,
            thread_name=getattr(args.thread, 'name', None))


def install():
    """앱 시작 시 1회 호출. 실패해도 앱 실행에는 영향 없음."""
    global _installed, _fault_file
    if _installed:
        return
    _installed = True
    sys.excepthook = _sys_hook
    try:
        threading.excepthook = _thread_hook
    except Exception:
        pass
    try:
        import faulthandler
        _fault_file = open(crash_log_path(), 'a', encoding='utf-8')
        faulthandler.enable(file=_fault_file, all_threads=True)
    except Exception:
        _fault_file = None
