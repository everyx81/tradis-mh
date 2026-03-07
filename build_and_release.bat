@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   TRADIS MH 빌드 및 GitHub 릴리즈
echo ============================================
echo.

REM version.py에서 버전 읽기
for /f "tokens=2 delims='= " %%a in ('findstr "__version__" version.py') do set VERSION=%%~a
echo [1/3] 현재 버전: v%VERSION%
echo.

REM PyInstaller 빌드
echo [2/3] PyInstaller 빌드 중...
pyinstaller JARVIS_AI_Assistant.spec --noconfirm
if errorlevel 1 (
    echo 빌드 실패!
    pause
    exit /b 1
)
echo 빌드 완료: dist\TRADIS_MH.exe
echo.

REM GitHub Release 생성
echo [3/3] GitHub Release 생성 중...
set /p NOTES="릴리즈 노트 (Enter로 건너뛰기): "
if "%NOTES%"=="" set NOTES=v%VERSION% 릴리즈

gh release create v%VERSION% "dist\TRADIS_MH.exe" --title "v%VERSION%" --notes "%NOTES%"
if errorlevel 1 (
    echo GitHub 릴리즈 실패! gh CLI가 설치되어 있고 로그인되어 있는지 확인하세요.
    echo   설치: winget install GitHub.cli
    echo   로그인: gh auth login
    pause
    exit /b 1
)

echo.
echo ============================================
echo   v%VERSION% 릴리즈 완료!
echo ============================================
pause
