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
