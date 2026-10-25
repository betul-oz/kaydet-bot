# kaydet-bot

Instagram/TikTok/YouTube'da kaydedilen videoları Telegram botuyla kategorileyen, web sayfasında gösteren, indiren ve plan kartlarında notlarla birleştirip tek tıkla kopyalatan açık kaynak araç.

- Proje hafızası: `docs/SPEC.md` (gereksinimler), `IS-LISTESI.json` (işler), `ILERLEME.md` (son durum), `KARARLAR.md`.
- Oturum başında `ILERLEME.md` ve `IS-LISTESI.json`'u oku; sıradaki tek işi yap.
- Yığın: Python 3.11+, python-telegram-bot, FastAPI, SQLite, yt-dlp. Chat/API anahtarı yok (KARARLAR #2).
- Testler: `python -m pytest`
- Public repo: token, `config.yaml`, `categories.yaml`, `*.db`, `downloads/` asla commit edilmez.
- Kod yorumları ve kullanıcıya dönük metinler Türkçe.
- Analiz modülü: `docs/SPEC-ANALIZ.md`, `app/analytics.py`. Hesap/metrik verisi yalnızca yerel DB'de; public repoya marka verisi, token, çerez girmez.
- Her iş sonunda: test -> commit -> `git push` (GitHub'a kayıt kullanıcı kuralı).
- İş panosu: oturum sonunda yaptığım/başlattığım işleri `python -m app.board durum <id> <durum>` ve `say` ile panoya yaz; oturum başında panodaki kullanıcı notlarını oku (`/api/board` ya da DB).

## Video ve metin inceleme kuralı (KARARLAR #40, #45)
- Bu hesapta (hangi proje olursa olsun) üretilen her video ve yazılan her metin (senaryo, açıklama, plan) bitince incelemeye kaydedilir:
  - Video: `python C:\Users\ozkan\Desktop\smDataAnalyze\izle.py ekle <dosya> --baslik "..." --marka "<Kanal>" --kategori "<Başlık>[/<Alt başlık>]" --format yatay|short [--platform youtube --proje <klasör>]`
  - Metin: `python C:\Users\ozkan\Desktop\smDataAnalyze\izle.py metin-ekle <dosya.md> --baslik "..." --marka "<Kanal>" --kategori "<Başlık>[/<Alt başlık>]"`
  - Klasördeki metinleri toplu: `izle.py metin-aktar <klasör> --marka "<Kanal>" [--haric a,b]` (alt klasör adı başlık olur). Metin sekmesi: `#/metin`.
  - Çıkan adresi kullanıcıya ver. Kanal = marka/kanal adı (örn. Flag Derby), başlık = konu grubu (örn. Altyazı yönleri), alt başlık = gerekiyorsa daha ince grup.
- Oturum başında `python izle.py bekleyen`: "Değişikliğe başla" denmiş video (zaman damgalı not) ve metin (cümle yorumu) revizyonlarını yazar. Uygula, sonra `izle.py yeni-surum <id> <yeni video>` veya `izle.py metin-guncelle <id> <dosya> --not "ne yaptın"`. Kullanıcı metni arayüzde düzenlediyse önce `izle.py metin-al <id>`.
- `IZLE_SERVER` + `IZLE_TOKEN` ortam değişkeni varsa komutlar yayındaki sunucuya yazar (docs/DEPLOY.md); yoksa yerel veritabanına.
- Uygulama kapalıysa `baslat.bat` ile aç; kayıt DB'ye düşer.
