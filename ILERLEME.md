# ILERLEME

## 2026-10-19 — Oturum 2: İş 2 (iskelet) bitti
- Yapıldı: `app/config.py` (config + kategori okuma, doğrulama, Türkçe İ/I/ı eşleşmesi), `app/links.py` (platform tanıma, YouTube/IG/TikTok normalleştirme, `link diy/hook` kısa yolu), `app/db.py` (SQLite: items, cards, card_items), örnek config dosyaları, `.gitignore`, CLAUDE.md.
- Test: `python -m pytest -q` → 27 geçti.
- Denetçi (Opus) bulgularının hepsi düzeltildi: çift kayıt normalleştirmesi, kısa yol katılığı, `İ` sorunu, bool/ID ayrıştırma, LIKE kaçışı, `.gitignore` (KARARLAR #9-12).
- Açık not: TikTok kısa linkleri (vm.tiktok.com) iş 3'te yt-dlp ile çözülüp tekrar kontrol edilecek (KARARLAR #10).
- Sıradaki tek iş: **İş 3 (Telegram botu)**. Başlamadan önce kullanıcı BotFather'dan token alıp `.env` oluşturmalı ve Telegram kullanıcı ID'sini `config.yaml`'a yazmalı.
