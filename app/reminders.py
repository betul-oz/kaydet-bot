"""Dönem hatırlatıcısı: saat başı kontrol eder, Telegram'dan izinli kullanıcılara yazar."""
from __future__ import annotations

import logging
import threading
from contextlib import closing

import httpx

from . import board, db

log = logging.getLogger("reminders")


def telegram_sender(token: str, user_ids: list[int]):
    """En az bir kullanıcıya gittiyse True (botu hiç başlatmamış biri yüzünden diğerlerine saat başı
    tekrar gitmesin). Token hata iletilerine sızmasın diye adres günlüğe yazılmaz."""
    def send(text: str) -> bool:
        delivered = 0
        for uid in user_ids:
            try:
                r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                               json={"chat_id": uid, "text": text}, timeout=20)
                delivered += r.status_code == 200
            except httpx.HTTPError:
                pass
        return delivered > 0
    return send


def start_loop(db_path: str, send, every_seconds: int = 3600) -> threading.Event:
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                with closing(db.connect(db_path)) as c:
                    board.run_reminders(c, send)
            except Exception:
                log.warning("Hatırlatıcı kontrolü başarısız", exc_info=False)
            stop.wait(every_seconds)

    threading.Thread(target=loop, name="reminders", daemon=True).start()
    return stop
