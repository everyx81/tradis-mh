# JARVIS GUI 유틸리티 함수
"""
GUI 유틸리티 함수:
- resource_path: 리소스 절대 경로 반환
- get_run_dir: 실행 파일 디렉토리 반환
"""

import os
import sys

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def get_run_dir():
    """ Get directory where the executable (or script) is running """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # gui 패키지 내부에 있으므로, 상위 디렉토리(프로젝트 루트)를 반환
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─────────────────────────────────────────────────
# QThread 수명 보호
# 실행 중인 QThread 의 C++ 객체가 소멸되면 Qt 가 qFatal 로 프로세스를 끝낸다
# ("QThread: Destroyed while thread is still running", 0xc0000409).
# 카드 재구성·gc.collect 로 워커를 들고 있던 파이썬 객체가 사라져도 스레드가
# 끝날 때까지 여기서 참조를 붙든다.
# ※ 워커는 QThread 자체의 finished 시그널을 가려서는 안 된다
#   (커스텀 결과 시그널은 result_ready 등 다른 이름 사용).
# ─────────────────────────────────────────────────
_LIVE_THREADS = set()


def keep_thread_alive(thread):
    """start() 직전에 호출. 스레드가 끝나면 자동으로 놓아준다."""
    _LIVE_THREADS.add(thread)

    def _release():
        try:
            thread.wait(2000)
        except RuntimeError:
            pass
        _LIVE_THREADS.discard(thread)
        try:
            thread.deleteLater()
        except RuntimeError:
            pass

    thread.finished.connect(_release)


def wait_live_threads(timeout_ms=3000):
    """앱 종료 직전에 호출. 실행 중인 워커를 기다려 실행 중 파괴를 막는다."""
    for t in list(_LIVE_THREADS):
        try:
            if t.isRunning():
                t.wait(timeout_ms)
        except RuntimeError:
            pass

