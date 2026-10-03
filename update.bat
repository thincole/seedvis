@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Thin Aptm - Cập Nhật Seedvis Từ GitHub
color 0B

echo ====================================================================
echo    CẬP NHẬT PHIÊN BẢN MỚI SEEDVIS TỪ GITHUB
echo    Kho lưu trữ: https://github.com/thincole/seedvis
echo ====================================================================
echo.

:: 1. Tự động đóng phần mềm nếu đang chạy ngầm để không bị lỗi khóa file (File Lock)
echo [*] Đang kiểm tra và đóng tiến trình Seedvis cũ (nếu đang chạy)...
taskkill /f /fi "WINDOWTITLE eq Thin Aptm*" >nul 2>&1
taskkill /f /im Seedvis.exe >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*seedvis_app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

:: 2. Sao lưu file cấu hình cài đặt người dùng vào thư mục Temp an toàn
set "SETTINGS_BAK=%TEMP%\seedvis_settings_backup_%RANDOM%.json"
if exist "seedvis_settings.json" (
    echo [*] Đang sao lưu cấu hình cá nhân (API Key, Client ID...)...
    copy /y "seedvis_settings.json" "%SETTINGS_BAK%" >nul 2>&1
)

:: 3. Tiến hành cập nhật mã nguồn
set UPDATE_SUCCESS=0

where git >nul 2>&1
if %errorlevel% equ 0 (
    echo [*] Đã tìm thấy Git. Tiến hành cập nhật qua Git...
    
    :: Thêm safe.directory để tránh lỗi phân quyền (dubious ownership) trên Windows
    git config --global --add safe.directory "%~dp0" >nul 2>&1
    git config --global --add safe.directory * >nul 2>&1

    if not exist ".git" (
        echo [*] Khởi tạo Git repository liên kết với GitHub...
        git -c safe.directory=* init >nul 2>&1
        git -c safe.directory=* remote add origin https://github.com/thincole/seedvis.git >nul 2>&1
    ) else (
        git -c safe.directory=* remote set-url origin https://github.com/thincole/seedvis.git >nul 2>&1
    )

    echo [*] Đang tải mã nguồn mới nhất từ nhánh main...
    git -c safe.directory=* fetch origin main
    if %errorlevel% equ 0 (
        git -c safe.directory=* checkout -B main origin/main >nul 2>&1
        git -c safe.directory=* reset --hard origin/main
        if %errorlevel% equ 0 (
            git -c safe.directory=* clean -fd -e seedvis_settings.json >nul 2>&1
            set UPDATE_SUCCESS=1
        )
    )
)

:: Nếu máy không có Git hoặc Git kéo lỗi, tải trực tiếp ZIP từ GitHub
if %UPDATE_SUCCESS% neq 1 (
    echo.
    echo [*] Đang tải bản cập nhật trực tiếp từ GitHub (ZIP fallback)...
    set "ZIP_TEMP=%TEMP%\seedvis_main_%RANDOM%.zip"
    set "DIR_TEMP=%TEMP%\seedvis_extract_%RANDOM%"

    where curl.exe >nul 2>&1
    if %errorlevel% equ 0 (
        curl.exe -L -s -o "%ZIP_TEMP%" "https://github.com/thincole/seedvis/archive/refs/heads/main.zip"
    ) else (
        powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://github.com/thincole/seedvis/archive/refs/heads/main.zip', '%ZIP_TEMP%')"
    )

    if exist "%ZIP_TEMP%" (
        echo [*] Đang giải nén bản cập nhật...
        powershell -NoProfile -Command "Expand-Archive -Path '%ZIP_TEMP%' -DestinationPath '%DIR_TEMP%' -Force"
        if exist "%DIR_TEMP%\seedvis-main" (
            powershell -NoProfile -Command "Copy-Item -Path '%DIR_TEMP%\seedvis-main\*' -Destination '.\' -Recurse -Force"
            rmdir /s /q "%DIR_TEMP%" >nul 2>&1
            del /f /q "%ZIP_TEMP%" >nul 2>&1
            set UPDATE_SUCCESS=1
        ) else (
            rmdir /s /q "%DIR_TEMP%" >nul 2>&1
            del /f /q "%ZIP_TEMP%" >nul 2>&1
        )
    )
)

:: 4. Khôi phục lại file cấu hình người dùng
if exist "%SETTINGS_BAK%" (
    copy /y "%SETTINGS_BAK%" "seedvis_settings.json" >nul 2>&1
    del /f /q "%SETTINGS_BAK%" >nul 2>&1
)

:: 5. Kiểm tra kết quả cập nhật mã nguồn
echo.
if %UPDATE_SUCCESS% equ 1 (
    color 0A
    if exist "version.txt" (
        set /p VER_CODE=<version.txt
        echo [OK] Đã cập nhật thành công lên phiên bản: v%VER_CODE%
    ) else (
        echo [OK] Đã cập nhật mã nguồn thành công!
    )
) else (
    color 0C
    echo [ERROR] Không thể kết nối hoặc tải bản cập nhật từ GitHub.
    echo Vui lòng kiểm tra lại kết nối Internet và thử lại sau.
    echo.
    pause
    exit /b 1
)

:: 6. Tự động kiểm tra và cập nhật các thư viện Python (requirements.txt)
echo.
echo [*] Đang kiểm tra thư viện Python...
set PYTHON_CMD=
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
) else (
    py --version >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=py"
    ) else (
        if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python312\python.exe"
        if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python311\python.exe"
        if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python310\python.exe"
        if exist "C:\Python312\python.exe" set "PYTHON_CMD=C:\Python312\python.exe"
        if exist "C:\Python311\python.exe" set "PYTHON_CMD=C:\Python311\python.exe"
    )
)

if defined PYTHON_CMD (
    if exist "requirements.txt" (
        echo [*] Đang nâng cấp các thư viện Python nếu có gói mới...
        "%PYTHON_CMD%" -m pip install -r requirements.txt --upgrade --quiet 2>nul
        if %errorlevel% equ 0 (
            echo [OK] Thư viện Python đã sẵn sàng.
        ) else (
            echo [WARN] Không thể tự động nâng cấp thư viện (bạn có thể chạy install.bat nếu thiếu module).
        )
    )
) else (
    echo [WARN] Chưa phát hiện Python trong PATH. Nếu phần mềm không mở được, hãy chạy install.bat.
)

echo.
echo ====================================================================
echo    CẬP NHẬT HOÀN TẤT THÀNH CÔNG!
echo    Bạn có thể khởi động phần mềm bằng file: run_seedvis.bat
echo ====================================================================
echo.
pause
