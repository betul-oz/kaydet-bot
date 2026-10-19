"""Video indirme: tek işçi iş parçacığı, kuyruk, durum DB'de (yt-dlp)."""
from __future__ import annotations

import logging
import queue
import re
import shutil
import threading
from contextlib import closing
from pathlib import Path
from typing import Callable

from . import db

log = logging.getLogger(__name__)
_BAD = re.compile(r"[^\w \-]", re.UNICODE)


def safe_dir(base: str | Path, category: str, subcategory: str) -> Path:
    """downloads/<kategori>/<alt-baslik>; yol çıkışına (../) izin vermez."""
    base_p = Path(base).resolve()
    parts = [(_BAD.sub("_", p).strip(" ._") or "diger") for p in (category, subcategory)]
    target = base_p.joinpath(*parts).resolve()
    if base_p != target and base_p not in target.parents:
        raise ValueError("Geçersiz indirme klasörü")
    return target


def ytdlp_download(url: str, target_dir: Path, cookies_file: str = "") -> str:
    import yt_dlp
    target_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "retries": 3,
        "socket_timeout": 30, "windowsfilenames": True,
        "outtmpl": str(target_dir / "%(title).60B-%(id)s.%(ext)s"),
    }
    if shutil.which("ffmpeg"):
        # YouTube görüntü ve sesi ayrı verir; ffmpeg ile birleştirilir (en fazla 1080p)
        opts["format"] = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b"
        opts["merge_output_format"] = "mp4"
    else:
        opts["format"] = "b[ext=mp4]/b"  # tek dosyalı (Instagram/TikTok genelde böyle)
    if cookies_file:
        opts["cookiefile"] = cookies_file
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        req = (info.get("requested_downloads") or [{}])[0]
        path = req.get("filepath") or ydl.prepare_filename(info)
    if not path or not Path(path).exists():
        raise RuntimeError("İndirme bitti ama dosya bulunamadı")
    return str(Path(path).resolve())


class Downloader:
    def __init__(self, db_path: str, downloads_dir: str, cookies_file: str = "",
                 run: Callable[[str, Path], str] | None = None):
        self.db_path = db_path
        self.downloads_dir = downloads_dir
        self._run = run or (lambda url, d: ytdlp_download(url, d, cookies_file))
        self._queue: queue.Queue[int] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Yarıda kalan işleri kuyruğa alır ve işçiyi başlatır."""
        with closing(db.connect(self.db_path)) as conn:
            for row in conn.execute("SELECT id FROM items WHERE status IN ('bekliyor', 'iniyor')"):
                self._queue.put(row["id"])
        self._thread = threading.Thread(target=self._loop, name="indirici", daemon=True)
        self._thread.start()

    def enqueue(self, item_id: int) -> bool:
        with closing(db.connect(self.db_path)) as conn:
            if not db.claim_for_download(conn, item_id):
                return False
        self._queue.put(item_id)
        return True

    def _loop(self) -> None:
        while True:
            self.process(self._queue.get())

    def process(self, item_id: int) -> None:
        with closing(db.connect(self.db_path)) as conn:
            row = db.get_item(conn, item_id)
            if row is None:
                return
            db.set_status(conn, item_id, "iniyor")
            try:
                target = safe_dir(self.downloads_dir, row["category"], row["subcategory"])
                path = self._run(row["url"], target)
                db.set_status(conn, item_id, "indirildi", file_path=path)
            except Exception as e:  # tek video hatası kuyruğu durdurmasın
                log.warning("İndirme hatası #%s: %s", item_id, e)
                db.set_status(conn, item_id, "hata", error=str(e)[:500])
