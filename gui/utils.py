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

