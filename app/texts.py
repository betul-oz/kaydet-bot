"""Metin inceleme: yazılan metinler (senaryo, açıklama, plan) cümle bazında yorumlanır, doğrudan düzenlenir.
Yorumlar bitince "Değişikliğe başla" ile revizyon istenir; Claude `izle.py metin-guncelle` ile yeni metni yükler.
"""
from __future__ import annotations

import sqlite3

from . import board, channels
from .review import IZLE_CMD

STATES = ("acik", "uygulandi")
MAX_DOC = 3 * 1024 * 1024
BACKUPS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS rv_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    channel_id INTEGER,
    cat_id INTEGER,
    status TEXT NOT NULL DEFAULT 'inceleme',
    dirty INTEGER NOT NULL DEFAULT 0,
    dismissed INTEGER NOT NULL DEFAULT 0,
    task_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS rv_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES rv_docs(id) ON DELETE CASCADE,
    quote TEXT NOT NULL,
    occ INTEGER NOT NULL DEFAULT 0,
    line INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'acik',
    claude_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS rv_doc_backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES rv_docs(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class TextError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _doc(conn: sqlite3.Connection, doc_id: int) -> sqlite3.Row:
    d = conn.execute("SELECT * FROM rv_docs WHERE id = ?", (doc_id,)).fetchone()
    if d is None:
        raise TextError("Metin yok", 404)
    return d


def _guard_open(d: sqlite3.Row) -> None:
    if d["status"] == "revizyon":
        raise TextError("Revizyon istendi; metin ve yorumlar donduruldu", 409)


def _norm(content: str) -> str:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if len(content.encode("utf-8")) > MAX_DOC:
        raise TextError("Metin çok büyük (en çok 3 MB)", 413)
    return content


def add_doc(conn: sqlite3.Connection, title: str, content: str, *, brand: str = "", category: str = "",
            source_path: str = "") -> tuple[int, bool]:
    title = " ".join(title.split())
    if not title or len(title) > 200:
        raise TextError("Başlık 1-200 karakter olmalı")
    if source_path:
        row = conn.execute("SELECT id FROM rv_docs WHERE source_path = ?", (source_path,)).fetchone()
        if row:
            return row["id"], False
    try:
        ch = channels.ensure_channel(conn, brand)
        cat = channels.ensure_cat(conn, ch, category, "m") if category.strip() and ch else None
    except channels.ChannelError as e:
        raise TextError(str(e))
    cur = conn.execute("INSERT INTO rv_docs (title, content, source_path, channel_id, cat_id) VALUES (?, ?, ?, ?, ?)",
                       (title, _norm(content), source_path[:500], ch, cat))
    conn.commit()
    board.add_message(conn, "sistem", f"İncelemeye hazır metin: {title}")
    return cur.lastrowid, True


def _comments(conn: sqlite3.Connection, doc_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, quote, occ, line, text, state, claude_note, created_at, updated_at FROM rv_comments "
        "WHERE doc_id = ? ORDER BY line, id", (doc_id,))]


def get_doc(conn: sqlite3.Connection, doc_id: int) -> dict:
    d = dict(_doc(conn, doc_id))
    d["comments"] = _comments(conn, doc_id)
    return d


def list_docs(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT id, title, source_path, channel_id, cat_id, status, dirty, dismissed, created_at, updated_at "
                          "FROM rv_docs ORDER BY updated_at DESC, id DESC"):
        d = dict(r)
        d["open_comments"] = conn.execute("SELECT COUNT(*) FROM rv_comments WHERE doc_id = ? AND state = 'acik'", (r["id"],)).fetchone()[0]
        out.append(d)
    return out


def patch_doc(conn: sqlite3.Connection, doc_id: int, *, title: str | None = None, dismissed: bool | None = None) -> None:
    _doc(conn, doc_id)
    if title is not None:
        title = " ".join(title.split())
        if not title or len(title) > 200:
            raise TextError("Başlık 1-200 karakter olmalı")
        conn.execute("UPDATE rv_docs SET title = ? WHERE id = ?", (title, doc_id))
    if dismissed is not None:
        conn.execute("UPDATE rv_docs SET dismissed = ? WHERE id = ?", (int(dismissed), doc_id))
    conn.commit()


def delete_doc(conn: sqlite3.Connection, doc_id: int) -> None:
    d = _doc(conn, doc_id)
    conn.execute("DELETE FROM rv_docs WHERE id = ?", (doc_id,))
    if d["task_id"]:
        conn.execute("DELETE FROM tasks WHERE id = ? AND status IN ('bekliyor', 'uretimde')", (d["task_id"],))
    conn.commit()


def _backup(conn: sqlite3.Connection, doc_id: int, old: str) -> None:
    conn.execute("INSERT INTO rv_doc_backups (doc_id, content) VALUES (?, ?)", (doc_id, old))
    conn.execute("DELETE FROM rv_doc_backups WHERE doc_id = ? AND id NOT IN "
                 "(SELECT id FROM rv_doc_backups WHERE doc_id = ? ORDER BY id DESC LIMIT ?)", (doc_id, doc_id, BACKUPS))


def save_content(conn: sqlite3.Connection, doc_id: int, content: str, *, expected_updated_at: str | None = None) -> str:
    """Arayüzden doğrudan düzenleme. Eski metin yedeklenir; Claude `metin-al` ile dosyaya yazana kadar 'dirty' kalır."""
    d = _doc(conn, doc_id)
    _guard_open(d)
    content = _norm(content)
    if expected_updated_at is not None and expected_updated_at != d["updated_at"]:
        raise TextError("Metin başka yerden değişti; sayfayı yenile", 409)
    if content != d["content"]:
        _backup(conn, doc_id, d["content"])
        conn.execute("UPDATE rv_docs SET content = ?, dirty = 1, updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?", (content, doc_id))
        conn.commit()
    return conn.execute("SELECT updated_at FROM rv_docs WHERE id = ?", (doc_id,)).fetchone()["updated_at"]


def add_comment(conn: sqlite3.Connection, doc_id: int, quote: str, text: str, *, line: int = 0, occ: int = 0) -> int:
    d = _doc(conn, doc_id)
    _guard_open(d)
    quote, text = quote.strip(), text.strip()
    if not quote or len(quote) > 800:
        raise TextError("Önce metinden bir cümle seç (en çok 800 karakter)")
    if not text or len(text) > 4000:
        raise TextError("Yorum boş olamaz (en çok 4000 karakter)")
    cur = conn.execute("INSERT INTO rv_comments (doc_id, quote, occ, line, text) VALUES (?, ?, ?, ?, ?)",
                       (doc_id, quote, max(occ, 0), max(line, 0), text))
    conn.execute("UPDATE rv_docs SET updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?", (doc_id,))
    conn.commit()
    return cur.lastrowid


def _comment(conn: sqlite3.Connection, comment_id: int) -> sqlite3.Row:
    c = conn.execute("SELECT c.*, d.status AS doc_status FROM rv_comments c JOIN rv_docs d ON d.id = c.doc_id WHERE c.id = ?",
                     (comment_id,)).fetchone()
    if c is None:
        raise TextError("Yorum yok", 404)
    return c


def edit_comment(conn: sqlite3.Connection, comment_id: int, text: str) -> None:
    c = _comment(conn, comment_id)
    if c["doc_status"] == "revizyon":
        raise TextError("Revizyon istendi; yorumlar donduruldu", 409)
    text = text.strip()
    if not text or len(text) > 4000:
        raise TextError("Yorum boş olamaz (en çok 4000 karakter)")
    conn.execute("UPDATE rv_comments SET text = ?, updated_at = datetime('now') WHERE id = ?", (text, comment_id))
    conn.commit()


def delete_comment(conn: sqlite3.Connection, comment_id: int) -> None:
    c = _comment(conn, comment_id)
    if c["doc_status"] == "revizyon":
        raise TextError("Revizyon istendi; yorumlar donduruldu", 409)
    conn.execute("DELETE FROM rv_comments WHERE id = ?", (comment_id,))
    conn.commit()


def revision_prompt(conn: sqlite3.Connection, doc_id: int) -> str:
    d = get_doc(conn, doc_id)
    ch = conn.execute("SELECT name FROM rv_channels WHERE id = ?", (d["channel_id"],)).fetchone() if d["channel_id"] else None
    lines = [f"Metin revizyonu: “{d['title']}” (metin #{d['id']})"]
    if ch:
        lines.append(f"Kanal: {ch['name']}")
    if d["source_path"]:
        lines.append(f"Kaynak dosya: {d['source_path']}")
    if d["dirty"]:
        lines.append(f"Kullanıcı metni arayüzde doğrudan düzenlemiş. Önce güncel metni dosyaya al: {IZLE_CMD} metin-al {d['id']}")
    open_ = [c for c in d["comments"] if c["state"] == "acik"]
    if open_:
        lines.append("")
        lines.append("Yorumlar (alıntı → ne değişsin):")
        lines += [f"- [satır {c['line'] + 1}] “{c['quote']}” → {c['text']}" for c in open_]
    lines.append("")
    lines.append("Yap: yorumları metne uygula; her yorumda yalnızca o noktayı değiştir. Bitince metni yükle:")
    lines.append(f'{IZLE_CMD} metin-guncelle {d["id"]} "<dosya>" --not "ne yaptın"')
    return "\n".join(lines)


def request_revision(conn: sqlite3.Connection, doc_id: int) -> str:
    d = _doc(conn, doc_id)
    if d["status"] == "revizyon":
        raise TextError("Revizyon zaten istendi", 409)
    n = conn.execute("SELECT COUNT(*) FROM rv_comments WHERE doc_id = ? AND state = 'acik'", (doc_id,)).fetchone()[0]
    if not n and not d["dirty"]:
        raise TextError("Önce en az bir yorum ekle (ya da metni düzenle)")
    if conn.execute("UPDATE rv_docs SET status = 'revizyon' WHERE id = ? AND status != 'revizyon'", (doc_id,)).rowcount == 0:
        raise TextError("Revizyon zaten istendi", 409)
    prompt = revision_prompt(conn, doc_id)
    ch = conn.execute("SELECT name FROM rv_channels WHERE id = ?", (d["channel_id"],)).fetchone() if d["channel_id"] else None
    brand = ch["name"] if ch else ""
    note = f"{n} yorum" + (" + doğrudan düzenleme" if d["dirty"] else "")
    if d["task_id"] and conn.execute("SELECT 1 FROM tasks WHERE id = ?", (d["task_id"],)).fetchone():
        board.update_task(conn, d["task_id"], status="uretimde", note=note, actor="sen")
        task_id = d["task_id"]
    else:
        task_id = board.add_task(conn, f"Metin revizyonu: {d['title']}", brand=brand, note=note, actor="sen")
        board.update_task(conn, task_id, status="uretimde", actor="sen")
    conn.execute("UPDATE rv_docs SET task_id = ?, updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?", (task_id, doc_id))
    conn.commit()
    board.add_message(conn, "sen", f"“{d['title']}” için {note} ile metin revizyonu istedim")
    return prompt


def apply_update(conn: sqlite3.Connection, doc_id: int, content: str, note: str = "", *, force: bool = False) -> None:
    """Claude'un revize ettiği metni yükler: açık yorumlar 'uygulandı' olur, metin tekrar incelemeye döner.
    Kullanıcının arayüzdeki düzenlemesini (dirty) ya da henüz revizyon istenmemiş yorumları sessizce ezmemek için
    bu durumlarda 409 verir (bilerek ezmek için force)."""
    d = _doc(conn, doc_id)
    if not force:
        if d["dirty"]:
            raise TextError(f"Kullanıcı metni arayüzde düzenlemiş: önce `izle.py metin-al {doc_id}` ile güncel metni al "
                            "(bilerek ezmek için --zorla)", 409)
        if d["status"] != "revizyon" and conn.execute("SELECT 1 FROM rv_comments WHERE doc_id = ? AND state = 'acik'", (doc_id,)).fetchone():
            raise TextError("Açık yorumlar var ama revizyon istenmedi; yorumları görmeden üzerine yazılmaz (bilerek için --zorla)", 409)
    content = _norm(content)
    if content != d["content"]:
        _backup(conn, doc_id, d["content"])
    conn.execute("UPDATE rv_docs SET content = ?, dirty = 0, status = 'inceleme', updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?",
                 (content, doc_id))
    conn.execute("UPDATE rv_comments SET state = 'uygulandi', claude_note = ?, updated_at = datetime('now') "
                 "WHERE doc_id = ? AND state = 'acik'", (note.strip()[:2000], doc_id))
    conn.commit()
    row = d["task_id"] and conn.execute("SELECT status FROM tasks WHERE id = ?", (d["task_id"],)).fetchone()
    if row and row["status"] in ("bekliyor", "uretimde", "sorun"):
        board.update_task(conn, d["task_id"], status="hazir", actor="claude")
    board.add_message(conn, "claude", f"“{d['title']}” metni revize edildi")


def mark_synced(conn: sqlite3.Connection, doc_id: int) -> None:
    """Güncel metin kaynak dosyaya yazıldı (izle.py metin-al)."""
    conn.execute("UPDATE rv_docs SET dirty = 0 WHERE id = ?", (doc_id,))
    conn.commit()


def approve(conn: sqlite3.Connection, doc_id: int) -> None:
    d = _doc(conn, doc_id)
    if d["status"] != "inceleme":
        raise TextError("Yalnızca incelemedeki metin onaylanır", 409)
    if conn.execute("SELECT 1 FROM rv_comments WHERE doc_id = ? AND state = 'acik'", (doc_id,)).fetchone():
        raise TextError("Açık yorumlar var: onay yerine Değişikliğe başla kullan", 409)
    conn.execute("UPDATE rv_docs SET status = 'onaylandi', updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') WHERE id = ?", (doc_id,))
    conn.commit()


def pending_prompts(conn: sqlite3.Connection) -> list[str]:
    return [revision_prompt(conn, r["id"]) for r in
            conn.execute("SELECT id FROM rv_docs WHERE status = 'revizyon' ORDER BY updated_at")]
