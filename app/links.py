"""Link tanıma, normalleştirme ve 'link diy/hook' kısa yolu ayrıştırma."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from .config import Categories

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
SHORTCUT_RE = re.compile(r"([^\s/]+)\s*/\s*([^\s/]+)")
EDGE_PUNCT = ".,;:!?()[]{}\"'"

PLATFORMS = {
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
}

YT_ID = r"[\w-]{6,}"
IG_RE = re.compile(r"^/(?:[^/]+/)?(?:p|reel|reels|tv)/([\w-]+)")
TT_VIDEO_RE = re.compile(r"^/(@[^/]+)/video/(\d+)")
YT_PATH_RE = re.compile(rf"^/(?:shorts|embed|live|v)/({YT_ID})")


def extract_urls(text: str) -> list[str]:
    return [u.rstrip(".,;:!?)") for u in URL_RE.findall(text)]


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    parts = host.split(".")
    # www., m., vm. gibi alt alan adlarını at: m.youtube.com -> youtube.com
    return ".".join(parts[-2:]) if len(parts) > 2 else host


def detect_platform(url: str) -> str | None:
    # 'tiktok.com@127.0.0.1' gibi kullanıcıbilgisi içeren adresler gerçekte başka sunucuya gider
    if "@" in urlparse(url).netloc:
        return None
    return PLATFORMS.get(_host(url))


def normalize_url(url: str) -> str:
    """Aynı videonun farklı link biçimlerini tek adrese indirger (çift kaydı önler)."""
    p = urlparse(url)
    host = _host(url)
    platform = PLATFORMS.get(host)
    path = p.path.rstrip("/") or "/"

    if platform == "youtube":
        vid = None
        if host == "youtu.be":
            vid = path.lstrip("/").split("/")[0] or None
        elif path == "/watch":
            vid = (parse_qs(p.query).get("v") or [None])[0]
        else:
            m = YT_PATH_RE.match(path)
            vid = m.group(1) if m else None
        if vid:
            return f"https://youtube.com/watch?v={vid}"
    elif platform == "instagram":
        m = IG_RE.match(path)
        if m:
            return f"https://instagram.com/reel/{m.group(1)}"
    elif platform == "tiktok":
        m = TT_VIDEO_RE.match(path)
        if m:
            return f"https://tiktok.com/{m.group(1)}/video/{m.group(2)}"

    # Tanınmayan biçim (kısa link, kanal vb.): Instagram/TikTok'ta sorgu hiçbir şeyi belirlemez.
    # Kısa linklerde (vm.tiktok.com) alt alan adı yönlendirme için gerekli, o yüzden korunur.
    if platform in ("instagram", "tiktok"):
        full = (p.hostname or "").removeprefix("www.")
        return f"https://{full}{path}"
    query = f"?{p.query}" if p.query else ""
    return f"https://{host}{path}{query}"


@dataclass
class Parsed:
    url: str
    platform: str
    category: str | None = None
    subcategory: str | None = None


def parse_message(text: str, categories: Categories | None = None) -> Parsed | None:
    """Mesajdan ilk desteklenen linki çıkarır; 'diy/hook' kısa yolu varsa çözer."""
    for raw in extract_urls(text):
        platform = detect_platform(raw)
        if platform is None:
            continue
        parsed = Parsed(url=normalize_url(raw), platform=platform)
        if categories is not None:
            rest = text.replace(raw, " ")
            for m in SHORTCUT_RE.finditer(rest):
                resolved = categories.resolve(m.group(1).strip(EDGE_PUNCT),
                                              m.group(2).strip(EDGE_PUNCT))
                if resolved:
                    parsed.category, parsed.subcategory = resolved
                    break
        return parsed
    return None
