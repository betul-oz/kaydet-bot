# ILERLEME

## 2026-10-25 - Oturum 5 (devam): Metinler sekmesi
- Yapıldı: üst anahtara **Metinler** eklendi (kanal > başlık > alt başlık, videolardan ayrı başlık türü), `izle.py metin-aktar` ile yt (31) ve SafeKids (17) metinleri içeri alındı (KARARLAR #48-49). Metin okuyucu/yorum/revizyon sayfası zaten vardı, bu sekmede çalışıyor.
- Test: 147 geçti. Tarayıcıda gerçek veriyle görüldü (kanal kartları, başlık/alt başlık bölümleri). Bu ek için ayrı denetçi çalıştırılmadı.
- Uygulama: `python -m app` bu oturumun arka plan görevi olarak açık; kalıcı olması için kullanıcı `baslat.bat`'ı açık bırakmalı (zamanlanmış görev kurulumu izin sistemince reddedildi).
- Not: yt kanalı adı `yt` olarak açıldı; kullanıcı panelden yeniden adlandırabilir (örn. Onun Yerinde).

## 2026-10-25 - Oturum 5 (devam): İş 21 bitti (kanal ağacı, metin inceleme, yayın hazırlığı)
- Yapıldı: Videolar modu kanal > başlık > alt başlık ağacına geçti (sol ray yalnızca ağaç + sayı; kanal sayfasında bölümler; başlık/alt başlık oluştur-adlandır-sil; taşı), ✕ ile temizle / geri al, metin inceleme (cümle yorumu, düzenleme, revizyon), yayın katmanı (şifre, token, yükleme, Dockerfile, docker-compose, `docs/DEPLOY.md`). KARARLAR #43-47.
- Test: 144 geçti. Denetçi (Opus) bulguları düzeltildi: giriş gövde sınırı, IP başına kilit, tünel için de şifre, metin-guncelle kullanıcı düzenlemesini ezmez (--zorla), çakışmada taslak korunur, kanalsız temizlenenler geri alınır, sunucu dosya temizliği, SQLite uyumu, tek seferlik göç, https zorunlu. Bilerek bırakılan: ad karşılaştırmada Türkçe İ/ı, çıkışta oturum iptali yok. Tarayıcıda izole veriyle görüldü: kanal/alt başlık sayfası, temizle/geri al, metinde seçim→yorum→revizyon→`metin-guncelle`→sayfa kendiliğinden güncellendi. Docker derlemesi bu makinede (docker yok) DENENMEDİ; Dokploy'da ilk derleme gerçek sınav.
- Kullanıcıdan gereken: Dokploy'da `docs/DEPLOY.md` adımları (KAYDET_PASSWORD, KAYDET_TOKEN, KAYDET_ALLOWED_HOSTS, /data hacmi, alan adı); sonra PowerShell'de KAYDET_SERVER ve KAYDET_TOKEN.
- Sınır: yerel `kaydet.db` yayına taşınmaz (eski videolar `izle.py ekle` ile yeniden yüklenmeli). yt klasöründeki eski `yazi-arayuzu` dokunulmadı; eski .md dosyaları toplu içe aktarılmadı.

## 2026-10-24 - Oturum 5: İş 20 bitti (Video inceleme arayüzü)
- Yapıldı: "Videolar" modu (`#/izle`): oynatıcı, durdurunca/yazmaya başlayınca tam ana zaman damgalı not, zaman çizgisinde işaret, ±0,1/1 sn adım, hız, kısayollar, sürüm geçmişi, altta "Değişikliğe başla" (KARARLAR #39-42). `app/review.py`, `izle.py` (her klasörden çalışır), `/api/review/*`. Kural global CLAUDE.md'ye ve proje CLAUDE.md'ye yazıldı.
- Test: 128 geçti (10 yeni). Denetçi (Opus) bulguları düzeltildi: açık sayfanın yeni sürüme geçmesi, çift Enter, revizyonda not/onay kilidi, atomik revizyon talebi, pano işi senkronu, 60 sn taşması, yol çözümleme, medya gömme engeli. Tarayıcıda izole veriyle denendi: yatay + short, not ekleme (Enter), revizyon isteme, CLI ile yeni sürüm, açık sayfanın otomatik yeni sürüme geçmesi.
- Sınır: "Değişikliğe başla" videoyu kendiliğinden üretmez; revizyonu kaydeder, ben bir oturumda `python izle.py bekleyen` ile okuyup yaparım (KARARLAR #41). Tam otomatik için başsız `claude -p` ayrı iş olabilir.
- Gerçek uygulamayı yeniden başlat (baslat.bat) ki yeni sayfa açılsın. Gerçek DB'ye test verisi girmedi.

## 2026-10-24 - Oturum 4 (devam): İş 19 bitti
- Yapıldı: Kanal tabloları (platform başına), İş panosu (iş durumu + mesajlar), 2 haftalık dönem ve bitişe 5 gün kala Telegram hatırlatıcısı (KARARLAR #36-38). Claude komutları: `python -m app.board add|durum|say`.
- Test: 118 geçti. Tarayıcıda izole veriyle görüldü. Denetçi (Opus) bulguları düzeltildi: kısmi Telegram gönderiminde saat başı tekrar, 4 sn yenilemede kaybolan yazı, yanlış dönem afişi, UTC saat, son tarih biçimi, çift gönderim. Telegram gönderimi gerçek bota denenmedi (mantık sahte gönderici ile test edildi).
- Kullanıcıdan gereken: panoda ilk 2 haftalık dönemin başlangıç tarihini gir; uygulamayı yeni klasörden aç.

## 2026-10-24 - Oturum 4: taşıma + İş 11 (Analiz temeli) bitti
- Taşındı: eski arayüz = **kaydet-bot** (`Desktop\içerik yöneticisi`, GitHub `betul-oz/kaydet-bot`, tam senkrondu). Dosyalar bu klasöre git geçmişiyle kopyalandı (KARARLAR #30). Eski klasör silinmedi.
- Yapıldı: üstte sağda Kaydet/Analiz anahtarı; Analiz sayfası (marka > hesap > video, güç skoru, etkileşim); `app/analytics.py` (hesaplar, gönderiler, anlık görüntüler, yt-dlp ile YouTube çekimi, arka plan eşitleyici); `/api/analytics/*`; `docs/SPEC-ANALIZ.md`; iş 12-18 planı.
- Test: 111 geçti (analiz için 13 yeni, ağsız). Denetçi (Opus) bulguları düzeltildi: takılı "calisiyor" durumu, sekme/video hatası toleransı, platform-host izin listesi (SSRF), harf farkı, medyan tutarlılığı, açık tablo korunması. Bilinen: eklenen videonun hesaba aitliği doğrulanmıyor; Shorts+uzun video tek medyanda. Gerçek denemede (izole DB) bir YouTube kanalından 30 video + takipçi çekildi, tarayıcıda görüldü.
- **Gerçek durum:** TikTok profil listesi yt-dlp'de çalışmıyor, Instagram profil listesi desteklenmiyor (KARARLAR #32). Şimdilik "Video linki ekle"; kalıcı çözüm iş 13 (panel dışa aktarma) ve 14 (resmi API).
- Kullanıcıdan gereken: marka/hesap listesi (arayüzden "+ Hesap ekle"). Instagram için `config.yaml`'a `cookies_file`.
- Gerçek uygulama (bot + web) yeni kodla YENİDEN BAŞLATILMADI: çalışan eski süreç varsa kapatıp yeni klasördeki `baslat.bat` ile aç (aynı bot token iki yerde çalışmasın).
- Sıradaki tek iş: **İş 12 (analiz panoları)** ya da hesaplar girildikten sonra **İş 13**.

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

