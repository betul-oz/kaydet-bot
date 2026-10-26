"""İçerik planı özeti: planlanan işler (iş panosu) ne zaman biter, tahmini bitiş, gecikme riski.
Saf hesap; veritabanı erişimi analytics.overview ve web katmanında."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

DONE = "yuklendi"
ACTIVE = ("bekliyor", "uretimde", "hazir", "sorun")
PACE_WINDOW = (7, 28)  # hız ölçüm penceresi (gün): ilk işten bu yana geçen süre bu aralığa sıkıştırılır


def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat((s or "").strip()[:10]) if s else None
    except ValueError:
        return None


def _dt(s: str | None) -> datetime | None:
    try:
        return datetime.strptime((s or "")[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def summarize(tasks: list[dict], today: date | None = None, now: datetime | None = None) -> dict:
    """tasks: iş panosu satırları (status, due, created_at, updated_at, platform, title, id)."""
    now = now or datetime.now(timezone.utc)
    today = today or datetime.now().astimezone().date()  # gecikme hesabı yerel (Türkiye) tarihine göre
    done = [t for t in tasks if t["status"] == DONE]
    active = [t for t in tasks if t["status"] in ACTIVE]
    total = len(tasks)
    # hız: son pencerede yüklenen iş / hafta
    created = [d for d in (_dt(t.get("created_at")) for t in tasks) if d]
    window = PACE_WINDOW[0]
    if created:
        window = min(max((now - min(created)).days, PACE_WINDOW[0]), PACE_WINDOW[1])
    recent_done = [t for t in done if (u := _dt(t.get("updated_at"))) and (now - u).days <= window]
    per_week = round(len(recent_done) / window * 7, 2) if recent_done else 0.0
    dues = sorted(d for d in (_d(t.get("due")) for t in active) if d)
    overdue = [t for t in active if (d := _d(t.get("due"))) and d < today]
    remaining = len(active)
    forecast = None
    if remaining == 0 and total:
        forecast = today
    elif per_week > 0:
        forecast = today + timedelta(days=math.ceil(remaining / (per_week / 7)))
    due_last = dues[-1] if dues else None
    if not total:
        verdict = "plan-yok"
    elif remaining == 0:
        verdict = "bitti"
    elif per_week == 0:
        verdict = "hiz-yok"
    elif due_last and forecast and forecast > due_last:
        verdict = "gecikme"
    elif overdue:
        verdict = "gecikmis-var"
    else:
        verdict = "zamaninda"
    late_days = (forecast - due_last).days if verdict == "gecikme" else 0
    by_platform: dict[str, dict] = {}
    for t in tasks:
        p = by_platform.setdefault(t.get("platform") or "", {"total": 0, "done": 0})
        p["total"] += 1
        p["done"] += t["status"] == DONE
    upcoming = sorted(active, key=lambda t: (_d(t.get("due")) or date.max, t["id"]))[:12]
    return {
        "total": total, "done": len(done), "remaining": remaining, "stuck": sum(t["status"] == "sorun" for t in active),
        "progress": round(len(done) / total, 3) if total else None,
        "overdue": len(overdue), "due_next": next((d.isoformat() for d in dues if d >= today), None),
        "due_last": due_last.isoformat() if due_last else None,
        "pace_per_week": per_week, "pace_window_days": window,
        "forecast": forecast.isoformat() if forecast else None, "verdict": verdict, "late_days": late_days,
        "by_platform": by_platform,
        "upcoming": [{"id": t["id"], "title": t["title"], "status": t["status"], "platform": t.get("platform") or "",
                      "due": t.get("due") or "", "overdue": bool(t in overdue)} for t in upcoming],
    }


def parse_lines(text: str, default_platform: str = "") -> list[dict]:
    """Toplu plan girişi: her satır 'Başlık | 2026-11-03 | youtube' (tarih ve platform isteğe bağlı, sırası serbest)."""
    out = []
    for raw in (text or "").splitlines():
        parts = [p.strip() for p in raw.split("|")]
        if not parts or not parts[0]:
            continue
        item = {"title": parts[0], "due": "", "platform": default_platform}
        for p in parts[1:]:
            if _d(p) and len(p) >= 10:
                item["due"] = p[:10]
            elif p.lower() in ("youtube", "tiktok", "instagram"):
                item["platform"] = p.lower()
        out.append(item)
    return out[:200]
