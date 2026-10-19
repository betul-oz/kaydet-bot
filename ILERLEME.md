# ILERLEME

## 2026-10-19 — Oturum 2: İş 2 (iskelet) bitti
- Yapıldı: `app/config.py` (config + kategori okuma, doğrulama, Türkçe İ/I/ı eşleşmesi), `app/links.py` (platform tanıma, YouTube/IG/TikTok normalleştirme, `link diy/hook` kısa yolu), `app/db.py` (SQLite: items, cards, card_items), örnek config dosyaları, `.gitignore`, CLAUDE.md.
- Test: `python -m pytest -q` → 27 geçti.
- Denetçi (Opus) bulgularının hepsi düzeltildi: çift kayıt normalleştirmesi, kısa yol katılığı, `İ` sorunu, bool/ID ayrıştırma, LIKE kaçışı, `.gitignore` (KARARLAR #9-12).
- Açık not: TikTok kısa linkleri (vm.tiktok.com) iş 3'te yt-dlp ile çözülüp tekrar kontrol edilecek (KARARLAR #10).
- Sıradaki tek iş: **İş 3 (Telegram botu)**. Başlamadan önce kullanıcı BotFather'dan token alıp `.env` oluşturmalı ve Telegram kullanıcı ID'sini `config.yaml`'a yazmalı.

## 2026-10-19 — Oturum 3: İş 3 (Telegram botu) kod olarak bitti
- Yapıldı: `app/bot.py` (butonlu kategori/alt başlık, kısa yol, izin listesi, çift kayıt, TikTok kısa link çözme), `app/meta.py` (yt-dlp başlık/thumbnail), `app/__main__.py` (`python -m app`, .env okuma), `db.get_item_by_url/set_meta`.
- Test: 42 geçti. Denetçi (Opus) bulguları düzeltildi (sahte adresle SSRF, TikTok platform kontrolü, test boşlukları — KARARLAR #13-14).
- **Doğrulanmadı:** Gerçek Telegram'a bağlanma. Proje klasöründe `.env`, `config.yaml`, `categories.yaml` yoktu (yalnızca `*.example`). Kullanıcı bu dosyaları oluşturunca `python -m app` ile açılış ve gerçek link denemesi yapılmalı.
- Bilinen sınırlar: TikTok kısa linki kaydederken bot en fazla ~30 sn bekleyebilir; bekleyen buton seçimleri bellekte tutulur (bot yeniden başlarsa "süresi dolmuş" der); `auto_download` iş 5'te uygulanacak.
- Sıradaki: önce gerçek token denemesi, sonra **İş 4 (web ana sayfa)**.
