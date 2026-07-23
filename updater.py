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


def apply_update(new_exe_path, new_version=None):
    """
    인스톨러 스타일 업데이트.
    PowerShell WinForms 창(Claude Design·단계 체크리스트)으로 진행 상황을
    표시하며 EXE 교체 후 안내.
    """
    current_exe = get_current_exe_path()
    if not current_exe:
        print("[업데이트] EXE 모드가 아닙니다.")
        return False

    pid = os.getpid()
    # 현재 실행 중인 _MEI 경로 (PyInstaller onefile 전용)
    mei_path = getattr(sys, '_MEIPASS', '')
    # PowerShell 단일 따옴표 이스케이프
    esc_new = new_exe_path.replace("'", "''")
    esc_cur = current_exe.replace("'", "''")
    esc_mei = mei_path.replace("'", "''")
    title_text = f"v{new_version} 업데이트" if new_version else f"{APP_NAME} 업데이트"

    # 업데이트 창 (시안 D-1): Claude Design 카드 + 실제 앱 아이콘 + 단계 체크리스트
    # 한글은 -EncodedCommand(UTF-16LE)로 전달되므로 리터럴 그대로 사용 가능
    ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# ── Claude Design 팔레트 (gui/claude_theme.py 와 동일) ──
$cBg     = [Drawing.Color]::FromArgb(20, 23, 29)
$cBorder = [Drawing.Color]::FromArgb(52, 55, 64)
$cFg     = [Drawing.Color]::FromArgb(248, 250, 252)
$cGray   = [Drawing.Color]::FromArgb(106, 110, 118)
$cBlue   = [Drawing.Color]::FromArgb(94, 189, 255)
$cGreen  = [Drawing.Color]::FromArgb(89, 200, 134)
$cRed    = [Drawing.Color]::FromArgb(250, 104, 99)

# ── 창 (1px 보더: 폼 배경=보더색 + 1px 패딩 위 패널) ──
$f = New-Object Windows.Forms.Form
$f.Text = "TRADIS MH"
$f.ClientSize = New-Object Drawing.Size(340, 224)
$f.StartPosition = "CenterScreen"
$f.FormBorderStyle = "None"
$f.BackColor = $cBorder
$f.Padding = New-Object Windows.Forms.Padding(1)
$f.TopMost = $true
$f.ShowInTaskbar = $true

$panel = New-Object Windows.Forms.Panel
$panel.Dock = "Fill"
$panel.BackColor = $cBg
$f.Controls.Add($panel)

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

# ── 헤더: 앱 아이콘(작업표시줄과 동일한 EXE 내장 아이콘) + 제목 ──
$icoBox = New-Object Windows.Forms.PictureBox
$icoBox.Size = New-Object Drawing.Size(28, 28)
$icoBox.Location = New-Object Drawing.Point(22, 18)
$icoBox.SizeMode = "Zoom"
$icoBox.BackColor = $cBg
try {{
    $ico = [System.Drawing.Icon]::ExtractAssociatedIcon('{esc_cur}')
    if ($ico) {{ $icoBox.Image = $ico.ToBitmap() }}
}} catch {{}}
$panel.Controls.Add($icoBox)

$lbl = New-Object Windows.Forms.Label
$lbl.Text = "{title_text}"
$lbl.ForeColor = $cFg
$lbl.Font = New-Object Drawing.Font("Malgun Gothic", 11, [Drawing.FontStyle]::Bold)
$lbl.AutoSize = $false
$lbl.Size = New-Object Drawing.Size(250, 28)
$lbl.Location = New-Object Drawing.Point(58, 18)
$lbl.TextAlign = "MiddleLeft"
$lbl.BackColor = $cBg
$panel.Controls.Add($lbl)

# ── 단계 체크리스트 ──
$steps = @()
$stepNames = @("프로그램 종료", "파일 교체", "임시 파일 정리", "완료")
for ($i = 0; $i -lt 4; $i++) {{
    $s = New-Object Windows.Forms.Label
    $s.Text = "○  " + $stepNames[$i]
    $s.ForeColor = $cGray
    $s.Font = New-Object Drawing.Font("Consolas", 10.5)
    $s.AutoSize = $false
    $s.Size = New-Object Drawing.Size(300, 26)
    $s.Location = New-Object Drawing.Point(24, (64 + $i * 32))
    $s.BackColor = $cBg
    $panel.Controls.Add($s)
    $steps += $s
}}

function Set-Step($idx, $mark, $color, $text) {{
    $steps[$idx].Text = $mark + "  " + $text
    $steps[$idx].ForeColor = $color
    [Windows.Forms.Application]::DoEvents()
}}

$f.Show()
[Windows.Forms.Application]::DoEvents()

# ── Phase 1: 프로세스 종료 대기 ──
Set-Step 0 "▸" $cBlue "프로그램 종료 대기 중..."

for ($i = 0; $i -lt 30; $i++) {{
    $proc = Get-Process -Id {pid} -ErrorAction SilentlyContinue
    if (-not $proc -or $proc.HasExited) {{ break }}
    Start-Sleep -Milliseconds 500
    [Windows.Forms.Application]::DoEvents()
}}
# 15초 후에도 살아있으면 강제 종료.
# PyInstaller 부트로더가 _MEI 삭제 실패 시 "Failed to remove temporary directory"
# 모달 경고창을 띄우고 확인을 누를 때까지 프로세스가 붙잡혀 EXE 교체가 영원히
# 실패하는 케이스 방지. 이 시점엔 저장·종료 처리가 모두 끝난 뒤라 안전하다.
$proc = Get-Process -Id {pid} -ErrorAction SilentlyContinue
if ($proc -and -not $proc.HasExited) {{
    Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}}
Start-Sleep -Seconds 1
Set-Step 0 "✓" $cGreen "프로그램 종료"

# ── Phase 2: 파일 교체 ──
Set-Step 1 "▸" $cBlue "파일 교체 중..."

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
    Set-Step 1 "✓" $cGreen "파일 교체"

    # ── Phase 3: 잔여 _MEI 폴더 정리 ──
    Set-Step 2 "▸" $cBlue "임시 파일 정리 중..."

    $meiPass = '{esc_mei}'
    if ($meiPass -and (Test-Path $meiPass)) {{
        Remove-Item $meiPass -Recurse -Force -ErrorAction SilentlyContinue
    }}
    $meiDirs = @([System.IO.Path]::GetTempPath(), 'C:\\ProgramData\\TRADIS_TMP')
    foreach ($d in $meiDirs) {{
        if (Test-Path $d) {{
            Get-ChildItem -Path $d -Directory -Filter "_MEI*" -ErrorAction SilentlyContinue | ForEach-Object {{
                try {{ Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }} catch {{}}
            }}
        }}
    }}

    Remove-Item -LiteralPath '{esc_new}' -Force -ErrorAction SilentlyContinue
    Set-Step 2 "✓" $cGreen "임시 파일 정리"

    # 자동 재시작 대신 안내 메시지 표시
    Set-Step 3 "✓" $cBlue "완료! 다시 실행해 주세요."
    Start-Sleep -Seconds 5
}} else {{
    Set-Step 1 "✗" $cRed "파일 교체 실패"
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

        # cwd를 temp로 지정 — 자식 프로세스가 앱의 작업 디렉토리(_MEI 내부일 가능성)를
        # 물려받아 _MEI 삭제를 막는 것 방지
        subprocess.Popen(
            ['powershell', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encoded],
            startupinfo=si,
            cwd=tempfile.gettempdir()
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
    mei_short = _get_short_path(getattr(sys, '_MEIPASS', ''))

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
    REM 10초 넘게 잠겨 있으면 _MEI 삭제 실패 경고창에 붙잡힌 프로세스로 보고 강제 종료
    if %RETRIES% EQU 10 taskkill /F /PID {os.getpid()} >nul 2>nul
    timeout /t 1 /nobreak >nul
    goto retry
)
echo   Cleaning up temp files...
if exist "{mei_short}" rd /s /q "{mei_short}" 2>nul
for /d %%D in ("C:\\ProgramData\\TRADIS_TMP\\_MEI*") do rd /s /q "%%D" 2>nul
for /d %%D in ("%TEMP%\\_MEI*") do rd /s /q "%%D" 2>nul
timeout /t 2 /nobreak >nul
del "{new_short}" 2>nul
echo   Update complete!
echo.
echo   Please restart the program manually.
echo.
pause
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
