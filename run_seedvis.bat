@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Thin Aptm - Seedvis Veo 3.1
start "" pythonw seedvis_app.py
