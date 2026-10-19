"""Çalıştır: python -m app"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from . import db
from .bot import build_application
from .config import load_categories, load_config


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
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN yok. .env.example dosyasını .env olarak kopyalayıp token'ı yaz.")
        return 1
    try:
        config = load_config("config.yaml")
        categories = load_categories("categories.yaml")
    except (FileNotFoundError, ValueError) as e:
        print(f"Ayar hatası: {e}")
        return 1
    if not config.allowed_user_ids:
        print("config.yaml içinde allowed_user_ids boş: bot kimseye cevap vermez. "
              "Telegram kullanıcı ID'ni @userinfobot'tan öğrenip ekle.")
        return 1
    conn = db.connect(config.db_path)
    build_application(token, config, categories, conn).run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
