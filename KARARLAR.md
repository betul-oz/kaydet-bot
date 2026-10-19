# KARARLAR

| # | Tarih | Karar | Neden |
|---|---|---|---|
| 1 | 2026-10-19 | Çekirdek tamamen ücretsiz: Telegram Bot API + SQLite + yt-dlp + ffmpeg | Kullanıcı ek ücret istemiyor; repo public paylaşılacak |
| 2 | 2026-10-19 | Uygulama içi chat / API anahtarı YOK (şimdilik) | Ücretsiz kalsın; birleştirme işini kullanıcı kartı kopyalayıp Claude'a yapıştırarak yaptırır |
| 3 | 2026-10-19 | Karta "Kopyala" düğmesi: video linkleri + kullanıcı notları tek metin | Chat yerine; kullanıcı metni Claude'a yapıştırır |
| 4 | 2026-10-19 | "Video indir" düğmesi (yt-dlp), tek video ve alt başlık toplu | Kullanıcı elle indirmekle uğraşmak istemiyor |
| 5 | 2026-10-19 | Kategoriler `categories.yaml` ile kullanıcı tarafından tanımlanır | Repo başkaları için de çalışsın |
| 6 | 2026-10-19 | Yığın: Python 3.11+, python-telegram-bot, FastAPI, SQLite, sade HTML/JS | Tek dil, kurulumu kolay, public repo için sade |
| 7 | 2026-10-19 | Bot yalnızca `allowed_user_ids` listesindeki kişilere cevap verir | Public repoda bot başkalarına açık kalmasın |
| 8 | 2026-10-19 | Video birleştirme (ffmpeg) ertelendi, v2 | Kullanıcı şimdilik kopyala yöntemini seçti |
| 9 | 2026-10-19 | Aynı video tek kayıt: YouTube `watch?v=ID`, Instagram `/reel/KOD`, TikTok `/@kullanici/video/ID` biçimine indirgenir; zaman damgası/liste/takip parametreleri atılır | Denetçi: aynı video farklı linklerle çift kaydoluyordu |
| 10 | 2026-10-19 | TikTok kısa linkleri (vm.tiktok.com, tiktok.com/t/) iş 3'te yt-dlp ile açılıp gerçek id ile tekrar kontrol edilecek | Yönlendirme çözülmeden normalleştirilemez |
| 11 | 2026-10-19 | SQLite bağlantısı `check_same_thread=False`; bot, web ve indirme kuyruğu aynı bağlantıyı paylaşabilir. Yazmalar kısa, her biri commit eder | Çoklu thread ihtiyacı |
| 12 | 2026-10-19 | Kısa yol/kategori eşleşmesi Türkçe İ/I/ı farkını yok sayar; '_' ve '-' boşluk sayılır (örn. `el_isi/hook`) | Türk klavyesi, boşluklu kategori adları |
| 13 | 2026-10-19 | Kullanıcıbilgisi içeren adresler (`tiktok.com@127.0.0.1`) desteklenmeyen sayılır; TikTok kısa linki çözülünce dönen adres de TikTok değilse kısa link olduğu gibi kaydedilir | Denetçi: yt-dlp'ye sahte adresle keyfi sunucu isteği (SSRF) gidebiliyordu |
| 14 | 2026-10-19 | Başlık/thumbnail kayıttan sonra arka planda doldurulur (kayıt hızlı, yt-dlp başarısız olsa da kayıt kalır) | Instagram giriş isteyebilir; kullanıcıyı bekletme |
| 15 | 2026-10-19 | Web arayüzü yalnızca 127.0.0.1'de; Host (DNS rebinding) ve Origin/Sec-Fetch-Site (CSRF) kontrolü; başka cihaz için `web_host` + `allowed_hosts` | Kimlik doğrulama yok, yerel araç |
| 16 | 2026-10-19 | İndirme: ffmpeg varsa `bv*+ba` birleştirip mp4 (en çok 1080p), yoksa tek dosyalı mp4; Instagram için isteğe bağlı `cookies_file`. Durum geçişi tek SQL ile atomik | YouTube görüntü+ses ayrı verir (gerçek denemede bulundu) |
| 17 | 2026-10-19 | Web arayüzünde not/başlık düzenlemesi ekranı yeniden çizmez, kayıtlar sıraya konur, Kopyala ve load() bekleyen kayıtları bekler | Denetçi: eski metin kopyalanabiliyordu (tarayıcıda doğrulandı) |
| 18 | 2026-10-19 | "Aç" düğmesi yok, yerine "Yolu kopyala" | Tarayıcı http sayfasından file:// açamaz |
| 19 | 2026-10-19 | Web ve bot tek komutla (`python -m app`); token/ID yoksa yalnızca web açılır | Token olmadan da kullanılabilsin |
| 20 | 2026-10-19 | Arayüz: sol kategori rayı, kategori başına ayrı sayfa (`#/k/<ad>`), plan kartları `#/planlar`, tüm kategorilerde arama; mobilde ray üstte yatay | Kullanıcı isteği (tek sayfada tek kategori) |
| 21 | 2026-10-19 | Kategori/alt başlık yönetimi web'den: tek kilit + tek SQLite yazma işlemi (BEGIN IMMEDIATE) + yaml; hata olursa bellek, DB ve yaml geri alınır. Silmede video varsa taşınacak yer zorunlu. Eşleşme harf/İ farkını yok sayar | Denetçi: yarış, çift kaynak (DB/yaml) tutarsızlığı |
| 22 | 2026-10-19 | `categories.yaml` web'den ilk düzenlemede yeniden yazılır, elle yazılan yorumlar silinir (dosya başında uyarı) | `safe_dump` yorum korumaz; kabul edilen bedel |
| 23 | 2026-10-19 | Telegram butonları gösterildiği andaki kategori adlarını saklar ve kaydetmeden önce adı yeniden doğrular; kategori değişmişse "linki tekrar gönder" der | Sıra/ad değişince video yanlış yere kaydoluyordu |
| 24 | 2026-10-19 | Açılışta `reconcile()` harf farklı eski kayıtları düzeltir; tanınmayan kategorili videolar arayüzde "Kategorisiz" sayfasında görünür | Videolar kaybolmasın |
| 25 | 2026-10-19 | Kategori adı: en çok 40 karakter, `/ | \ < >` ve görünmez/yön değiştiren karakterler yasak | XSS, yanıltıcı adlar |
