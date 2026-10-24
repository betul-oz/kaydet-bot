"""İş panosu: kullanıcı ile Claude arasındaki iş takibi, mesajlar ve 2 haftalık içerik dönemleri.

Komut satırı (Claude oturumlarından kullanım):
  python -m app.board add "Başlık" [--marka X] [--platform youtube] [--son 2026-11-03]
  python -m app.board durum <id> <bekliyor|uretimde|hazir|yuklendi|sorun> [--not "..."]
  python -m app.board say "mesaj"
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, timedelta

STATUSES = ("bekliyor", "uretimde", "hazir", "yuklendi", "sorun")
AUTHORS = ("sen", "claude", "sistem")
BATCH_DAYS = 14
REMIND_DAYS_BEFORE = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    brand TEXT NOT NULL DEFAULT '',
    platform TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'bekliyor',
    note TEXT NOT NULL DEFAULT '',
    due TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author TEXT NOT NULL,
    text TEXT NOT NULL,
    task_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    reminded INTEGER NOT NULL DEFAULT 0
);
"""


class BoardError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        raise BoardError("Tarih YYYY-AA-GG biçiminde olmalı (örn. 2026-11-03)")


def add_message(conn: sqlite3.Connection, author: str, text: str, task_id: int | None = None) -> int:
    text = text.strip()
    if author not in AUTHORS or not text or len(text) > 2000:
        raise BoardError("Mesaj boş olamaz (en çok 2000 karakter)")
    cur = conn.execute("INSERT INTO messages (author, text, task_id) VALUES (?, ?, ?)", (author, text, task_id))
    conn.commit()
    return cur.lastrowid


def add_task(conn: sqlite3.Connection, title: str, *, brand: str = "", platform: str = "",
             due: str = "", note: str = "", actor: str = "sen") -> int:
    title = " ".join(title.split())
    if not title or len(title) > 200:
        raise BoardError("İş başlığı 1-200 karakter olmalı")
    due = _date(due).isoformat() if due.strip() else ""
    cur = conn.execute("INSERT INTO tasks (title, brand, platform, due, note) VALUES (?, ?, ?, ?, ?)",
                       (title, brand.strip()[:60], platform.strip()[:20], due.strip(), note.strip()[:2000]))
    conn.commit()
    add_message(conn, actor, f"Yeni iş: {title}", cur.lastrowid)
    return cur.lastrowid


def update_task(conn: sqlite3.Connection, task_id: int, *, status: str | None = None, title: str | None = None,
                note: str | None = None, due: str | None = None, actor: str = "sen") -> bool:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return False
    if status is not None and status not in STATUSES:
        raise BoardError("Durum: " + ", ".join(STATUSES))
    if title is not None and not (title := " ".join(title.split())):
        raise BoardError("Başlık boş olamaz")
    if due is not None:
        due = _date(due).isoformat() if due.strip() else ""
    conn.execute("UPDATE tasks SET status = COALESCE(?, status), title = COALESCE(?, title), "
                 "note = COALESCE(?, note), due = COALESCE(?, due), updated_at = datetime('now') WHERE id = ?",
                 (status, title, None if note is None else note.strip()[:2000], due, task_id))
    conn.commit()
    if status and status != row["status"]:
        add_message(conn, actor, f"“{row['title']}”: {row['status']} → {status}", task_id)
    return True


def delete_task(conn: sqlite3.Connection, task_id: int) -> bool:
    cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    return cur.rowcount > 0


def add_batch(conn: sqlite3.Connection, title: str, start: str) -> int:
    title = " ".join(title.split()) or "2 haftalık içerik"
    s = _date(start)
    cur = conn.execute("INSERT INTO batches (title, start_date, end_date) VALUES (?, ?, ?)",
                       (title[:100], s.isoformat(), (s + timedelta(days=BATCH_DAYS - 1)).isoformat()))
    conn.commit()
    return cur.lastrowid


def delete_batch(conn: sqlite3.Connection, batch_id: int) -> bool:
    cur = conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
    conn.commit()
    return cur.rowcount > 0


def overview(conn: sqlite3.Connection, today: date | None = None) -> dict:
    today = today or date.today()
    batches = []
    for r in conn.execute("SELECT * FROM batches ORDER BY end_date DESC"):
        b = dict(r)
        left = (date.fromisoformat(b["end_date"]) - today).days
        b["days_left"] = left
        b["remind_on"] = (date.fromisoformat(b["end_date"]) - timedelta(days=REMIND_DAYS_BEFORE)).isoformat()
        b["state"] = "bitti" if left < 0 else "son" if left <= REMIND_DAYS_BEFORE else "surer"
        batches.append(b)
    return {"tasks": [dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC, id DESC")],
            "messages": [dict(r) for r in conn.execute(
                "SELECT * FROM (SELECT * FROM messages ORDER BY id DESC LIMIT 100) ORDER BY id")],
            "batches": batches, "statuses": list(STATUSES)}


def due_reminders(conn: sqlite3.Connection, today: date | None = None) -> list[sqlite3.Row]:
    """Bitişine REMIND_DAYS_BEFORE gün veya daha az kalmış, bitmemiş ve henüz hatırlatılmamış dönemler."""
    today = today or date.today()
    out = []
    for r in conn.execute("SELECT * FROM batches WHERE reminded = 0"):
        left = (date.fromisoformat(r["end_date"]) - today).days
        if 0 <= left <= REMIND_DAYS_BEFORE:
            out.append(r)
    return out


def reminder_text(batch: sqlite3.Row, today: date | None = None) -> str:
    left = (date.fromisoformat(batch["end_date"]) - (today or date.today())).days
    return (f"Hatırlatma: “{batch['title']}” dönemi {batch['end_date']} tarihinde bitiyor "
            f"({'bugün' if left == 0 else f'{left} gün kaldı'}). Yeni 2 haftalık içeriği planlama zamanı.")


def run_reminders(conn: sqlite3.Connection, send, today: date | None = None) -> int:
    """send(metin) çağrılır; yalnızca gönderim başarılıysa dönem 'hatırlatıldı' olur. Dönen: gönderilen sayı."""
    n = 0
    for b in due_reminders(conn, today):
        text = reminder_text(b, today)
        try:
            ok = send(text)
        except Exception:
            ok = False
        if ok:
            conn.execute("UPDATE batches SET reminded = 1 WHERE id = ?", (b["id"],))
            conn.commit()
            add_message(conn, "sistem", text)
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    from . import db
    from .config import load_config
    ap = argparse.ArgumentParser(prog="python -m app.board")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("title"); a.add_argument("--marka", default="")
    a.add_argument("--platform", default=""); a.add_argument("--son", default="")
    d = sub.add_parser("durum"); d.add_argument("id", type=int); d.add_argument("status"); d.add_argument("--not", dest="note")
    s = sub.add_parser("say"); s.add_argument("text")
    args = ap.parse_args(argv)
    conn = db.connect(load_config("config.yaml").db_path)
    try:
        if args.cmd == "add":
            print("iş", add_task(conn, args.title, brand=args.marka, platform=args.platform, due=args.son, actor="claude"))
        elif args.cmd == "durum":
            if not update_task(conn, args.id, status=args.status, note=args.note, actor="claude"):
                print("İş yok"); return 1
        else:
            add_message(conn, "claude", args.text)
    except BoardError as e:
        print(e); return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
