@echo off
rem Çift tıkla: botu ve web sayfasını başlatır, tarayıcıda açar (http://127.0.0.1:8000).
rem Kapatmak için bu pencereyi kapat. Pencere açık kaldıkça bot ve sayfa çalışır.
cd /d "%~dp0"
chcp 65001 >nul
title Kaydet
rem 4 saniye sonra tarayıcıyı aç (sunucunun açılması için bekler)
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8000"
python -m app
echo.
echo Program durdu. Hata varsa yukarıda yazar.
pause
