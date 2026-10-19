# kaydet-bot

Instagram, TikTok ve YouTube'da kaydettiğin videolar kaybolmasın: linki **Telegram botuna at**, kendi kategorilerine otomatik yerleşsin, **tek sayfada kanban** olarak gör, istersen **indir**, plan kartlarında notlarınla birleştirip **tek tıkla kopyala** (ve ChatGPT/Claude'a yapıştır).

Ücretsiz, hesap/abonelik yok, verin kendi bilgisayarında (SQLite). API anahtarı gerekmez.

> *English, short:* a self-hosted Telegram bot + local web board that files the Instagram/TikTok/YouTube links you send it into your own categories, optionally downloads them with yt-dlp, and lets you build plan cards (videos + your notes) you can copy as one text block. Setup is the same as below.

## Özellikler
- **Telegram botu:** link at → bot "nereye koyayım?" diye butonlarla sorar. Hızlı yol: `link diy/hook` yazarsan sormadan kaydeder.
- **Kendi kategorilerin:** `categories.yaml` dosyasında sen belirlersin (takma adlarla: `d/h`).
- **Web sayfası** (`http://127.0.0.1:8000`): solda kategori listesi, **her kategori ayrı sayfa**; alt başlıklar kanban sütunu, kartları sürükle-bırak (ya da ⋯ menüsünden) taşı, not ekle, tüm kategorilerde ara.
- **Kategori yönetimi web sayfasından:** kategori ve alt başlık ekle, yeniden adlandır, sırala, sil (içinde video varsa nereye taşınacağını sorar). Değişiklikler `categories.yaml`'a yazılır, bot da hemen görür.
- **Video indir:** tek video ya da alt başlıktaki hepsi (yt-dlp). İstersen bot her kaydı otomatik indirir.
- **Plan kartı:** kartın notu + istediğin videolar (sıralı, her birine not) → **Kopyala** düğmesi linkleri ve notların hepsini tek metin yapar.

## Kurulum (Windows / macOS / Linux)
Gerekli: Python 3.11+. Önerilen: [ffmpeg](https://ffmpeg.org/) (YouTube indirirken görüntü+sesi birleştirmek için).

```bash
pip install -r requirements.txt
```

1. **Bot oluştur:** Telegram'da `@BotFather` → `/newbot` → verdiği token'ı kopyala.
2. **Kendi Telegram ID'ni öğren:** `@userinfobot`'a yaz, sana sayı verir.
3. Örnek dosyaları kopyala ve doldur:

```bash
cp .env.example .env                       # TELEGRAM_BOT_TOKEN=... satırına token'ı yaz
cp config.example.yaml config.yaml         # allowed_user_ids: [senin_id'n]
cp categories.example.yaml categories.yaml # kendi kategorilerini yaz
```

4. Çalıştır:

```bash
python -m app
```

Web sayfası `http://127.0.0.1:8000` adresinde açılır. Token veya ID boşsa bot kapalı kalır, sadece web sayfası çalışır.

### Docker ile
```bash
docker build -t kaydet-bot .
docker run -d --name kaydet -p 127.0.0.1:8000:8000 -v "$PWD":/data -w /data --env-file .env kaydet-bot
```
Docker'da `config.yaml` içine `web_host: 0.0.0.0` yaz (port yine yalnızca senin bilgisayarına açılır; `-p 127.0.0.1:8000:8000` buna dikkat eder).

## Ayarlar (`config.yaml`)
| Anahtar | Anlamı |
|---|---|
| `allowed_user_ids` | Bota yazabilecek Telegram ID'leri. **Boşsa bot kimseye cevap vermez.** |
| `auto_download` | `true` ise bota atılan her link otomatik indirilir |
| `downloads_dir` | İndirilenlerin klasörü (`downloads/kategori/alt-baslik/`) |
| `cookies_file` | Giriş isteyen videolar (özellikle Instagram) için `cookies.txt` yolu |
| `web_host`, `web_port` | Web sayfası adresi (varsayılan `127.0.0.1:8000`) |
| `allowed_hosts` | `web_host: 0.0.0.0` ile başka cihazdan (telefon) açacaksan o adresi yaz, örn. `["192.168.1.20"]`. Boşsa yalnızca localhost çalışır |

## Plan kartını Claude'a yaptırmak
Plan kartında **Kopyala**'ya bas, metni Claude'a (veya başka bir yapay zekâya) yapıştır ve ne istediğini yaz ("bu iki videoyu birleştiren bir senaryo yaz"). Videoları gerçekten birleştirmek istersen indirilmiş dosya yolları kopyalanan metinde yer alır.

## Güvenlik notları
- Web sayfası **sadece bu bilgisayardan** erişilebilir (varsayılan). Başka cihaza açarsan (`web_host` + `allowed_hosts`) kimlik doğrulaması yoktur; sadece güvendiğin yerel ağda kullan, internete açma.
- `cookies.txt` oturum bilgin içerir; repoya girmez (`.gitignore`), kimseyle paylaşma.
- `.env`, `config.yaml`, `categories.yaml`, `*.db` ve `downloads/` repoya girmez (`.gitignore`).
- Bot yalnızca `allowed_user_ids` listesindekilere cevap verir.

## Kullanım şartları ve telif
Videoları indirmek Instagram/TikTok/YouTube kullanım şartlarının gri alanındadır ve içerik sahiplerinin telif hakkı vardır. Bu araç **kişisel arşiv ve ilham/planlama** içindir; indirdiğin videoyu izinsiz yeniden yayınlamak senin sorumluluğundadır.

## Geliştirme
```bash
pip install -r requirements-dev.txt
python -m pytest
```
Proje hafızası: `docs/SPEC.md`, `KARARLAR.md`, `IS-LISTESI.json`, `ILERLEME.md`.

## Lisans
MIT, bkz. [LICENSE](LICENSE).
