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
import base64
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
    tmp_path = None
    try:
        req = request.Request(download_url, headers={
            "User-Agent": f"{APP_NAME}/{__version__}",
            "Accept": "application/octet-stream",
        })
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

        # 파일 크기 검증 (최소 1MB, Content-Length 일치)
        file_size = os.path.getsize(tmp_path)
        if file_size < 1_000_000:
            print(f"[다운로드 실패] 파일 크기 비정상: {file_size} bytes")
            _safe_delete(tmp_path)
            return None
        if total > 0 and file_size != total:
            print(f"[다운로드 실패] 크기 불일치: {file_size} != {total}")
            _safe_delete(tmp_path)
            return None

        return tmp_path
    except Exception as e:
        print(f"[다운로드 실패] {type(e).__name__}: {e}")
        _safe_delete(tmp_path)
        return None


def apply_update(new_exe_path):
    """
    인스톨러 스타일 업데이트.
    PowerShell WinForms 창으로 진행 상황을 표시하며 EXE 교체 후 재시작.
    """
    current_exe = get_current_exe_path()
    if not current_exe:
        print("[업데이트] EXE 모드가 아닙니다.")
        return False

    pid = os.getpid()
    # PowerShell 단일 따옴표 이스케이프
    esc_new = new_exe_path.replace("'", "''")
    esc_cur = current_exe.replace("'", "''")

    ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ── 업데이트 창 ──
$f = New-Object Windows.Forms.Form
$f.Text = "TRADIS MH"
$f.ClientSize = New-Object Drawing.Size(400, 160)
$f.StartPosition = "CenterScreen"
$f.FormBorderStyle = "None"
$f.BackColor = [Drawing.Color]::FromArgb(20, 25, 38)
$f.TopMost = $true
$f.ShowInTaskbar = $true

# Windows 11 둥근 모서리
try {{
    Add-Type @"
using System; using System.Runtime.InteropServices;
public class DwmRound {{
    [DllImport("dwmapi.dll")]
    public static extern int DwmSetWindowAttribute(IntPtr h, int a, ref int v, int s);
}}
"@
    $v = 2
    [DwmRound]::DwmSetWindowAttribute($f.Handle, 33, [ref]$v, 4) | Out-Null
}} catch {{}}

# 타이틀
$lbl = New-Object Windows.Forms.Label
$lbl.Text = "TRADIS MH"
$lbl.ForeColor = [Drawing.Color]::FromArgb(0, 229, 255)
$lbl.Font = New-Object Drawing.Font("Segoe UI", 16, [Drawing.FontStyle]::Bold)
$lbl.TextAlign = "MiddleCenter"
$lbl.AutoSize = $false
$lbl.Size = New-Object Drawing.Size(400, 40)
$lbl.Location = New-Object Drawing.Point(0, 20)
$lbl.BackColor = [Drawing.Color]::Transparent
$f.Controls.Add($lbl)

# 상태 텍스트
$st = New-Object Windows.Forms.Label
$st.Text = ""
$st.ForeColor = [Drawing.Color]::FromArgb(160, 165, 175)
$st.Font = New-Object Drawing.Font("Segoe UI", 10)
$st.TextAlign = "MiddleCenter"
$st.AutoSize = $false
$st.Size = New-Object Drawing.Size(400, 30)
$st.Location = New-Object Drawing.Point(0, 65)
$st.BackColor = [Drawing.Color]::Transparent
$f.Controls.Add($st)

# 프로그레스 바
$pb = New-Object Windows.Forms.ProgressBar
$pb.Location = New-Object Drawing.Point(40, 120)
$pb.Size = New-Object Drawing.Size(320, 6)
$pb.Style = "Marquee"
$pb.MarqueeAnimationSpeed = 25
$f.Controls.Add($pb)

$f.Show()
[Windows.Forms.Application]::DoEvents()

# ── Phase 1: 프로세스 종료 대기 ──
$st.Text = [char]0xD504 + [char]0xB85C + [char]0xC138 + [char]0xC2A4 + " " + [char]0xC885 + [char]0xB8CC + " " + [char]0xB300 + [char]0xAE30 + " " + [char]0xC911 + "..."
[Windows.Forms.Application]::DoEvents()

for ($i = 0; $i -lt 60; $i++) {{
    $proc = Get-Process -Id {pid} -ErrorAction SilentlyContinue
    if (-not $proc -or $proc.HasExited) {{ break }}
    Start-Sleep -Milliseconds 500
    [Windows.Forms.Application]::DoEvents()
}}
Start-Sleep -Seconds 1
[Windows.Forms.Application]::DoEvents()

# ── Phase 2: 파일 교체 ──
$st.Text = [char]0xD30C + [char]0xC77C + " " + [char]0xAD50 + [char]0xCCB4 + " " + [char]0xC911 + "..."
[Windows.Forms.Application]::DoEvents()

$ok = $false
for ($r = 0; $r -lt 20; $r++) {{
    try {{
        Copy-Item -LiteralPath '{esc_new}' -Destination '{esc_cur}' -Force
        $ok = $true
        break
    }} catch {{
        Start-Sleep -Seconds 1
        [Windows.Forms.Application]::DoEvents()
    }}
}}

if ($ok) {{
    # ── Phase 3: 잔여 _MEI 폴더 정리 후 재시작 ──
    $st.Text = [char]0xC644 + [char]0xB8CC + "! " + [char]0xC7AC + [char]0xC2DC + [char]0xC791 + " " + [char]0xC911 + "..."
    $pb.Style = "Continuous"
    $pb.Value = 100
    [Windows.Forms.Application]::DoEvents()

    # PyInstaller 임시 폴더(_MEI*) 정리
    # os._exit()로 강제 종료 시 _MEI 폴더가 불완전하게 남아
    # 새 EXE 실행 시 python312.dll 로드 실패를 유발할 수 있음
    # runtime_tmpdir = C:\ProgramData\TRADIS_TMP (spec 설정)
    $meiDirs = @('C:\ProgramData\TRADIS_TMP', [System.IO.Path]::GetTempPath())
    foreach ($d in $meiDirs) {{
        if (Test-Path $d) {{
            Get-ChildItem -Path $d -Directory -Filter "_MEI*" -ErrorAction SilentlyContinue | ForEach-Object {{
                try {{ Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }} catch {{}}
            }}
        }}
    }}
    Start-Sleep -Seconds 2

    Start-Process -FilePath '{esc_cur}'
    Remove-Item -LiteralPath '{esc_new}' -Force -ErrorAction SilentlyContinue
}} else {{
    $st.Text = [char]0xC5C5 + [char]0xB370 + [char]0xC774 + [char]0xD2B8 + " " + [char]0xC2E4 + [char]0xD328
    $st.ForeColor = [Drawing.Color]::FromArgb(255, 100, 100)
    $pb.Style = "Continuous"
    $pb.Value = 0
    [Windows.Forms.Application]::DoEvents()
    Start-Sleep -Seconds 3
}}

$f.Close()
'''

    # UTF-16LE Base64 인코딩 → -EncodedCommand (한글 경로 완벽 지원)
    encoded = base64.b64encode(ps_script.encode('utf-16-le')).decode('ascii')

    # PowerShell 실행 시도 (콘솔 창 숨김, WinForms 업데이트 창만 표시)
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE

        subprocess.Popen(
            ['powershell', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded],
            startupinfo=si
        )
        return True
    except FileNotFoundError:
        # PowerShell 미설치 또는 차단 → bat 폴백
        print("[업데이트] PowerShell 사용 불가 → bat 폴백")
        return _apply_update_bat(new_exe_path, current_exe)


def _apply_update_bat(new_exe_path, current_exe):
    """폴백: bat 스크립트로 EXE 교체 (PowerShell 없는 환경용)"""
    current_short = _get_short_path(current_exe)
    new_short = _get_short_path(new_exe_path)

    bat_content = f'''@echo off
chcp 65001 >nul 2>nul
echo.
echo   TRADIS MH Updating...
echo.
timeout /t 3 /nobreak >nul
set RETRIES=0
:retry
copy /Y "{new_short}" "{current_short}" >nul 2>nul
if errorlevel 1 (
    set /a RETRIES+=1
    if %RETRIES% GEQ 20 (
        echo   Update failed - EXE still locked
        pause
        exit /b 1
    )
    timeout /t 1 /nobreak >nul
    goto retry
)
echo   Cleaning up temp files...
for /d %%D in ("C:\\ProgramData\\TRADIS_TMP\\_MEI*") do rd /s /q "%%D" 2>nul
for /d %%D in ("%TEMP%\\_MEI*") do rd /s /q "%%D" 2>nul
timeout /t 2 /nobreak >nul
echo   Update complete! Restarting...
start "" "{current_short}"
del "{new_short}" 2>nul
del "%~f0"
'''
    bat_path = os.path.join(tempfile.gettempdir(), "tradis_update.bat")
    with open(bat_path, 'w', encoding='mbcs') as f:
        f.write(bat_content)

    # bat를 콘솔 창과 함께 실행 (시각적 피드백)
    subprocess.Popen(
        ['cmd', '/c', bat_path],
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    return True


def _safe_delete(path):
    """임시 파일 안전 삭제"""
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def _get_short_path(long_path):
    """Windows short path (8.3) 변환 - 한글 경로 문제 방지"""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        result = ctypes.windll.kernel32.GetShortPathNameW(long_path, buf, 512)
        if result > 0 and buf.value:
            return buf.value
        # 8.3 비활성화 시 원본 경로 반환 (bat에서 큰따옴표로 감싸져 있으므로 동작)
        return long_path
    except Exception:
        return long_path


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
