"""SQLite katmanı: kayıtlar (items) ve plan kartları (cards)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import analytics, board, channels, review, texts, vidanalysis

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
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
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
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # bot, web ve indirme ayrı bağlantılarla çalışır
    conn.executescript(SCHEMA)
    conn.executescript(analytics.SCHEMA)
    conn.executescript(board.SCHEMA)
    conn.executescript(review.SCHEMA)
    conn.executescript(channels.SCHEMA)
    conn.executescript(texts.SCHEMA)
    conn.executescript(vidanalysis.SCHEMA)
    channels.migrate(conn)
    analytics.migrate(conn)
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


def claim_for_download(conn: sqlite3.Connection, item_id: int) -> bool:
    """Durumu tek SQL ile 'bekliyor' yapar; zaten sırada/iniyorsa veya kayıt yoksa False (çift indirmeyi önler)."""
    cur = conn.execute(
        "UPDATE items SET status = 'bekliyor', error = '' "
        "WHERE id = ? AND status NOT IN ('bekliyor', 'iniyor')", (item_id,))
    conn.commit()
    return cur.rowcount > 0


def delete_item(conn: sqlite3.Connection, item_id: int) -> bool:
    cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    return cur.rowcount > 0


# ---- Plan kartları ----

def create_card(conn: sqlite3.Connection, title: str, note: str = "") -> int:
    cur = conn.execute("INSERT INTO cards (title, note) VALUES (?, ?)", (title, note))
    conn.commit()
    return cur.lastrowid


def update_card(conn: sqlite3.Connection, card_id: int, *, title: str | None = None,
                note: str | None = None) -> bool:
    if conn.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone() is None:
        return False
    if title is not None:
        conn.execute("UPDATE cards SET title = ? WHERE id = ?", (title, card_id))
    if note is not None:
        conn.execute("UPDATE cards SET note = ? WHERE id = ?", (note, card_id))
    conn.commit()
    return True


def delete_card(conn: sqlite3.Connection, card_id: int) -> bool:
    cur = conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    conn.commit()
    return cur.rowcount > 0


def _card_items(conn: sqlite3.Connection, card_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT i.*, ci.position AS position, ci.note AS card_note FROM card_items ci "
        "JOIN items i ON i.id = ci.item_id WHERE ci.card_id = ? "
        "ORDER BY ci.position, i.id", (card_id,)).fetchall()
    return [dict(r) for r in rows]


def get_card(conn: sqlite3.Connection, card_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        return None
    card = dict(row)
    card["items"] = _card_items(conn, card_id)
    return card


def list_cards(conn: sqlite3.Connection) -> list[dict]:
    ids = [r["id"] for r in conn.execute("SELECT id FROM cards ORDER BY id DESC")]
    return [get_card(conn, i) for i in ids]


def add_card_item(conn: sqlite3.Connection, card_id: int, item_id: int) -> bool:
    """Karta video ekler (sona). Kart/video yoksa veya zaten ekliyse False."""
    if conn.execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone() is None \
            or conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None:
        return False
    pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM card_items WHERE card_id = ?",
                       (card_id,)).fetchone()[0]
    cur = conn.execute("INSERT OR IGNORE INTO card_items (card_id, item_id, position) VALUES (?, ?, ?)",
                       (card_id, item_id, pos))
    conn.commit()
    return cur.rowcount > 0


def remove_card_item(conn: sqlite3.Connection, card_id: int, item_id: int) -> bool:
    cur = conn.execute("DELETE FROM card_items WHERE card_id = ? AND item_id = ?", (card_id, item_id))
    conn.commit()
    return cur.rowcount > 0


def set_card_item_note(conn: sqlite3.Connection, card_id: int, item_id: int, note: str) -> bool:
    cur = conn.execute("UPDATE card_items SET note = ? WHERE card_id = ? AND item_id = ?",
                       (note, card_id, item_id))
    conn.commit()
    return cur.rowcount > 0


def move_card_item(conn: sqlite3.Connection, card_id: int, item_id: int, direction: int) -> bool:
    """direction -1 = yukarı, +1 = aşağı. Sıra numaraları yeniden 0..n-1 yazılır."""
    order = [r["item_id"] for r in conn.execute(
        "SELECT item_id FROM card_items WHERE card_id = ? ORDER BY position, item_id", (card_id,))]
    if item_id not in order or direction not in (-1, 1):
        return False
    i = order.index(item_id)
    j = i + direction
    if 0 <= j < len(order):
        order[i], order[j] = order[j], order[i]
    for pos, iid in enumerate(order):
        conn.execute("UPDATE card_items SET position = ? WHERE card_id = ? AND item_id = ?",
                     (pos, card_id, iid))
    conn.commit()
    return True


# ---- Genel notlar (todo listesi) ----

def add_todo(conn: sqlite3.Connection, text: str) -> dict:
    cur = conn.execute("INSERT INTO todos (text) VALUES (?)", (text,))
    conn.commit()
    return dict(conn.execute("SELECT * FROM todos WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_todos(conn: sqlite3.Connection) -> list[dict]:
    """Açık olanlar eklenme sırasıyla; tamamlananlar sonra."""
    return [dict(r) for r in conn.execute("SELECT * FROM todos ORDER BY done, id")]


def update_todo(conn: sqlite3.Connection, todo_id: int, *, text: str | None = None,
                done: bool | None = None) -> dict | None:
    if conn.execute("SELECT 1 FROM todos WHERE id = ?", (todo_id,)).fetchone() is None:
        return None
    if text is not None:
        conn.execute("UPDATE todos SET text = ? WHERE id = ?", (text, todo_id))
    if done is not None:
        conn.execute("UPDATE todos SET done = ? WHERE id = ?", (1 if done else 0, todo_id))
    conn.commit()
    return dict(conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone())


def delete_todo(conn: sqlite3.Connection, todo_id: int) -> bool:
    cur = conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    conn.commit()
    return cur.rowcount > 0


def clear_done_todos(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM todos WHERE done = 1")
    conn.commit()
    return cur.rowcount
