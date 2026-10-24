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
