"""SQLite katmanı: kayıtlar (items) ve plan kartları (cards)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    thumb_url TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    subcategory TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'kayitli',
    file_path TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS card_items (
    card_id INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (card_id, item_id)
);
"""

STATUSES = {"kayitli", "bekliyor", "iniyor", "indirildi", "hata"}


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def add_item(conn: sqlite3.Connection, *, url: str, platform: str, category: str,
             subcategory: str, title: str = "", thumb_url: str = "") -> tuple[int, bool]:
    """(id, yeni_mi) döner. Aynı url ikinci kez eklenmez."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO items (url, platform, category, subcategory, title, thumb_url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (url, platform, category, subcategory, title, thumb_url),
    )
    conn.commit()
    if cur.rowcount == 0:
        return conn.execute("SELECT id FROM items WHERE url = ?", (url,)).fetchone()["id"], False
    return cur.lastrowid, True


def get_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()


def get_item_by_url(conn: sqlite3.Connection, url: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM items WHERE url = ?", (url,)).fetchone()


def set_meta(conn: sqlite3.Connection, item_id: int, *, title: str = "",
             thumb_url: str = "") -> bool:
    """Boş gelen alan mevcut değeri ezmez."""
    cur = conn.execute(
        "UPDATE items SET title = COALESCE(NULLIF(?, ''), title), "
        "thumb_url = COALESCE(NULLIF(?, ''), thumb_url) WHERE id = ?",
        (title, thumb_url, item_id))
    conn.commit()
    return cur.rowcount > 0


def list_items(conn: sqlite3.Connection, *, category: str | None = None,
               subcategory: str | None = None, platform: str | None = None,
               search: str | None = None) -> list[sqlite3.Row]:
    sql, args = "SELECT * FROM items WHERE 1=1", []
    for col, val in (("category", category), ("subcategory", subcategory), ("platform", platform)):
        if val:
            sql += f" AND {col} = ?"
            args.append(val)
    if search:
        sql += (" AND (title LIKE ? ESCAPE '!' OR note LIKE ? ESCAPE '!'"
                " OR url LIKE ? ESCAPE '!')")
        esc = search.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        args += [f"%{esc}%"] * 3
    sql += " ORDER BY created_at DESC, id DESC"
    return conn.execute(sql, args).fetchall()


def move_item(conn: sqlite3.Connection, item_id: int, category: str, subcategory: str) -> bool:
    cur = conn.execute("UPDATE items SET category = ?, subcategory = ? WHERE id = ?",
                       (category, subcategory, item_id))
    conn.commit()
    return cur.rowcount > 0


def set_note(conn: sqlite3.Connection, item_id: int, note: str) -> bool:
    cur = conn.execute("UPDATE items SET note = ? WHERE id = ?", (note, item_id))
    conn.commit()
    return cur.rowcount > 0


def set_status(conn: sqlite3.Connection, item_id: int, status: str, *,
               file_path: str = "", error: str = "") -> bool:
    if status not in STATUSES:
        raise ValueError(f"Geçersiz durum: {status}")
    cur = conn.execute("UPDATE items SET status = ?, file_path = ?, error = ? WHERE id = ?",
                       (status, file_path, error, item_id))
    conn.commit()
    return cur.rowcount > 0


def delete_item(conn: sqlite3.Connection, item_id: int) -> bool:
    cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    return cur.rowcount > 0
