# SPEC: Kayıtlı İçerik Düzenleyici (çalışma adı: "kaydet-bot")

## Amaç
Instagram / TikTok / YouTube'da kaydedilen videoların kaybolmasını önlemek: linki Telegram botuna at, kategorilenip tek sayfada görünsün, istenirse indirilsin, planlama kartlarında notlarla birleşsin ve tek tıkla kopyalanabilsin.

## Kapsam (v1)
### 1. Telegram botu
- Kullanıcı link gönderir. Bot platformu (instagram/tiktok/youtube) tanır.
- Kategori ve alt başlığı butonlarla sorar (önce kategori, sonra alt başlık). Seçenekler `categories.yaml`'dan gelir.
- Kısa yol: mesajda `link diy/hook` yazılırsa sormadan kaydeder. Kısa ad (alias) desteği: `categories.yaml` içinde kategori/alt başlık takma adları.
- Bot başlık ve thumbnail'i çekmeyi dener (yt-dlp metadata, başarısız olursa boş bırakır; kayıt yine yapılır).
- Yalnızca `allowed_user_ids` içindeki kullanıcılara cevap verir.
- Aynı link ikinci kez gelirse uyarır, çift kayıt yapmaz.
- Config'de `auto_download: false|true`: true ise kayıttan sonra indirmeyi kuyruğa alır.

### 2. Ana sayfa (web)
- Tek sayfa. Kategoriler alt alta; her kategorinin altında alt başlıklar; her alt başlıkta video kartları (thumbnail, başlık, platform, not).
- Kartı bir alt başlığa sürükle-bırak ile taşıma, silme, not ekleme.
- Arama ve platform filtresi.
- Kartta "İndir" düğmesi; indirildiyse "Aç / dosya yolu". Alt başlıkta "Hepsini indir".
- İndirme arka planda kuyrukla çalışır, durum görünür (bekliyor / iniyor / bitti / hata + mesaj).
- Dosyalar `downloads/<kategori>/<alt-baslik>/` altına yazılır.

### 3. Plan kartı (birleştirme kartı)
- Kullanıcı kartı oluşturur: başlık + kendi notu (serbest metin).
- Karta kayıtlı videolardan istediği kadarını ekler (örn. hook + metin videosu), sıralar, her videoya kısa not ekleyebilir.
- **Kopyala** düğmesi: kartı tek metin olarak panoya kopyalar (aşağıdaki biçim). Kullanıcı bunu Claude'a yapıştırır.

Kopyala biçimi:
```
# <kart başlığı>

## Notlarım
<kart notu>

## Videolar
1. [diy / hook] <başlık> (<platform>)
   Link: <url>
   Not: <video notu>
   Dosya: <indirildiyse yerel yol>
2. ...
```

### 4. Kurulum / paylaşım
- `.env`: `TELEGRAM_BOT_TOKEN`. `config.yaml`: `allowed_user_ids`, `auto_download`, `downloads_dir`.
- `categories.example.yaml` repoda; kullanıcı kendi `categories.yaml`'ını oluşturur.
- README (Türkçe + kısa İngilizce), tek komutla çalıştırma (`python -m app`), opsiyonel Dockerfile.
- Telif / kullanım şartı uyarısı README'de: indirme kişisel arşiv/ilham içindir, yeniden yayınlamak kullanıcı sorumluluğundadır.

## Kapsam dışı (v1)
- Uygulama içi chat, API anahtarı, otomatik video birleştirme (ffmpeg) → v2.
- Çok kullanıcılı hesap sistemi, bulut barındırma.

## Veri modeli (SQLite)
- `items`: id, url (unique), platform, title, thumb_url, category, subcategory, note, status (`kayitli|bekliyor|iniyor|indirildi|hata`), file_path, error, created_at
- `cards`: id, title, note, created_at
- `card_items`: card_id, item_id, position, note

## Kabul kriterleri
1. Bota Instagram/TikTok/YouTube linki atınca butonlarla kategori+alt başlık seçilip kayıt oluşur; `link diy/hook` kısa yolu sormadan kaydeder.
2. İzin listesinde olmayan kullanıcıya bot cevap vermez.
3. Aynı link iki kez eklenmez.
4. Ana sayfada kayıtlar kategori > alt başlık altında görünür; sürükle-bırak taşıma kalıcıdır (sayfa yenilenince kalır).
5. İndir düğmesi videoyu `downloads/` altına indirir; başarısızlıkta hata mesajı kartta görünür, uygulama çökmez.
6. Plan kartı oluşturulur, en az iki video eklenir, "Kopyala" yukarıdaki biçimde metni panoya koyar (link + notlar eksiksiz).
7. Temiz bir makinede README'deki adımlarla kurulum çalışır; token ve kişisel veri repoda yoktur (`.gitignore`: `.env`, `config.yaml`, `categories.yaml`, `*.db`, `downloads/`).
8. Otomatik testler: link ayrıştırma, kısa yol ayrıştırma, DB işlemleri, kopyala biçimi.
