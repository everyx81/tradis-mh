@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   TRADIS MH 빌드 및 GitHub 릴리즈
echo ============================================
echo.

REM gh CLI 경로 설정
set "GH=gh"
if exist "C:\Program Files\GitHub CLI\gh.exe" set "GH=C:\Program Files\GitHub CLI\gh.exe"

REM version.py에서 버전 읽기
for /f "tokens=2 delims='= " %%a in ('findstr "__version__" version.py') do set VERSION=%%~a
echo [1/6] 현재 버전: v%VERSION%
echo.

REM 릴리즈 노트 입력 (커밋 메시지로도 사용)
set /p NOTES="릴리즈 노트 (Enter로 건너뛰기): "
if "%NOTES%"=="" set NOTES=v%VERSION% 릴리즈
echo.

REM git 상태 확인 후 소스 커밋
echo [2/6] git 커밋 중...
git add -A
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "v%VERSION%: %NOTES%"
    if errorlevel 1 (
        echo git commit 실패!
        pause
        exit /b 1
    )
) else (
    echo 커밋할 변경사항 없음 ^(이미 커밋됨^)
)
echo.

REM 태그 생성 (이미 있으면 재사용)
echo [3/6] git 태그 v%VERSION% 생성 중...
git tag -l v%VERSION% | findstr "v%VERSION%" >nul
if errorlevel 1 (
    git tag v%VERSION%
) else (
    echo 태그 v%VERSION% 이미 존재 ^(건너뜀^)
)
echo.

REM 원격 push
echo [4/6] origin/main + 태그 push 중...
git push origin main
if errorlevel 1 (
    echo git push 실패!
    pause
    exit /b 1
)
git push origin v%VERSION%
if errorlevel 1 (
    echo 태그 push 실패!
    pause
    exit /b 1
)
echo.

REM PyInstaller 빌드
echo [5/6] PyInstaller 빌드 중...
pyinstaller JARVIS_AI_Assistant.spec --noconfirm
if errorlevel 1 (
    echo 빌드 실패!
    pause
    exit /b 1
)
echo 빌드 완료: dist\TRADIS_MH.exe
echo.

REM GitHub Release 생성
echo [6/6] GitHub Release 생성 중...
"%GH%" release create v%VERSION% "dist\TRADIS_MH.exe" --title "v%VERSION%" --notes "%NOTES%"
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
