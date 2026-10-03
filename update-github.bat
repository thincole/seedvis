@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Push Code to GitHub (thincole/seedvis)

:: Cau hinh Git user & safe directory
git config --global --add safe.directory "%~dp0" >nul 2>&1
git config --global --add safe.directory * >nul 2>&1
git config user.email "thincole@users.noreply.github.com"
git config user.name "thincole"

echo ====================================================================
echo    PUSH CODE LEN GITHUB (thincole/seedvis)
echo ====================================================================
echo.

if not exist ".git" (
    git init
    git branch -M main
    git remote add origin https://github.com/thincole/seedvis.git
    echo Da khoi tao repository moi.
)

:: Doc version hien tai va tu dong tang
if not exist "version.txt" echo 1.0.0> version.txt
set /p OLD_VER=<version.txt
for /f "tokens=1,2,3 delims=." %%a in ("%OLD_VER%") do (
    set MAJOR=%%a
    set MINOR=%%b
    set /a PATCH=%%c+1
)
set NEW_VER=%MAJOR%.%MINOR%.%PATCH%
echo %NEW_VER%> version.txt

echo Version: %OLD_VER% --^> %NEW_VER%
echo.

git add -A
git commit -m "Seedvis v%NEW_VER%"
git branch -M main
git push -u origin main
if %errorlevel% neq 0 (
    echo [WARN] Thu force push...
    git push -u origin main --force
)

git tag -a v%NEW_VER% -m "Version %NEW_VER%" 2>nul
git push origin v%NEW_VER% 2>nul

echo.
echo ====================================================================
echo    DA PUSH THANH CONG! Version: v%NEW_VER%
echo ====================================================================
echo.
pause
