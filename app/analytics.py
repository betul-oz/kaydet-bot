"""Analiz: marka/hesap/gönderi verisi, yt-dlp ile herkese açık metrik çekme ve özet hesapları."""
from __future__ import annotations

import re
import sqlite3
import statistics
import threading
from datetime import datetime, timezone
from typing import Callable

from . import insights, planning, recommend

PLATFORMS = ("youtube", "tiktok", "instagram")
SHORT_MAX_SECONDS = 180
# profil adı olamayacak yol parçaları (video/kanal-kimliği linki yapıştırılmış demektir)
RESERVED = {"channel", "c", "user", "watch", "reel", "reels", "p", "shorts", "video", "playlist", "tv", "stories", "explore"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    followers INTEGER,
    sync_status TEXT NOT NULL DEFAULT '',
    sync_error TEXT NOT NULL DEFAULT '',
    synced_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (platform, handle)
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    ext_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    posted_at TEXT NOT NULL DEFAULT '',
    duration INTEGER,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    thumb_url TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, ext_id)
);
CREATE TABLE IF NOT EXISTS snapshots (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    taken_at TEXT NOT NULL DEFAULT (datetime('now')),
    views INTEGER,
    likes INTEGER,
    comments INTEGER
);
"""


class AnalyticsError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def clean_handle(platform: str, raw: str) -> str:
    """'@marka', 'https://www.tiktok.com/@marka/' ya da 'marka' -> 'marka'."""
    s = raw.strip()
    m = re.search(r"(?:youtube\.com|tiktok\.com|instagram\.com)/@?([^/?#\s]+)", s, re.I)
    if m:
        s = m.group(1)
    s = s.lstrip("@").strip()
    if s.lower() in RESERVED or not re.fullmatch(r"[\w.\-]{2,60}", s):
        raise AnalyticsError("Kullanıcı adı geçersiz. Profil adını (@marka) ya da profil linkini yaz; "
                             "video, kanal-kimliği (/channel/) ve /c/ linkleri desteklenmiyor")
    return s.lower()


PLATFORM_HOSTS = {"youtube": ("youtube.com", "youtu.be"), "tiktok": ("tiktok.com",),
                  "instagram": ("instagram.com", "instagr.am")}


def url_matches_platform(url: str, platform: str) -> bool:
    """Yalnızca https/http ve hesabın platformuna ait sunucu adı (SSRF ve yanlış hesaba ekleme önlemi)."""
    from urllib.parse import urlparse
    u = urlparse(url)
    if u.scheme not in ("http", "https") or u.username or u.password:
        return False
    host = (u.hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in PLATFORM_HOSTS.get(platform, ()))


def profile_url(platform: str, handle: str) -> str:
    return {"youtube": f"https://www.youtube.com/@{handle}",
            "tiktok": f"https://www.tiktok.com/@{handle}",
            "instagram": f"https://www.instagram.com/{handle}/"}[platform]


_migrated: set[str] = set()


def migrate(conn: sqlite3.Connection) -> None:
    """Eski hesaplardaki marka adlarından marka kayıtları oluşturur (süreç başına veritabanı başına bir kez)."""
    key = next((r["file"] for r in conn.execute("PRAGMA database_list") if r["name"] == "main"), "")
    if key and key in _migrated:
        return
    for r in conn.execute("SELECT DISTINCT brand FROM accounts WHERE brand != ''").fetchall():
        try:
            ensure_brand(conn, r["brand"])
        except AnalyticsError:
            pass
    conn.commit()
    if key:
        _migrated.add(key)


def clean_brand(name: str) -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > 60 or any(c in name for c in "<>/\\") or any(ord(c) < 32 for c in name):
        raise AnalyticsError("Marka adı 1-60 karakter olmalı ( < > / \\ olmadan)")
    return name


def ensure_brand(conn: sqlite3.Connection, name: str) -> int:
    name = clean_brand(name)
    row = conn.execute("SELECT id FROM brands WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    pos = conn.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM brands").fetchone()[0]
    return conn.execute("INSERT INTO brands (name, position) VALUES (?, ?)", (name, pos)).lastrowid


def add_brand(conn: sqlite3.Connection, name: str) -> int:
    name = clean_brand(name)
    if conn.execute("SELECT 1 FROM brands WHERE name = ?", (name,)).fetchone():
        raise AnalyticsError("Bu marka zaten var", 409)
    bid = ensure_brand(conn, name)
    conn.commit()
    return bid


def rename_brand(conn: sqlite3.Connection, brand_id: int, name: str) -> None:
    """Adı değişince hesaplar ve iş panosundaki (plan) kayıtlar da yeni adla eşleşir."""
    name = clean_brand(name)
    row = conn.execute("SELECT name FROM brands WHERE id = ?", (brand_id,)).fetchone()
    if row is None:
        raise AnalyticsError("Marka yok", 404)
    if conn.execute("SELECT 1 FROM brands WHERE name = ? AND id != ?", (name, brand_id)).fetchone():
        raise AnalyticsError("Bu adda başka bir marka var", 409)
    conn.execute("UPDATE brands SET name = ? WHERE id = ?", (name, brand_id))
    conn.execute("UPDATE accounts SET brand = ? WHERE brand = ? COLLATE NOCASE", (name, row["name"]))
    conn.execute("UPDATE tasks SET brand = ? WHERE brand = ? COLLATE NOCASE", (name, row["name"]))
    conn.commit()


def delete_brand(conn: sqlite3.Connection, brand_id: int) -> None:
    """Yalnızca hesabı olmayan marka silinir (veri kaybı olmasın): hesapları önce başka markaya taşı veya sil."""
    row = conn.execute("SELECT name FROM brands WHERE id = ?", (brand_id,)).fetchone()
    if row is None:
        raise AnalyticsError("Marka yok", 404)
    n = conn.execute("SELECT COUNT(*) FROM accounts WHERE brand = ? COLLATE NOCASE", (row["name"],)).fetchone()[0]
    if n:
        raise AnalyticsError(f"Markada {n} hesap var; önce hesapları başka markaya taşı veya sil", 409)
    conn.execute("DELETE FROM brands WHERE id = ?", (brand_id,))
    conn.commit()


def move_account(conn: sqlite3.Connection, account_id: int, brand_id: int) -> None:
    b = conn.execute("SELECT name FROM brands WHERE id = ?", (brand_id,)).fetchone()
    if b is None:
        raise AnalyticsError("Marka yok", 404)
    if not conn.execute("UPDATE accounts SET brand = ? WHERE id = ?", (b["name"], account_id)).rowcount:
        raise AnalyticsError("Hesap yok", 404)
    conn.commit()


def add_account(conn: sqlite3.Connection, brand: str, platform: str, raw_handle: str) -> int:
    brand = clean_brand(brand)
    if platform not in PLATFORMS:
        raise AnalyticsError("Platform youtube, tiktok veya instagram olmalı")
    handle = clean_handle(platform, raw_handle)
    brand = conn.execute("SELECT name FROM brands WHERE name = ?", (brand,)).fetchone()["name"] \
        if conn.execute("SELECT 1 FROM brands WHERE name = ?", (brand,)).fetchone() else brand
    ensure_brand(conn, brand)
    try:
        cur = conn.execute("INSERT INTO accounts (brand, platform, handle) VALUES (?, ?, ?)",
                           (brand, platform, handle))
    except sqlite3.IntegrityError:
        raise AnalyticsError("Bu hesap zaten ekli", 409)
    conn.commit()
    return cur.lastrowid


def delete_account(conn: sqlite3.Connection, account_id: int) -> bool:
    cur = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    return cur.rowcount > 0


def upsert_post(conn: sqlite3.Connection, account_id: int, *, ext_id: str, url: str, title: str = "",
                posted_at: str = "", duration: int | None = None, views: int | None = None,
                likes: int | None = None, comments: int | None = None, thumb_url: str = "") -> int:
    """Gönderiyi ekler/günceller (boş gelen alan eski değeri ezmez) ve metrik anlık görüntüsü kaydeder."""
    conn.execute(
        "INSERT INTO posts (account_id, ext_id, url, title, posted_at, duration, views, likes, comments, thumb_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(account_id, ext_id) DO UPDATE SET url = excluded.url, "
        "title = COALESCE(NULLIF(excluded.title, ''), title), "
        "posted_at = COALESCE(NULLIF(excluded.posted_at, ''), posted_at), "
        "duration = COALESCE(excluded.duration, duration), views = COALESCE(excluded.views, views), "
        "likes = COALESCE(excluded.likes, likes), comments = COALESCE(excluded.comments, comments), "
        "thumb_url = COALESCE(NULLIF(excluded.thumb_url, ''), thumb_url), fetched_at = datetime('now')",
        (account_id, ext_id, url, title, posted_at, duration, views, likes, comments, thumb_url))
    pid = conn.execute("SELECT id FROM posts WHERE account_id = ? AND ext_id = ?",
                       (account_id, ext_id)).fetchone()["id"]
    row = conn.execute("SELECT views, likes, comments FROM posts WHERE id = ?", (pid,)).fetchone()
    conn.execute("INSERT INTO snapshots (post_id, views, likes, comments) VALUES (?, ?, ?, ?)",
                 (pid, row["views"], row["likes"], row["comments"]))
    conn.commit()
    return pid


def outlier_scores(views: list[int | None]) -> list[float | None]:
    """Her gönderinin izlenmesi / hesabın medyanı. 1.0 = hesabın tipik videosu, 3.0 = 3 kat."""
    known = [v for v in views if v]
    if not known:
        return [None] * len(views)
    med = statistics.median(known)
    return [round(v / med, 2) if v is not None and med else None for v in views]


def engagement_rate(views: int | None, likes: int | None, comments: int | None) -> float | None:
    if not views:
        return None
    return round(((likes or 0) + (comments or 0)) / views * 100, 2)


def overview(conn: sqlite3.Connection) -> dict:
    """Arayüzün tek çağrıda ihtiyaç duyduğu özet: markalar > hesaplar > en iyi/son gönderiler."""
    accounts = [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY brand COLLATE NOCASE, platform")]
    posts_by_acc: dict[int, list[dict]] = {}
    for r in conn.execute("SELECT * FROM posts ORDER BY posted_at DESC, id DESC"):
        posts_by_acc.setdefault(r["account_id"], []).append(dict(r))
    snaps_by_post: dict[int, list[dict]] = {}
    for r in conn.execute("SELECT post_id, taken_at, views FROM snapshots WHERE taken_at >= datetime('now', '-30 days') ORDER BY taken_at"):
        snaps_by_post.setdefault(r["post_id"], []).append(dict(r))
    brands: dict[str, dict] = {}
    for b0 in conn.execute("SELECT id, name FROM brands ORDER BY position, id"):
        brands[b0["name"].lower()] = {"id": b0["id"], "brand": b0["name"], "accounts": [], "total_views": 0, "post_count": 0}
    for a in accounts:
        posts = posts_by_acc.get(a["id"], [])
        # güç skoru: aynı hesap + aynı biçim, olgun videolar; z, VSR, şüpheli trafik, hız (bkz. insights.py)
        insights.enrich_posts(posts, platform=a["platform"], followers=a["followers"])
        for p in posts:
            p.update(insights.velocity(snaps_by_post.get(p["id"], [])))
        a["insights"] = insights.account_insights(posts)
        a["recs"] = recommend.recommendations(posts, a["insights"])
        a["highlights"] = recommend.top_and_weak(posts)
        engs = [p["engagement"] for p in posts if p.get("engagement") is not None]
        a["median_engagement"] = round(statistics.median(engs), 2) if engs else None
        views = [p["views"] for p in posts if p["views"] is not None]
        known = [v for v in views if v]  # güç skorunun paydasıyla aynı medyan
        a["post_count"] = len(posts)
        a["median_views"] = int(statistics.median(known)) if known else None
        a["total_views"] = sum(views) if views else 0
        a["best"] = max(posts, key=lambda p: p["views"] or 0) if posts else None
        a["posts"] = posts
        b = brands.setdefault(a["brand"].lower(), {"id": None, "brand": a["brand"], "accounts": [], "total_views": 0, "post_count": 0})
        b["accounts"].append(a)
        b["total_views"] += a["total_views"]
        b["post_count"] += a["post_count"]
    # içerik planı: iş panosundaki işler marka adıyla eşleşir (büyük/küçük harf farkı yok sayılır)
    tasks_by: dict[str, list[dict]] = {}
    for t in conn.execute("SELECT * FROM tasks ORDER BY id"):
        tasks_by.setdefault((t["brand"] or "").strip().lower(), []).append(dict(t))
    for key, b in brands.items():
        b["plan"] = planning.summarize(tasks_by.pop(key, []))
    loose = [t for ts in tasks_by.values() for t in ts]  # hiçbir markayla eşleşmeyen işler
    return {"brands": list(brands.values()), "platforms": list(PLATFORMS),
            "plan_unassigned": planning.summarize(loose) if loose else None}


# ---------------- yt-dlp ile veri çekme ----------------

Extractor = Callable[[str, int], dict]


def ytdlp_extract(url: str, limit: int, cookies_file: str | None = None, flat: bool = False) -> dict:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20,
            "extract_flat": "in_playlist" if flat else False, "playlistend": limit}
    if cookies_file:
        opts["cookiefile"] = cookies_file
    with yt_dlp.YoutubeDL(opts) as y:
        return y.extract_info(url, download=False) or {}


def _date(info: dict) -> str:
    ts = info.get("timestamp")
    if ts:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    d = info.get("upload_date")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]} 00:00:00" if d and len(d) == 8 else ""


def save_info(conn: sqlite3.Connection, account_id: int, info: dict) -> int:
    if info.get("_type") == "playlist" or info.get("entries") is not None:
        raise AnalyticsError("Bu bir liste/kanal linki; tek bir videonun linkini yapıştır")
    ext_id = str(info.get("id") or "")
    if not ext_id:
        raise AnalyticsError("Videonun kimliği okunamadı")
    return upsert_post(
        conn, account_id, ext_id=ext_id,
        url=info.get("webpage_url") or info.get("url") or "",
        title=(info.get("title") or info.get("description") or "")[:300],
        posted_at=_date(info),
        duration=int(info["duration"]) if info.get("duration") else None,
        views=info.get("view_count"), likes=info.get("like_count"), comments=info.get("comment_count"),
        thumb_url=info.get("thumbnail") or "")


def sync_youtube(conn: sqlite3.Connection, account_id: int, handle: str, limit: int = 15,
                 extract: Extractor | None = None) -> int:
    """Kanalın son Shorts ve uzun videolarını çeker. Dönen: kaydedilen gönderi sayısı."""
    extract = extract or ytdlp_extract
    ids: list[str] = []
    followers = None
    errors: list[str] = []
    for tab in ("shorts", "videos"):  # kanalda sekmelerden biri olmayabilir
        try:
            info = extract(f"https://www.youtube.com/@{handle}/{tab}", limit)
        except Exception as e:
            errors.append(str(e))
            continue
        followers = followers or info.get("channel_follower_count")
        ids += [e["id"] for e in (info.get("entries") or []) if e and e.get("id")]
    saved = 0
    for vid in dict.fromkeys(ids):  # premiere/üyelere özel/yaş kısıtlı tek video tümünü durdurmasın
        try:
            save_info(conn, account_id, extract(f"https://www.youtube.com/watch?v={vid}", 1))
            saved += 1
        except Exception as e:
            errors.append(str(e))
    if saved == 0 and errors:
        raise AnalyticsError(errors[0][:250])
    if followers is not None:
        conn.execute("UPDATE accounts SET followers = ? WHERE id = ?", (followers, account_id))
        conn.commit()
    return saved


def reset_stale_syncs(conn: sqlite3.Connection) -> int:
    """Uygulama eşitleme sürerken kapandıysa 'calisiyor'da takılı kalan hesapları serbest bırak."""
    cur = conn.execute("UPDATE accounts SET sync_status = 'hata', sync_error = 'Yarıda kesildi, tekrar çek' "
                       "WHERE sync_status = 'calisiyor'")
    conn.commit()
    return cur.rowcount


class Syncer:
    """Hesap eşitlemelerini arka planda çalıştırır. Durum accounts.sync_status'ta durur."""

    def __init__(self, db_path, connect, cookies_file: str | None = None, extract: Extractor | None = None):
        self.db_path, self.connect, self.cookies_file = db_path, connect, cookies_file
        self.extract = extract
        self._lock = threading.Lock()
        self._busy: set[int] = set()
        try:
            c = connect(db_path)
            try:
                reset_stale_syncs(c)
            finally:
                c.close()
        except Exception:
            pass

    def _finish(self, account_id: int, status: str, err: str) -> None:
        try:
            c = self.connect(self.db_path)
            try:
                c.execute("UPDATE accounts SET sync_status = ?, sync_error = ?, synced_at = datetime('now') "
                          "WHERE id = ?", (status, err, account_id))
                c.commit()
            finally:
                c.close()
        finally:
            with self._lock:
                self._busy.discard(account_id)

    def start(self, account_id: int) -> bool:
        with self._lock:
            if account_id in self._busy:
                return False
            self._busy.add(account_id)
        try:
            c = self.connect(self.db_path)
            try:
                cur = c.execute("UPDATE accounts SET sync_status = 'calisiyor', sync_error = '' WHERE id = ?",
                                (account_id,))
                c.commit()
                found = cur.rowcount > 0
            finally:
                c.close()
            if not found:
                with self._lock:
                    self._busy.discard(account_id)
                return False
            threading.Thread(target=self._run, args=(account_id,), daemon=True).start()
            return True
        except Exception:
            with self._lock:
                self._busy.discard(account_id)
            raise

    def _run(self, account_id: int) -> None:
        status, err = "hata", "Beklenmeyen hata"
        try:
            c = self.connect(self.db_path)
            try:
                a = c.execute("SELECT platform, handle FROM accounts WHERE id = ?", (account_id,)).fetchone()
                if a is None:
                    return
                if a["platform"] != "youtube":
                    raise AnalyticsError("Bu platform için otomatik çekme henüz yok: videoların linkini elle ekle "
                                         "(TikTok/Instagram profil listesi yt-dlp ile alınamıyor)")
                n = sync_youtube(c, account_id, a["handle"], extract=self.extract or (
                    lambda u, lim: ytdlp_extract(u, lim, self.cookies_file, flat="/watch?" not in u)))
                status, err = ("tamam", "") if n else ("hata", "Hiç video bulunamadı (kullanıcı adı doğru mu?)")
            finally:
                c.close()
        except Exception as e:  # kullanıcıya okunur hata; her yolda son durum yazılır
            status, err = "hata", str(e)[:300]
        finally:
            try:
                self._finish(account_id, status, err)
            except Exception:
                with self._lock:
                    self._busy.discard(account_id)
