@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Auto Seedvis - Cai dat Moi Truong
color 0B

echo ====================================================================
echo    CAI DAT MOI TRUONG CHO PHAN MEM SEEDVIS (STANDALONE)
echo ====================================================================
echo.

echo [1/4] Kiem tra Python...
set PYTHON_EXE=python
%PYTHON_EXE% --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [WARN] Khong tim thay Python trong PATH! Dang thu dung winget...
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo   [FAIL] Khong the cai Python tu dong.
        echo   Vui long tai Python 3.10+ tai https://www.python.org/
        echo   NHO TICH VAO "Add Python to PATH" KHI CAI!
        pause
        exit /b 1
    )
)
for /f "tokens=*" %%V in ('%PYTHON_EXE% --version 2^>^&1') do echo   [OK] %%V

echo.
echo [2/4] Nang cap pip...
%PYTHON_EXE% -m pip install --upgrade pip --quiet
if %errorlevel% neq 0 (echo   [WARN] Khong the upgrade pip) else (echo   [OK] Pip da duoc nang cap)

echo.
echo [3/4] Dang cai dat cac thu vien Python...
%PYTHON_EXE% -m pip install customtkinter pillow pystray edge-tts google-genai google-generativeai groq
if %errorlevel% neq 0 (
    echo   [WARN] Co loi, dang thu cai le tung thu vien...
    for %%P in (customtkinter pillow pystray edge-tts google-genai google-generativeai groq) do (
        %PYTHON_EXE% -m pip install %%P
    )
)
echo   [OK] Thu vien Python da duoc cai dat.

echo.
echo [4/4] Kiem tra FFmpeg (Bat buoc de ghep Video)...
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] FFmpeg da duoc cai dat va co trong PATH.
) else (
    echo   [WARN] FFmpeg CHUA CO trong PATH! Dang cai bang winget...
    winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
    if %errorlevel% equ 0 (
        echo   [OK] FFmpeg da cai thanh cong qua winget!
    ) else (
        echo   [FAIL] Khong the cai FFmpeg tu dong.
        echo   Vui long tai FFmpeg tu https://www.gyan.dev/ffmpeg/builds/
        echo   Giai nen vao C:\ffmpeg\bin roi them vao PATH.
    )
)

echo.
echo [Kiem tra] Diagnostic thu vien...
%PYTHON_EXE% -c "import customtkinter, PIL, pystray, edge_tts, groq; print('   [OK] 5/7 thu vien co ban OK')" 2>nul
%PYTHON_EXE% -c "from google import genai; print('   [OK] google-genai OK')" 2>nul

echo.
echo ====================================================================
color 0A
echo    CAI DAT MOI TRUONG HOAN TAT!
echo ====================================================================
echo    De chay phan mem: Nhan kep vao file run_seedvis.bat
echo.
pause
