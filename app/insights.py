"""Analiz içgörüleri: biçime ve yaşa göre düzeltilmiş güç skoru, sağlam z-skoru, izlenme hızı, en iyi gün/saat,
süre kırılımı, başlık özelliği 'lift' tablosu, trend. Saf hesap: veritabanı ve ağ yok, kolayca test edilir.

Dayanak (açık kaynak araştırması, 2026-10-25): bangermap-mcp (aynı biçimin son 30 yüklemesi, >=7 gün yaşlı, kendisi hariç),
youtube-niche-finder (snapshot'tan saatlik izlenme ve ivme, çok pencereli outlier), yuben-app (VSR = izlenme/abone,
beğeni/1000 izlenme ile şüpheli trafik), Trend-Lens (z-skoru). Eşikler öneridir, kanıtlanmış sabit değil.
"""
from __future__ import annotations

import math
import re
import statistics
from datetime import datetime, timedelta, timezone, tzinfo

SHORT_MAX_SECONDS = 180
BASE_LAST_N = 30         # taban: aynı hesap + aynı biçimin son N videosu
BASE_MIN_AGE_DAYS = 7    # taban yalnızca en az bu kadar yaşlı videolardan (yeni video henüz olgunlaşmadı)
RELIABLE_MIN = 10        # taban en az bu kadar videoyla güvenilir sayılır
HOT_SCORE, HOT_Z = 3.0, 2.5
SUSPICIOUS_LIKES_PER_1000 = 1.5
MIN_GROUP = 5            # lift/gün/süre kırılımı: gruplarda en az bu kadar video yoksa 'az veri'

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆]")
_NUM = re.compile(r"\d")
_HASH = re.compile(r"#\w+", re.UNICODE)


def parse_dt(s: str | None) -> datetime | None:
    """'YYYY-MM-DD HH:MM:SS' (UTC) ya da 'YYYY-MM-DD'; çözülemezse None."""
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if " " in s else s[:10], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def post_format(platform: str, duration: int | None, url: str = "") -> str:
    """'short' ya da 'uzun': Shorts ile uzun video ayrı tabanla kıyaslanır."""
    if "/shorts/" in url or platform in ("tiktok", "instagram"):
        return "short"
    return "short" if duration is not None and duration <= SHORT_MAX_SECONDS else "uzun"


def _med(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def robust_z(value: float, population: list[float]) -> float | None:
    """ln ölçeğinde (value - medyan) / (1.4826 * MAD). Tek viral video ölçüyü bozmasın diye ortalama/std kullanılmaz."""
    if value <= 0 or len(population) < 8:
        return None
    logs = [math.log(v) for v in population if v > 0]
    if len(logs) < 8:
        return None
    med = statistics.median(logs)
    mad = statistics.median(abs(x - med) for x in logs)
    if mad == 0:
        return None
    return round((math.log(value) - med) / (1.4826 * mad), 2)


def enrich_posts(posts: list[dict], *, platform: str, followers: int | None, now: datetime | None = None) -> None:
    """Gönderilere yerinde alan ekler: format, age_days, outlier (güç), base_n, reliable, z, hot, vsr, suspicious, engagement."""
    now = now or datetime.now(timezone.utc)
    for p in posts:
        dt = parse_dt(p.get("posted_at"))
        p["_dt"] = dt
        p["age_days"] = round((now - dt).total_seconds() / 86400, 1) if dt else None
        p["format"] = post_format(platform, p.get("duration"), p.get("url", ""))
        p["is_short"] = p["format"] == "short"
    by_fmt: dict[str, list[dict]] = {}
    for p in posts:
        by_fmt.setdefault(p["format"], []).append(p)
    account_med = _med([p["views"] for p in posts if p.get("views")])
    for p in posts:
        v = p.get("views")
        same = [q for q in by_fmt[p["format"]] if q is not p and q.get("views")]
        ripe = sorted((q for q in same if q["_dt"] is None or q["age_days"] is None or q["age_days"] >= BASE_MIN_AGE_DAYS),
                      key=lambda q: q["_dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:BASE_LAST_N]
        base_pool = ripe if len(ripe) >= 3 else same  # olgun video azsa aynı biçimdekilerin hepsi
        base = _med([q["views"] for q in base_pool])
        scope = "biçim"
        if base is None:  # aynı biçimde yeterli video yok: hesabın genel medyanı (eski davranış)
            base, scope = account_med, "hesap"
        p["base_n"] = len(base_pool) if scope == "biçim" else len([1 for q in posts if q.get("views")])
        p["base_scope"] = scope
        p["reliable"] = p["base_n"] >= RELIABLE_MIN
        p["outlier"] = round(v / base, 2) if v is not None and base else None
        pop = [q["views"] for q in by_fmt[p["format"]] if q.get("views")]
        p["z"] = robust_z(v, pop) if v else None
        p["hot"] = bool(p["outlier"] is not None and p["outlier"] >= HOT_SCORE and (p["z"] is None or p["z"] >= HOT_Z))
        p["vsr"] = round(v / followers, 3) if v is not None and followers else None
        likes = p.get("likes")
        p["suspicious"] = bool(v and v >= 1000 and likes is not None and likes / v * 1000 < SUSPICIOUS_LIKES_PER_1000)
        p["engagement"] = round(((likes or 0) + (p.get("comments") or 0)) / v * 100, 2) if v else None
    for p in posts:
        p.pop("_dt", None)


def velocity(snaps: list[dict], min_hours: float = 0.5) -> dict:
    """snaps: [{taken_at, views}] eski->yeni. vph = son iki ölçüm arası saatlik izlenme; accel = bir önceki aralığa göre değişim."""
    pts = []
    for s in snaps:
        dt, v = parse_dt(s.get("taken_at")), s.get("views")
        if dt is not None and v is not None and (not pts or dt > pts[-1][0]):
            pts.append((dt, v))
    rates = []
    for (t1, v1), (t2, v2) in zip(pts, pts[1:]):
        h = (t2 - t1).total_seconds() / 3600
        if h >= min_hours:
            rates.append(round(max(v2 - v1, 0) / h, 1))
    return {"vph": rates[-1] if rates else None, "accel": round(rates[-1] - rates[-2], 1) if len(rates) >= 2 else None,
            "snapshots": len(pts)}


DAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
DUR_BUCKETS = [(0, 15, "0-15 sn"), (15, 30, "15-30 sn"), (30, 60, "30-60 sn"), (60, 180, "1-3 dk"), (180, 10 ** 9, "3 dk+")]
HOUR_BUCKETS = [(0, 6, "00-06"), (6, 12, "06-12"), (12, 18, "12-18"), (18, 24, "18-24")]


def _group_stats(items: list[tuple]) -> dict:
    """items: [(güç, etkileşim %)]. median = medyan güç, eng = medyan etkileşim oranı (%)."""
    pw = [x[0] for x in items]
    en = [x[1] for x in items if x[1] is not None]
    return {"n": len(pw), "median": round(_med(pw), 2) if pw else None, "eng": round(_med(en), 2) if en else None,
            "few": len(pw) < MIN_GROUP}


def _pe(p: dict) -> tuple:
    return (p["outlier"], p.get("engagement"))


def title_features(title: str) -> dict[str, bool]:
    t = title or ""
    return {"sayı var": bool(_NUM.search(t)), "soru işareti": "?" in t, "emoji": bool(_EMOJI.search(t)),
            "hashtag": bool(_HASH.search(t)), "uzun başlık (60+)": len(t) >= 60,
            "BÜYÜK HARF kelime": any(len(w) >= 4 and w.isupper() for w in re.findall(r"\w+", t))}


def lift_table(posts: list[dict], boot: int = 200) -> list[dict]:
    """Özellik başına: var/yok medyan güç skoru, lift ve (varsa) yaklaşık güven. Her iki grupta en az MIN_GROUP video yoksa 'az veri'."""
    scored = [p for p in posts if p.get("outlier") is not None]
    rows = []
    for name in title_features("").keys():
        yes = [p for p in scored if title_features(p.get("title", ""))[name]]
        no = [p for p in scored if not title_features(p.get("title", ""))[name]]
        row = {"feature": name, "n_yes": len(yes), "n_no": len(no), "med_yes": None, "med_no": None, "lift": None,
               "eng_yes": None, "eng_no": None, "eng_lift": None, "few": True}
        if yes and no:
            my, mn = _med([p["outlier"] for p in yes]), _med([p["outlier"] for p in no])
            ey = _med([p["engagement"] for p in yes if p.get("engagement") is not None])
            en = _med([p["engagement"] for p in no if p.get("engagement") is not None])
            row.update(med_yes=round(my, 2), med_no=round(mn, 2), lift=round(my / mn, 2) if mn else None,
                       eng_yes=round(ey, 2) if ey is not None else None, eng_no=round(en, 2) if en is not None else None,
                       eng_lift=round(ey / en, 2) if ey is not None and en else None,
                       few=len(yes) < MIN_GROUP or len(no) < MIN_GROUP)
        rows.append(row)
    return rows


def hashtag_table(posts: list[dict], min_n: int = 3) -> list[dict]:
    agg: dict[str, list[tuple]] = {}
    for p in posts:
        if p.get("outlier") is None:
            continue
        for tag in {m.lower() for m in _HASH.findall(p.get("title", ""))}:
            agg.setdefault(tag, []).append(_pe(p))
    out = [{"tag": t, "n": len(v), **{k: x for k, x in _group_stats(v).items() if k in ("median", "eng")}} for t, v in agg.items() if len(v) >= min_n]
    return sorted(out, key=lambda r: (-r["median"], r["tag"]))[:12]


_STOP = set("ve ile bir bu şu için gibi daha çok en de da mi mı mu mü ne ama ya veya the and for with that this you your from are was how what why".split())
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)


def keyword_table(posts: list[dict], min_n: int = 3, limit: int = 12) -> list[dict]:
    """Başlıktaki anahtar kelimelere (konu vekili) göre güç ve etkileşim: hangi konu tutuyor?"""
    agg: dict[str, list[tuple]] = {}
    for p in posts:
        if p.get("outlier") is None:
            continue
        words = {w.lower() for w in _WORD.findall(_HASH.sub(" ", p.get("title", "")))} - _STOP
        for w in words:
            agg.setdefault(w, []).append(_pe(p))
    rows = [{"word": w, "n": len(v), **{k: x for k, x in _group_stats(v).items() if k in ("median", "eng")}} for w, v in agg.items() if len(v) >= min_n]
    return sorted(rows, key=lambda r: (-r["median"], r["word"]))[:limit]


def account_insights(posts: list[dict], tz: tzinfo | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    scored = [p for p in posts if p.get("outlier") is not None]
    # --- gün / saat ---
    rawdt = [(p, parse_dt(p.get("posted_at"))) for p in scored]
    has_time = [(p, d) for p, d in rawdt if d is not None and (p.get("posted_at") or "").strip()[11:16] not in ("", "00:00")]
    local = lambda d: d.astimezone(tz) if tz else d.astimezone()
    timed = {id(p) for p, _ in has_time}
    days = [[] for _ in range(7)]
    for p, d in rawdt:
        if d is not None:
            days[(local(d) if id(p) in timed else d).weekday()].append(_pe(p))
    hours = {lab: [] for _, _, lab in HOUR_BUCKETS}
    for p, d in has_time:
        h = local(d).hour
        for lo, hi, lab in HOUR_BUCKETS:
            if lo <= h < hi:
                hours[lab].append(_pe(p))
    durs = {lab: [] for _, _, lab in DUR_BUCKETS}
    for p in scored:
        if p.get("duration") is not None:
            for lo, hi, lab in DUR_BUCKETS:
                if lo <= p["duration"] < hi:
                    durs[lab].append(_pe(p))
    fmts = {}
    for f in ("short", "uzun"):
        vs = [p["views"] for p in posts if p.get("format") == f and p.get("views")]
        if vs:
            fmts[f] = {"n": len(vs), "median_views": int(_med(vs))}
    # --- trend: son 30 gün ile önceki 90 günün medyan güç skoru ---
    recent = [p["outlier"] for p in scored if p.get("age_days") is not None and p["age_days"] <= 30]
    before = [p["outlier"] for p in scored if p.get("age_days") is not None and 30 < p["age_days"] <= 120]
    trend = None
    if len(recent) >= 3 and len(before) >= 3:
        r, b = _med(recent), _med(before)
        ratio = round(r / b, 2) if b else None
        trend = {"recent_n": len(recent), "before_n": len(before), "recent": round(r, 2), "before": round(b, 2), "ratio": ratio,
                 "label": "büyüyor" if ratio and ratio >= 1.15 else "soğuyor" if ratio and ratio <= 0.85 else "sabit"}
    return {
        "weekday": [{"day": DAYS[i], **_group_stats(v)} for i, v in enumerate(days)],
        "hour": [{"slot": lab, **_group_stats(v)} for lab, v in hours.items()] if has_time and len(has_time) >= len(rawdt) / 2 else [],
        "duration": [{"bucket": lab, **_group_stats(v)} for lab, v in durs.items() if v],
        "formats": fmts,
        "features": lift_table(scored),
        "hashtags": hashtag_table(scored),
        "keywords": keyword_table(scored),
        "trend": trend,
        "n_scored": len(scored),
    }
