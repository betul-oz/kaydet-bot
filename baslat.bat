@echo off
rem Çift tıkla: botu ve web sayfasını başlatır (http://127.0.0.1:8000). Kapatmak için pencereyi kapat.
cd /d "%~dp0"
chcp 65001 >nul
python -m app
pause
