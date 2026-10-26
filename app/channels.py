"""Kanal > başlık (kategori) yapısı: inceleme modülündeki videolar ve metinler bu ağaca yerleşir."""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS rv_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS rv_cats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL REFERENCES rv_channels(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES rv_cats(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'v',
    name TEXT NOT NULL COLLATE NOCASE,
    position INTEGER NOT NULL DEFAULT 0
);
"""
ITEM_TABLES = ("rv_videos", "rv_docs")
KIND_OF = {"rv_videos": "v", "rv_docs": "m"}  # başlıklar videolar ('v') ve metinler ('m') için ayrı tutulur


class ChannelError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def clean_name(name: str, what: str = "Ad") -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > 60 or any(c in name for c in "<>/\\") or any(ord(c) < 32 for c in name):
        raise ChannelError(f"{what} 1-60 karakter olmalı ( < > / \\ olmadan)")
    return name


_migrated: set[str] = set()


def migrate(conn: sqlite3.Connection) -> None:
    """Eski kayıtları kanal/başlık yapısına taşır (süreç başına veritabanı başına bir kez; tekrar çalışması zararsız)."""
    key = next((r["file"] for r in conn.execute("PRAGMA database_list") if r["name"] == "main"), "")
    if key and key in _migrated:
        return
    _migrate(conn)
    if key:
        _migrated.add(key)


def _migrate(conn: sqlite3.Connection) -> None:
    ccols = {r["name"] for r in conn.execute("PRAGMA table_info(rv_cats)")}
    if "kind" not in ccols:
        conn.execute("ALTER TABLE rv_cats ADD COLUMN kind TEXT NOT NULL DEFAULT 'v'")
        # yalnızca metinlerin kullandığı eski başlıklar metin başlığı olur
        conn.execute("UPDATE rv_cats SET kind = 'm' WHERE id IN (SELECT cat_id FROM rv_docs WHERE cat_id IS NOT NULL) "
                     "AND id NOT IN (SELECT cat_id FROM rv_videos WHERE cat_id IS NOT NULL)")
    dcols = {r["name"] for r in conn.execute("PRAGMA table_info(rv_docs)")}
    if "base" not in dcols:
        conn.execute("ALTER TABLE rv_docs ADD COLUMN base TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE rv_docs SET base = content")  # eski metinlerde fark bu andan itibaren izlenir
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(rv_videos)")}
    for col, ddl in (("channel_id", "INTEGER"), ("cat_id", "INTEGER"), ("dismissed", "INTEGER NOT NULL DEFAULT 0")):
        if col not in cols:
            conn.execute(f"ALTER TABLE rv_videos ADD COLUMN {col} {ddl}")
    for r in conn.execute("SELECT DISTINCT brand FROM rv_videos WHERE channel_id IS NULL AND brand != ''").fetchall():
        try:
            ch = ensure_channel(conn, r["brand"])  # adı normalleştirir ("A  B" -> "A B")
        except ChannelError:
            continue
        conn.execute("UPDATE rv_videos SET channel_id = ? WHERE channel_id IS NULL AND brand = ?", (ch, r["brand"]))
    conn.commit()


def ensure_channel(conn: sqlite3.Connection, name: str) -> int | None:
    name = (name or "").strip()
    if not name:
        return None
    name = clean_name(name, "Kanal adı")
    row = conn.execute("SELECT id FROM rv_channels WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM rv_channels").fetchone()[0]
    return conn.execute("INSERT INTO rv_channels (name, position) VALUES (?, ?)", (name, pos)).lastrowid


def _find_cat(conn: sqlite3.Connection, channel_id: int, parent_id: int | None, name: str, kind: str, skip: int = 0):
    return conn.execute("SELECT id FROM rv_cats WHERE channel_id = ? AND parent_id IS ? AND name = ? AND kind = ? AND id != ?",
                        (channel_id, parent_id, name, kind, skip)).fetchone()


def _new_cat(conn: sqlite3.Connection, channel_id: int, parent_id: int | None, name: str, kind: str) -> int:
    pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM rv_cats WHERE channel_id = ? AND parent_id IS ?",
                       (channel_id, parent_id)).fetchone()[0]
    return conn.execute("INSERT INTO rv_cats (channel_id, parent_id, name, position, kind) VALUES (?, ?, ?, ?, ?)",
                        (channel_id, parent_id, name, pos, kind)).lastrowid


def ensure_cat(conn: sqlite3.Connection, channel_id: int, path: str, kind: str = "v") -> int:
    """'Başlık' veya 'Başlık/Alt başlık' (en çok 2 düzey); yoksa oluşturur, son düzeyin id'sini döner."""
    parts = [p for p in (x.strip() for x in path.split("/")) if p]
    if not parts or len(parts) > 2:
        raise ChannelError("Başlık yolu 'Başlık' ya da 'Başlık/Alt başlık' olmalı")
    parent = None
    for p in parts:
        name = clean_name(p, "Başlık adı")
        row = _find_cat(conn, channel_id, parent, name, kind)
        parent = row["id"] if row else _new_cat(conn, channel_id, parent, name, kind)
    return parent


def add_channel(conn: sqlite3.Connection, name: str) -> int:
    name = clean_name(name, "Kanal adı")
    if conn.execute("SELECT 1 FROM rv_channels WHERE name = ?", (name,)).fetchone():
        raise ChannelError("Bu kanal zaten var", 409)
    cid = ensure_channel(conn, name)
    conn.commit()
    return cid


def rename_channel(conn: sqlite3.Connection, channel_id: int, name: str) -> None:
    name = clean_name(name, "Kanal adı")
    if not conn.execute("SELECT 1 FROM rv_channels WHERE id = ?", (channel_id,)).fetchone():
        raise ChannelError("Kanal yok", 404)
    if conn.execute("SELECT 1 FROM rv_channels WHERE name = ? AND id != ?", (name, channel_id)).fetchone():
        raise ChannelError("Bu adda başka bir kanal var", 409)
    conn.execute("UPDATE rv_channels SET name = ? WHERE id = ?", (name, channel_id))
    conn.execute("UPDATE rv_videos SET brand = ? WHERE channel_id = ?", (name, channel_id))
    conn.commit()


def delete_channel(conn: sqlite3.Connection, channel_id: int) -> None:
    """Yalnızca boş kanal silinir (temizlenmiş/arşivdeki öğeler de sayılır: kayıp olmasın)."""
    n = sum(conn.execute(f"SELECT COUNT(*) FROM {t} WHERE channel_id = ?", (channel_id,)).fetchone()[0] for t in ITEM_TABLES)
    if n:
        raise ChannelError(f"Kanalda {n} öğe var; önce taşı veya sil", 409)
    if not conn.execute("DELETE FROM rv_channels WHERE id = ?", (channel_id,)).rowcount:
        raise ChannelError("Kanal yok", 404)
    conn.commit()


def add_cat(conn: sqlite3.Connection, channel_id: int, name: str, parent_id: int | None = None, kind: str = "v") -> int:
    if kind not in ("v", "m"):
        raise ChannelError("Tür v (video) ya da m (metin) olmalı")
    if not conn.execute("SELECT 1 FROM rv_channels WHERE id = ?", (channel_id,)).fetchone():
        raise ChannelError("Kanal yok", 404)
    if parent_id is not None:
        p = conn.execute("SELECT channel_id, parent_id, kind FROM rv_cats WHERE id = ?", (parent_id,)).fetchone()
        if p is not None:
            kind = p["kind"]
        if p is None or p["channel_id"] != channel_id:
            raise ChannelError("Üst başlık bu kanalda yok", 404)
        if p["parent_id"] is not None:
            raise ChannelError("Alt başlığın altına yeni düzey eklenemez (en çok Başlık > Alt başlık)")
    name = clean_name(name, "Başlık adı")
    if _find_cat(conn, channel_id, parent_id, name, kind):
        raise ChannelError("Bu ad burada zaten var", 409)
    cid = _new_cat(conn, channel_id, parent_id, name, kind)
    conn.commit()
    return cid


def rename_cat(conn: sqlite3.Connection, cat_id: int, name: str) -> None:
    name = clean_name(name, "Başlık adı")
    row = conn.execute("SELECT channel_id, parent_id, kind FROM rv_cats WHERE id = ?", (cat_id,)).fetchone()
    if row is None:
        raise ChannelError("Başlık yok", 404)
    if _find_cat(conn, row["channel_id"], row["parent_id"], name, row["kind"], cat_id):
        raise ChannelError("Bu adda başka bir başlık var", 409)
    conn.execute("UPDATE rv_cats SET name = ? WHERE id = ?", (name, cat_id))
    conn.commit()


def delete_cat(conn: sqlite3.Connection, cat_id: int) -> None:
    """Başlık (ve alt başlıkları) silinince içindekiler 'Başlıksız'a düşer, öğe silinmez."""
    ids = [cat_id] + [r["id"] for r in conn.execute("SELECT id FROM rv_cats WHERE parent_id = ?", (cat_id,))]
    marks = ",".join("?" * len(ids))
    for t in ITEM_TABLES:
        conn.execute(f"UPDATE {t} SET cat_id = NULL WHERE cat_id IN ({marks})", ids)
    if not conn.execute("DELETE FROM rv_cats WHERE id = ?", (cat_id,)).rowcount:
        raise ChannelError("Başlık yok", 404)
    conn.commit()


def place(conn: sqlite3.Connection, table: str, item_id: int, *, channel_id: int | None, cat_id: int | None,
          set_channel: bool, set_cat: bool) -> None:
    """Öğeyi kanal/başlığa yerleştirir. Başlık, seçilen kanala ait olmalı; kanal değişince başlık sıfırlanır."""
    assert table in ITEM_TABLES
    row = conn.execute(f"SELECT channel_id, cat_id FROM {table} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ChannelError("Öğe yok", 404)
    ch = channel_id if set_channel else row["channel_id"]
    cat = cat_id if set_cat else (None if set_channel and ch != row["channel_id"] else row["cat_id"])
    if ch is not None and not conn.execute("SELECT 1 FROM rv_channels WHERE id = ?", (ch,)).fetchone():
        raise ChannelError("Kanal yok", 404)
    if cat is not None:
        c = conn.execute("SELECT channel_id, kind FROM rv_cats WHERE id = ?", (cat,)).fetchone()
        if c is None or c["channel_id"] != ch:
            raise ChannelError("Başlık bu kanala ait değil", 400)
        if c["kind"] != KIND_OF[table]:
            raise ChannelError("Video başlığına metin (ya da tersi) konamaz", 400)
    name = conn.execute("SELECT name FROM rv_channels WHERE id = ?", (ch,)).fetchone() if ch is not None else None
    extra = ", brand = ?" if table == "rv_videos" else ""
    args = [ch, cat] + ([name["name"] if name else ""] if table == "rv_videos" else []) + [item_id]
    conn.execute(f"UPDATE {table} SET channel_id = ?, cat_id = ?{extra}, updated_at = datetime('now') WHERE id = ?", args)
    conn.commit()


def channel_list(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for c in conn.execute("SELECT * FROM rv_channels ORDER BY position, id"):
        d = dict(c)
        d["cats"] = [dict(x) for x in conn.execute(
            "SELECT id, name, parent_id, kind FROM rv_cats WHERE channel_id = ? ORDER BY position, id", (c["id"],))]
        out.append(d)
    return out
