"""Link için başlık/thumbnail çekme (yt-dlp, en iyi çaba: hata olursa boş döner)."""
from __future__ import annotations

import asyncio


def fetch_metadata(url: str, timeout: int = 20) -> dict:
    try:
        import yt_dlp
    except ImportError:
        return {}
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "socket_timeout": timeout, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:  # giriş isteyen/silinmiş/ağ hatası: kayıt yine yapılır
        return {}
    if not isinstance(info, dict):
        return {}
    return {
        "title": str(info.get("title") or "")[:300],
        "thumb_url": str(info.get("thumbnail") or ""),
        "webpage_url": str(info.get("webpage_url") or ""),
    }


async def fetch_metadata_async(url: str, timeout: int = 30) -> dict:
    try:
        return await asyncio.wait_for(asyncio.to_thread(fetch_metadata, url), timeout)
    except Exception:
        return {}
