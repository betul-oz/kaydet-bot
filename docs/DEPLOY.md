# Yayına alma (Dokploy / Docker)

Uygulama yayında **şifreyle** açılır; videolar ve metinler `izle.py` ile bilgisayarından sunucuya yüklenir, notlar sunucuda tutulur.

## 1. Dokploy'da uygulama
1. **Create Application** → GitHub'daki bu depoyu seç (`betul-oz/kaydet-bot`), dal: `main` (ya da `claude/changes`). Build tipi: **Dockerfile**.
2. **Environment** (zorunlu):
   - `KAYDET_PASSWORD` = tarayıcı giriş şifresi (uzun ve benzersiz)
   - `KAYDET_TOKEN` = `izle.py` için gizli anahtar (rastgele, 32+ karakter)
   - `KAYDET_ALLOWED_HOSTS` = alan adın (örn. `kaydet.ornek.com`; virgülle birden çok)
   - İsteğe bağlı: `TELEGRAM_BOT_TOKEN` (+ `config.yaml` içinde `allowed_user_ids`), `KAYDET_MAX_UPLOAD_MB` (varsayılan 3072)
   Şifre yoksa uygulama bilerek açılmaz (şifresiz yayın güvenli değil).
3. **Volumes / Mounts**: bir hacim ekle, mount yolu `/data` (veritabanı ve yüklenen videolar burada; yeniden yayında silinmez).
4. **Domains**: alan adını ekle, container port `8000`, HTTPS (Let's Encrypt) aç.
5. Deploy. `https://alan-adin/healthz` "ok" dönmeli; ana adres şifre sorar.

## 2. Bilgisayardan göndermek (Claude oturumları)
Windows PowerShell'de bir kez (kalıcı):
```powershell
setx KAYDET_SERVER "https://alan-adin"
setx KAYDET_TOKEN "dokploy'daki-token"
```
Yeni bir terminal açınca `python C:\Users\ozkan\Desktop\smDataAnalyze\izle.py ekle video.mp4 --baslik "..." --marka "Kanal" --kategori "Başlık/Alt başlık"` videoyu sunucuya yükler. `metin-ekle`, `metin-guncelle`, `metin-al`, `bekleyen` aynı şekilde sunucuyla konuşur. Bu iki değişken tanımlı değilse komutlar yerel veritabanına yazar.

## 3. Notlar
- Yerel `kaydet.db` ile sunucudaki veri **ayrı**dır; yerel kayıtlar yayına kendiliğinden taşınmaz.
- Eski yerel yol kayıtlı videolar sunucuda oynamaz; yeniden `izle.py ekle` ile yükle.
- Yayında Telegram botu, yt-dlp indirme ve analiz sayfaları da şifrenin arkasında çalışır; gerekmiyorsa kullanma.
- Giriş: istemci (IP) başına 5 dakikada 10 hatalı denemeden sonra geçici kilit. Çerez 30 gün, HttpOnly, SameSite=Lax; https üzerinden gelince `Secure` olur (alan adını https ile aç; http IP adresiyle giriş çalışmayabilir).
- `KAYDET_SERVER` https:// ile başlamalı (yerel adres hariç); token açık metin gitmesin.
- Compose kullanırsan Dokploy'da **Compose** tipini seç, değişkenleri Environment'a gir. Telegram botu için `/data/config.yaml` içine `allowed_user_ids: [..]` yazıp `TELEGRAM_BOT_TOKEN` ver; bot kullanmıyorsan gerekmez.
- Sunucudaki `/data/media` büyür: video silince sunucuya yüklenen dosya da silinir, ama yüklenip kaydedilmemiş artıklar için ara sıra bakmak iyi olur.
- `metin-guncelle`: kullanıcı metni arayüzde düzenlediyse önce `metin-al`; bilerek ezmek için `--zorla`.
