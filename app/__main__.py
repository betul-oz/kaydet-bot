"""Çalıştır: python -m app  (web sayfası + indirme + varsa Telegram botu)"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

import uvicorn

from . import analytics, db
from .bot import build_application
from .catalog import Catalog
from .config import load_categories, load_config
from .downloader import Downloader
from .web import create_app


def load_env(path: str | Path = ".env") -> None:
    """Basit .env okuyucu (bağımlılık eklememek için). Ortamda zaten olan değeri ezmez."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # istek adresleri token içerir
    load_env()
    try:
        config = load_config("config.yaml")
        categories = load_categories("categories.yaml")
    except (FileNotFoundError, ValueError) as e:
        print(f"Ayar hatası: {e}")
        return 1

    db.connect(config.db_path).close()  # şemayı oluştur
    downloader = Downloader(config.db_path, config.downloads_dir, config.cookies_file)
    downloader.start()

    catalog = Catalog(categories, "categories.yaml", config.db_path)
    fixed = catalog.reconcile()  # sadece harf farkı olan eski kayıtları yapılandırmadaki yazıma çek
    if fixed:
        print(f"{fixed} videonun kategori yazımı düzeltildi.")
    server = uvicorn.Server(uvicorn.Config(
        create_app(config, categories, downloader, catalog,
                   analytics.Syncer(config.db_path, db.connect, config.cookies_file)),
        host=config.web_host, port=config.web_port, log_level="warning"))
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    bot_problem = ("TELEGRAM_BOT_TOKEN yok (.env)" if not token else
                   "config.yaml içinde allowed_user_ids boş (Telegram ID'ni @userinfobot'tan öğren)"
                   if not config.allowed_user_ids else "")

    print(f"Web sayfası: http://{config.web_host}:{config.web_port}")
    if bot_problem:
        print(f"Telegram botu KAPALI: {bot_problem}. Sadece web sayfası çalışıyor.")
        server.run()
        return 0

    # Bot ana iş parçacığında (sinyalleri o yönetir), web arka planda
    server.install_signal_handlers = lambda: None
    threading.Thread(target=server.run, name="web", daemon=True).start()
    bot_conn = db.connect(config.db_path)
    app = build_application(token, config, categories, bot_conn)
    app.bot_data["downloader"] = downloader
    print("Telegram botu açık. Durdurmak için Ctrl+C.")
    app.run_polling()
    server.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main())
