"""
TRADIS MH 자동 업데이트 모듈
GitHub Releases API를 통해 최신 버전 확인 및 업데이트 수행
"""

import os
import sys
import json
import subprocess
import tempfile
import threading
from urllib import request, error

from version import __version__, APP_NAME, GITHUB_REPO


GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def get_current_exe_path():
    """현재 실행 중인 EXE 경로 반환"""
    if getattr(sys, 'frozen', False):
        return sys.executable
    return None


def check_for_update():
    """
    GitHub Releases에서 최신 버전 확인.
    Returns:
        dict: {"available": bool, "version": str, "download_url": str, "notes": str}
    """
    try:
        req = request.Request(GITHUB_API_URL, headers={"Accept": "application/vnd.github.v3+json"})
        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        latest_version = data.get("tag_name", "").lstrip("v")
        notes = data.get("body", "")

        # EXE 다운로드 URL 찾기
        download_url = None
        for asset in data.get("assets", []):
            if asset["name"].lower().endswith(".exe"):
                download_url = asset["browser_download_url"]
                break

        if not latest_version or not download_url:
            return {"available": False, "version": __version__, "download_url": None, "notes": ""}

        if _version_compare(latest_version, __version__) > 0:
            return {
                "available": True,
                "version": latest_version,
                "download_url": download_url,
                "notes": notes,
            }
        return {"available": False, "version": __version__, "download_url": None, "notes": ""}

    except Exception as e:
        print(f"[업데이트 확인 실패] {e}")
        return {"available": False, "version": __version__, "download_url": None, "notes": "", "error": str(e)}


def download_update(download_url, progress_callback=None):
    """
    새 EXE 다운로드.
    Args:
        download_url: 다운로드 URL
        progress_callback: func(downloaded_bytes, total_bytes) 진행 콜백
    Returns:
        str: 다운로드된 임시 파일 경로, 실패 시 None
    """
    try:
        req = request.Request(download_url)
        with request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".exe", prefix="tradis_update_")
            tmp_path = tmp.name

            downloaded = 0
            block_size = 65536
            while True:
                chunk = resp.read(block_size)
                if not chunk:
                    break
                tmp.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)
            tmp.close()
        return tmp_path
    except Exception as e:
        print(f"[다운로드 실패] {e}")
        return None


def apply_update(new_exe_path):
    """
    현재 EXE를 새 EXE로 교체하고 재시작.
    bat 스크립트를 통해 실행 중인 EXE 교체.
    """
    current_exe = get_current_exe_path()
    if not current_exe:
        print("[업데이트] EXE 모드가 아닙니다.")
        return False

    # bat 스크립트로 교체 수행 (현재 프로세스 종료 후 교체 → 재시작)
    bat_content = f'''@echo off
chcp 65001 >nul
echo TRADIS MH 업데이트 중...
timeout /t 2 /nobreak >nul
:retry
del "{current_exe}" 2>nul
if exist "{current_exe}" (
    timeout /t 1 /nobreak >nul
    goto retry
)
move /Y "{new_exe_path}" "{current_exe}"
if errorlevel 1 (
    echo 업데이트 실패
    pause
    exit /b 1
)
echo 업데이트 완료. 재시작합니다...
start "" "{current_exe}"
del "%~f0"
'''
    bat_path = os.path.join(tempfile.gettempdir(), "tradis_update.bat")
    with open(bat_path, 'w', encoding='utf-8') as f:
        f.write(bat_content)

    # bat 실행 (현재 프로세스와 독립적으로)
    subprocess.Popen(
        ['cmd', '/c', bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True
    )
    return True


def _version_compare(v1, v2):
    """버전 비교. v1 > v2이면 양수, 같으면 0, 작으면 음수"""
    def parse(v):
        return [int(x) for x in v.split('.')]
    try:
        parts1 = parse(v1)
        parts2 = parse(v2)
        for a, b in zip(parts1, parts2):
            if a != b:
                return a - b
        return len(parts1) - len(parts2)
    except (ValueError, AttributeError):
        return 0
