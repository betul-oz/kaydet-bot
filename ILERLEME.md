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

## 2026-10-19 — Oturum 3 (devam): İş 4, 5, 6, 7 bitti
- Yapıldı: web ana sayfa (kanban, sürükle-bırak, not, ara/filtre), indirme kuyruğu (yt-dlp, durum, hata, "hepsini indir", `auto_download`), plan kartı + Kopyala, README (TR+EN özet), Dockerfile.
- Test: 64 geçti. Gerçek tarayıcıda denendi (kanban, kart, kopyalama). Gerçek indirme denendi (YouTube, ffmpeg ile birleşik mp4); bu sırada format hatası bulunup düzeltildi.
- Denetçi (Opus) bulguları düzeltildi: not/kopyala yarışı, CSRF, allowed_hosts, atomik kuyruğa alma, boş başlık, cookies .gitignore (KARARLAR #15-19).
- **Doğrulanmadı:** Gerçek Telegram bağlantısı. Kullanıcı `.env` içine token, `config.yaml` içine `allowed_user_ids` yazmadı/yazamadı (proje klasöründe boş şablonlar var). Token'ı ben girmem.
- Bilinen sınırlar: Instagram çoğu zaman giriş ister (başlık/indirme için `cookies_file` gerekir); bekleyen bot buton seçimleri bellekte; TikTok kısa linkte bot ~30 sn bekleyebilir.
- Sıradaki: kullanıcı token+ID'yi yazınca `python -m app` ile bot denemesi → sonra **İş 8 (toplu içe aktarma)**; v2: ffmpeg birleştirme.

## 2026-10-19 — Oturum 3 (son): gerçek Telegram doğrulaması, İş 3 BİTTİ
- Doğrulandı: gerçek bot (token `.env`'de, ID `config.yaml`'da) çalışıyor. Kullanıcı telefondan Instagram linki attı, butonlarla diy/hook seçti → `kaydet.db`'ye düştü, yt-dlp başlığı otomatik çekti, web API ve sayfada görünüyor.
- `baslat.bat` eklendi (çift tıkla başlat).
- Not: DB'deki `created_at` UTC (yerel saatten 3 saat geri). Arayüzde yerel saate çevrilebilir (küçük iş).
- Sıradaki: kullanıcı gerçek kullanımda bulduklarını söyler; **İş 8 (toplu içe aktarma)**; v2: ffmpeg birleştirme. Token sohbette paylaşıldı: kullanıcıya BotFather'da `/revoke` önerildi.

## 2026-10-19 — Oturum 3 (son): arayüz yeniden tasarımı + kategori yönetimi (İş 10)
- Yapıldı: yeni arayüz (kategori rayı, kategori başına sayfa, küçük resimli dikey kartlar, ⋯ menüleri, diyaloglar, mobil uyum, Türkçe arama, "Kategorisiz" sayfası), kategori/alt başlık ekle-adlandır-sırala-sil (`app/catalog.py`, `/api/catalog/*`), hata sonrası diyalog yazıları korur.
- Test: 91 geçti. Tarayıcıda denendi (masaüstü + mobil, yönetim akışları, plan kartı + Kopyala, arama). Denetçi bulguları düzeltildi (KARARLAR #21-25): bot buton kayması, harf farkı, kilit dışı kontrol, geri alma, XSS, odak.
- Gerçek uygulama yeni kodla yeniden başlatıldı (bot + web açık).
- Bilinen sınırlar: Telegram'dan seçim yaparken web'de tam aynı anda yeniden adlandırma çok dar bir pencerede videoyu eski adla kaydedebilir (açılışta `reconcile` ve "Kategorisiz" sayfası bunu görünür kılar); yeni kategori adı bot kısa yolunda boşluk yerine `_` ile yazılır.
- Sıradaki: kullanıcı geri bildirimi; **İş 8 (toplu içe aktarma)**; v2: ffmpeg birleştirme.

## 2026-10-19 — Oturum 3 (son): Notlar sayfası + yeni yerleşim
- Yapıldı: "Notlar" sayfası (todo listesi, `todos` tablosu, `/api/todos`), sütunlar tek satırda yan yana/yukarıdan hizalı, sayfa kaymaz, sütun alanı iki yöne kayar ve yatay çubuk ekranın altında (KARARLAR #27-29, #26'yı değiştirir). Denetçi bulguları düzeltildi: çift gönderim, sayfa değişince kaydırma, kırpılan menü, odak, aria etiketleri, ağ hatası.
- Test: 98 geçti; tarayıcıda 25 videolu sahte veriyle (masaüstü + mobil) denendi, gerçek veriye dokunulmadı. Gerçek uygulama yeni kodla çalışıyor.
- Bilinen sınırlar: sürüklerken kenarda otomatik kaydırma tarayıcının yerel davranışına bırakıldı (denenmedi); ön yüz için otomatik test yok (elle tarayıcıda denendi).
- Sıradaki: kullanıcı geri bildirimi; İş 8 (toplu içe aktarma); v2: ffmpeg birleştirme.
