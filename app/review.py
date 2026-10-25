"""Video inceleme: üretilen videolar burada izlenir, tam istenen ana zaman damgalı not düşülür,
notlar bitince "Değişikliğe başla" ile revizyon talebi oluşur.

Komut satırı (Claude oturumlarından; her üretilen video buraya kaydedilir):
  python izle.py ekle <dosya> --baslik "..." [--marka X] [--format yatay|short] [--platform youtube] [--proje <klasor>]
  python izle.py yeni-surum <video_id> <dosya>     # revizyon sonrası yeni sürüm
  python izle.py bekleyen                          # "Değişikliğe başla" denmiş videoların notları (revizyon istemi)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from . import board, channels

KINDS = ("yatay", "short")
# Claude'a verilen istemlerde yazılan komut: kullanıcının bilgisayarındaki izle.py (sunucuda IZLE_YOLU ile değiştirilebilir)
IZLE = os.environ.get("IZLE_YOLU", r"C:\Users\ozkan\Desktop\smDataAnalyze\izle.py")
IZLE_CMD = f'python "{IZLE}"'
STATUSES = ("inceleme", "revizyon", "onaylandi")
VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS rv_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    brand TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'yatay',
    platform TEXT NOT NULL DEFAULT '',
    project_dir TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'inceleme',
    task_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS rv_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES rv_videos(id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (video_id, n)
);
CREATE TABLE IF NOT EXISTS rv_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES rv_versions(id) ON DELETE CASCADE,
    t REAL NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class ReviewError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def fmt_time(t: float) -> str:
    m, s = divmod(round(max(t, 0.0), 1), 60)
    return f"{int(m)}:{s:04.1f}"


def _check_file(path: str) -> str:
    p = Path(path).expanduser()
    if p.suffix.lower() not in VIDEO_EXT:
        raise ReviewError("Desteklenen biçimler: " + ", ".join(sorted(VIDEO_EXT)))
    if not p.is_file():
        raise ReviewError(f"Dosya yok: {p}", 404)
    return str(p.resolve())


def _touch(conn: sqlite3.Connection, video_id: int) -> None:
    conn.execute("UPDATE rv_videos SET updated_at = datetime('now') WHERE id = ?", (video_id,))


def add_video(conn: sqlite3.Connection, path: str, title: str, *, brand: str = "", kind: str = "yatay",
              platform: str = "", project_dir: str = "", category: str = "") -> tuple[int, bool]:
    """(video_id, yeni_mi). Aynı dosya yolu ikinci kez eklenmez."""
    full = _check_file(path)
    title = " ".join(title.split())
    if not title or len(title) > 200:
        raise ReviewError("Başlık 1-200 karakter olmalı")
    if kind not in KINDS:
        raise ReviewError("Biçim: " + ", ".join(KINDS))
    row = conn.execute("SELECT video_id FROM rv_versions WHERE path = ?", (full,)).fetchone()
    if row:
        return row["video_id"], False
    brand = " ".join(brand.split())
    try:
        ch = channels.ensure_channel(conn, brand)
        cat = channels.ensure_cat(conn, ch, category, "v") if category.strip() and ch else None
    except channels.ChannelError as e:
        raise ReviewError(str(e))
    cur = conn.execute("INSERT INTO rv_videos (title, brand, kind, platform, project_dir, channel_id, cat_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (title, brand.strip()[:60], kind, platform.strip()[:20], project_dir.strip()[:500], ch, cat))
    vid = cur.lastrowid
    conn.execute("INSERT INTO rv_versions (video_id, n, path) VALUES (?, 1, ?)", (vid, full))
    conn.commit()
    board.add_message(conn, "sistem", f"İncelemeye hazır video: {title}")
    return vid, True


def _task_ready(conn: sqlite3.Connection, task_id: int | None, actor: str) -> None:
    row = task_id and conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row and row["status"] in ("bekliyor", "uretimde", "sorun"):
        board.update_task(conn, task_id, status="hazir", actor=actor)


def add_version(conn: sqlite3.Connection, video_id: int, path: str) -> int:
    """Revizyon sonrası yeni sürüm; video tekrar 'inceleme' durumuna döner, pano işi 'hazır' olur."""
    video = conn.execute("SELECT * FROM rv_videos WHERE id = ?", (video_id,)).fetchone()
    if video is None:
        raise ReviewError("Video yok", 404)
    full = _check_file(path)
    if conn.execute("SELECT 1 FROM rv_versions WHERE path = ?", (full,)).fetchone():
        raise ReviewError("Bu dosya zaten bir sürüm olarak kayıtlı (revize edilmiş yeni dosya ver)")
    n = conn.execute("SELECT COALESCE(MAX(n), 0) + 1 FROM rv_versions WHERE video_id = ?", (video_id,)).fetchone()[0]
    vcur = conn.execute("INSERT INTO rv_versions (video_id, n, path) VALUES (?, ?, ?)", (video_id, n, full))
    conn.execute("UPDATE rv_videos SET status = 'inceleme', updated_at = datetime('now') WHERE id = ?", (video_id,))
    conn.commit()
    _task_ready(conn, video["task_id"], "claude")
    board.add_message(conn, "claude", f"“{video['title']}” revize edildi: sürüm {n} incelemeye hazır")
    return vcur.lastrowid


def _guard_open(conn: sqlite3.Connection, video_id: int) -> None:
    """Revizyon istendiyse notlar donar: Claude'un okuyacağı istem ile ekrandaki notlar aynı kalsın."""
    row = conn.execute("SELECT status FROM rv_videos WHERE id = ?", (video_id,)).fetchone()
    if row is not None and row["status"] == "revizyon":
        raise ReviewError("Revizyon istendi; notlar donduruldu", 409)


def _version(conn: sqlite3.Connection, version_id: int) -> sqlite3.Row:
    v = conn.execute("SELECT * FROM rv_versions WHERE id = ?", (version_id,)).fetchone()
    if v is None:
        raise ReviewError("Sürüm yok", 404)
    return v


def media_path(conn: sqlite3.Connection, version_id: int) -> str:
    return _version(conn, version_id)["path"]


def list_videos(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM rv_videos ORDER BY updated_at DESC, id DESC"):
        v = dict(r)
        last = conn.execute("SELECT id, n FROM rv_versions WHERE video_id = ? ORDER BY n DESC LIMIT 1", (r["id"],)).fetchone()
        if last is None:
            continue
        v["version_id"], v["version_n"] = last["id"], last["n"]
        v["note_count"] = conn.execute("SELECT COUNT(*) FROM rv_notes WHERE version_id = ?", (last["id"],)).fetchone()[0]
        out.append(v)
    return out


def tree(conn: sqlite3.Connection) -> dict:
    """Arayüzün tek çağrıda aldığı özet: kanallar > başlıklar, videolar ve metinler (içeriksiz)."""
    from . import texts
    return {"channels": channels.channel_list(conn), "videos": list_videos(conn), "docs": texts.list_docs(conn)}


def patch_video(conn: sqlite3.Connection, video_id: int, *, title: str | None = None, dismissed: bool | None = None) -> None:
    if conn.execute("SELECT 1 FROM rv_videos WHERE id = ?", (video_id,)).fetchone() is None:
        raise ReviewError("Video yok", 404)
    if title is not None:
        title = " ".join(title.split())
        if not title or len(title) > 200:
            raise ReviewError("Başlık 1-200 karakter olmalı")
        conn.execute("UPDATE rv_videos SET title = ? WHERE id = ?", (title, video_id))
    if dismissed is not None:
        conn.execute("UPDATE rv_videos SET dismissed = ? WHERE id = ?", (int(dismissed), video_id))
    conn.commit()


def get_video(conn: sqlite3.Connection, video_id: int) -> dict:
    r = conn.execute("SELECT * FROM rv_videos WHERE id = ?", (video_id,)).fetchone()
    if r is None:
        raise ReviewError("Video yok", 404)
    v = dict(r)
    v["versions"] = []
    for ver in conn.execute("SELECT id, n, created_at, path FROM rv_versions WHERE video_id = ? ORDER BY n", (video_id,)):
        d = {"id": ver["id"], "n": ver["n"], "created_at": ver["created_at"], "file": Path(ver["path"]).name,
             "exists": Path(ver["path"]).is_file()}
        d["notes"] = [dict(n) for n in conn.execute(
            "SELECT id, t, text, created_at FROM rv_notes WHERE version_id = ? ORDER BY t, id", (ver["id"],))]
        v["versions"].append(d)
    return v


def _latest_version_id(conn: sqlite3.Connection, video_id: int) -> int:
    return conn.execute("SELECT id FROM rv_versions WHERE video_id = ? ORDER BY n DESC LIMIT 1", (video_id,)).fetchone()["id"]


def add_note(conn: sqlite3.Connection, version_id: int, t: float, text: str) -> int:
    text = text.strip()
    if not text or len(text) > 2000:
        raise ReviewError("Not boş olamaz (en çok 2000 karakter)")
    if not (0 <= t <= 24 * 3600):
        raise ReviewError("Geçersiz zaman")
    ver = _version(conn, version_id)
    if ver["id"] != _latest_version_id(conn, ver["video_id"]):
        raise ReviewError("Not yalnızca son sürüme eklenebilir", 409)
    _guard_open(conn, ver["video_id"])
    cur = conn.execute("INSERT INTO rv_notes (version_id, t, text) VALUES (?, ?, ?)", (version_id, round(t, 2), text))
    _touch(conn, ver["video_id"])
    conn.commit()
    return cur.lastrowid


def _note_version(conn: sqlite3.Connection, note_id: int) -> sqlite3.Row:
    n = conn.execute("SELECT n.id, v.id AS version_id, v.video_id FROM rv_notes n JOIN rv_versions v ON v.id = n.version_id "
                     "WHERE n.id = ?", (note_id,)).fetchone()
    if n is None:
        raise ReviewError("Not yok", 404)
    if n["version_id"] != _latest_version_id(conn, n["video_id"]):
        raise ReviewError("Eski sürümün notu değiştirilemez", 409)
    _guard_open(conn, n["video_id"])
    return n


def edit_note(conn: sqlite3.Connection, note_id: int, text: str) -> None:
    text = text.strip()
    if not text or len(text) > 2000:
        raise ReviewError("Not boş olamaz (en çok 2000 karakter)")
    n = _note_version(conn, note_id)
    conn.execute("UPDATE rv_notes SET text = ? WHERE id = ?", (text, note_id))
    _touch(conn, n["video_id"])
    conn.commit()


def delete_note(conn: sqlite3.Connection, note_id: int) -> None:
    n = _note_version(conn, note_id)
    conn.execute("DELETE FROM rv_notes WHERE id = ?", (note_id,))
    _touch(conn, n["video_id"])
    conn.commit()


def revision_prompt(conn: sqlite3.Connection, video_id: int) -> str:
    """Claude'a verilecek revizyon istemi: video, dosya, proje klasörü ve zaman damgalı notlar."""
    v = get_video(conn, video_id)
    last = v["versions"][-1]
    lines = [f"Video revizyonu: “{v['title']}” (video #{v['id']}, {v['kind']}, sürüm {last['n']})"]
    if v["brand"] or v["platform"]:
        lines.append("Kanal/platform: " + " · ".join(x for x in (v["brand"], v["platform"]) if x))
    if v["project_dir"]:
        lines.append(f"Proje klasörü: {v['project_dir']}")
    path = conn.execute("SELECT path FROM rv_versions WHERE id = ?", (last["id"],)).fetchone()["path"]
    # Yayındaki sunucuda dosya yolu kullanıcının bilgisayarında yoktur: yalnızca yerelde varsa yaz
    lines.append(f"Güncel dosya: {path}" if Path(path).is_file() and not path.startswith("/data/")
                 else f"Güncel dosya: sunucuda ({Path(path).name}); proje klasöründeki son çıktıdan devam et")
    lines.append("")
    lines.append("Notlar (zaman → ne değişsin):")
    lines += [f"- [{fmt_time(n['t'])}] {n['text']}" for n in last["notes"]]
    lines.append("")
    lines.append("Yap: videoyu yeniden üret; her notta yalnızca o noktayı değiştir. Bitince yeni dosyayı yükle:")
    lines.append(f'{IZLE_CMD} yeni-surum {v["id"]} "<yeni video dosyası>"')
    return "\n".join(lines)


def request_revision(conn: sqlite3.Connection, video_id: int) -> str:
    v = get_video(conn, video_id)
    last = v["versions"][-1]
    if not last["notes"]:
        raise ReviewError("Önce en az bir not ekle")
    if v["status"] == "revizyon":
        raise ReviewError("Revizyon zaten istendi", 409)
    # Önce durumu atomik al: iki eşzamanlı istekten yalnızca biri geçer
    if conn.execute("UPDATE rv_videos SET status = 'revizyon' WHERE id = ? AND status != 'revizyon'", (video_id,)).rowcount == 0:
        raise ReviewError("Revizyon zaten istendi", 409)
    prompt = revision_prompt(conn, video_id)
    if v["task_id"] and conn.execute("SELECT 1 FROM tasks WHERE id = ?", (v["task_id"],)).fetchone():
        board.update_task(conn, v["task_id"], status="uretimde", note=f"Revizyon: {len(last['notes'])} not", actor="sen")
        task_id = v["task_id"]
    else:
        task_id = board.add_task(conn, f"Revizyon: {v['title']}", brand=v["brand"], platform=v["platform"],
                                 note=f"{len(last['notes'])} zaman damgalı not", actor="sen")
        board.update_task(conn, task_id, status="uretimde", actor="sen")
    conn.execute("UPDATE rv_videos SET status = 'revizyon', task_id = ?, updated_at = datetime('now') WHERE id = ?",
                 (task_id, video_id))
    conn.commit()
    board.add_message(conn, "sen", f"“{v['title']}” için {len(last['notes'])} notla revizyon istedim")
    return prompt


def approve(conn: sqlite3.Connection, video_id: int) -> None:
    v = get_video(conn, video_id)
    if v["status"] != "inceleme":
        raise ReviewError("Yalnızca incelemedeki video onaylanır", 409)
    if v["versions"][-1]["notes"]:
        raise ReviewError("Notlar var: onay yerine Değişikliğe başla kullan", 409)
    conn.execute("UPDATE rv_videos SET status = 'onaylandi', updated_at = datetime('now') WHERE id = ?", (video_id,))
    conn.commit()
    _task_ready(conn, v["task_id"], "sen")


def delete_video(conn: sqlite3.Connection, video_id: int) -> bool:
    """Yalnızca kayıt silinir; video dosyasına dokunulmaz."""
    row = conn.execute("SELECT task_id FROM rv_videos WHERE id = ?", (video_id,)).fetchone()
    cur = conn.execute("DELETE FROM rv_videos WHERE id = ?", (video_id,))
    if row and row["task_id"]:
        conn.execute("DELETE FROM tasks WHERE id = ? AND status IN ('bekliyor', 'uretimde')", (row["task_id"],))
    conn.commit()
    return cur.rowcount > 0


def pending_prompts(conn: sqlite3.Connection) -> list[str]:
    return [revision_prompt(conn, r["id"]) for r in
            conn.execute("SELECT id FROM rv_videos WHERE status = 'revizyon' ORDER BY updated_at")]


def main(argv: list[str] | None = None) -> int:
    from .izle_cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
