@echo off
chcp 65001 > nul
echo ============================================================
echo JARVIS AI Assistant - 빌드 스크립트
echo ============================================================
echo.

REM 시작 시간 기록
set START_TIME=%TIME%

echo [1/4] 이전 빌드 정리 중...
if exist "dist\JARVIS_AI_Assistant.exe" del /q "dist\JARVIS_AI_Assistant.exe"

echo [2/4] PyInstaller 설치 확인 중...
python -m PyInstaller --version > nul 2>&1
if errorlevel 1 (
    echo      PyInstaller가 설치되어 있지 않습니다. 설치 중...
    pip install pyinstaller
)

echo [3/4] PyInstaller 빌드 시작...
echo      (이 과정은 2-5분 정도 소요됩니다)
echo.

REM 빌드 실행 (python -m 으로 실행하여 PATH 문제 해결)
python -m PyInstaller JARVIS_AI_Assistant.spec --noconfirm > build_log.txt 2>&1

REM 빌드 결과 확인
if exist "dist\JARVIS_AI_Assistant.exe" (
    echo.
    echo [4/4] 빌드 성공!
    echo.
    for %%I in ("dist\JARVIS_AI_Assistant.exe") do (
        echo      파일: dist\JARVIS_AI_Assistant.exe
        echo      크기: %%~zI bytes
    )
    echo.
    echo ============================================================
    echo 빌드 완료! 실행하려면:
    echo   dist\JARVIS_AI_Assistant.exe
    echo ============================================================
) else (
    echo.
    echo [오류] 빌드 실패!
    echo       상세 로그: build_log.txt
    echo.
    echo 마지막 20줄 오류 로그:
    echo ------------------------------------------------------------
    powershell -Command "Get-Content build_log.txt -Tail 20"
    echo ------------------------------------------------------------
)

echo.
echo 종료 시간: %TIME%
echo 시작 시간: %START_TIME%
echo.
pause
