"""Hesap için 'ne yapmalıyım' önerileri: kural tabanlı, kanıtlı (örnek sayısı yazılır), Türkçe.
Girdi: insights.enrich_posts + account_insights çıktısı. Eşikler öneridir; az veride 'ipucu' diye işaretlenir."""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

STRONG, WEAK = 1.25, 0.8      # grup medyan gücü / hesap normali: bunun üstü 'iyi', altı 'zayıf'
MIN_N = 5


def _rec(level: str, text: str, why: str, prio: int = 2) -> dict:
    return {"level": level, "text": text, "why": why, "prio": prio}


def _best_worst(groups: list[dict], label_key: str, min_n: int = MIN_N):
    ok = [g for g in groups if g.get("n", 0) >= min_n and g.get("median") is not None]
    if len(ok) < 2:
        return None, None
    return max(ok, key=lambda g: g["median"]), min(ok, key=lambda g: g["median"])


def top_and_weak(posts: list[dict], k: int = 3) -> dict:
    """En çok tutan ve en zayıf kalan videolar (zayıf için yalnızca olgun: >=7 gün)."""
    scored = [p for p in posts if p.get("outlier") is not None]
    ripe = [p for p in scored if p.get("age_days") is None or p["age_days"] >= 7]
    slim = lambda p: {"id": p["id"], "title": p.get("title") or p.get("url"), "url": p.get("url"), "views": p.get("views"),
                      "power": p["outlier"], "engagement": p.get("engagement"), "format": p.get("format")}
    return {"top": [slim(p) for p in sorted(scored, key=lambda p: -p["outlier"])[:k]],
            "weak": [slim(p) for p in sorted(ripe, key=lambda p: p["outlier"])[:k]]}


def recommendations(posts: list[dict], ins: dict, *, now: datetime | None = None, synced: bool = True) -> list[dict]:
    """synced=False (TikTok/Instagram'da videolar elle eklendiyse): yayın sıklığı önerisi çıkarılmaz, çünkü listenin tamamı yoktur."""
    now = now or datetime.now(timezone.utc)
    out: list[dict] = []
    n = ins.get("n_scored", 0)
    if n < 10:
        out.append(_rec("uyari", f"Veri az ({n} video): öneriler henüz ipucu niteliğinde.",
                        "En az 10-15 videoyla güvenilir kalıp çıkar. 'Verileri çek' ile daha fazla video getir.", 1))
    # --- biçim ---
    f = ins.get("formats", {})
    sh = [p for p in posts if p.get("format") == "short" and p.get("outlier") is not None]
    lo = [p for p in posts if p.get("format") == "uzun" and p.get("outlier") is not None]
    if len(sh) >= MIN_N and len(lo) >= MIN_N:
        vs, vl = [p["views"] for p in sh if p.get("views")], [p["views"] for p in lo if p.get("views")]
        ms, ml = (statistics.median(vs) if vs else 0), (statistics.median(vl) if vl else 0)
        if ms and ml and (ms / ml >= 1.5 or ml / ms >= 1.5):
            win, lose, r = ("Short", "uzun videodan", ms / ml) if ms > ml else ("Uzun video", "Short'tan", ml / ms)
            out.append(_rec("yap", f"{win} bu hesapta {lose} {r:.1f}× daha çok izleniyor: ağırlığı artır.",
                            f"Medyan izlenme: Short {int(ms):,}, uzun {int(ml):,} (n={len(sh)}/{len(lo)}).".replace(",", "."), 1))
    # --- süre ---
    best, worst = _best_worst(ins.get("duration", []), "bucket")
    if best and best["median"] >= STRONG:
        out.append(_rec("yap", f"En iyi süre aralığı {best['bucket']}: yeni videoları bu uzunluğa yaklaştır.",
                        f"Medyan güç {best['median']}× (n={best['n']})" + (f", etkileşim %{best['eng']}" if best.get("eng") is not None else ""), 1))
    if worst and worst["median"] <= WEAK and worst is not best:
        out.append(_rec("birak", f"{worst['bucket']} videolar zayıf kalıyor: bu uzunluktan kaçın ya da daha iyi hook'la dene.",
                        f"Medyan güç {worst['median']}× (n={worst['n']})", 2))
    # --- gün / saat ---
    bd, wd = _best_worst(ins.get("weekday", []), "day")
    if bd and bd["median"] >= STRONG:
        out.append(_rec("yap", f"{bd['day']} günü paylaşım daha iyi sonuç veriyor: önemli videoları bu güne planla.",
                        f"Medyan güç {bd['median']}× (n={bd['n']})", 2))
    bh, wh = _best_worst(ins.get("hour", []), "slot")
    if bh and bh["median"] >= STRONG:
        out.append(_rec("yap", f"{bh['slot']} saat diliminde paylaşılanlar daha iyi: yayın saatini buraya çek.",
                        f"Medyan güç {bh['median']}× (n={bh['n']})", 2))
    # --- başlık özellikleri ---
    for r in ins.get("features", []):
        if r.get("few") or r.get("lift") is None:
            continue
        if r["lift"] >= 1.3:
            out.append(_rec("yap", f"Başlıkta “{r['feature']}” olan videolar {r['lift']}× daha güçlü: bunu daha sık kullan.",
                            f"Var: {r['med_yes']}× (n={r['n_yes']}), yok: {r['med_no']}× (n={r['n_no']})", 2))
        elif r["lift"] <= 0.75:
            out.append(_rec("birak", f"Başlıkta “{r['feature']}” kullanmak zayıf sonuç vermiş ({r['lift']}×): azalt.",
                            f"Var: {r['med_yes']}× (n={r['n_yes']}), yok: {r['med_no']}× (n={r['n_no']})", 3))
    # --- konu (anahtar kelime) ---
    kw = [k for k in ins.get("keywords", []) if k["n"] >= 5]
    if kw and kw[0]["median"] >= 1.4:
        k = kw[0]
        out.append(_rec("yap", f"“{k['word']}” konulu videolar en çok tutan grup ({k['median']}×, {k['n']} video): bu konuda seri düşün.",
                        "Başlıktaki anahtar kelimeye göre gruplandı; konu vekilidir, kesin değildir.", 2))
    weak_kw = [k for k in ins.get("keywords", []) if k["n"] >= 3 and k["median"] <= 0.7]
    if weak_kw:
        out.append(_rec("birak", f"“{weak_kw[-1]['word']}” konulu videolar zayıf ({weak_kw[-1]['median']}×): konuyu gözden geçir.", f"{weak_kw[-1]['n']} video", 3))
    # --- etkileşim / izlenme uyumsuzluğu ---
    scored = [p for p in posts if p.get("outlier") is not None and p.get("engagement") is not None]
    if len(scored) >= 10:
        ranked = sorted(scored, key=lambda p: -p["outlier"])
        q = max(2, len(ranked) // 4)
        eng_top = statistics.median(p["engagement"] for p in ranked[:q])
        eng_all = statistics.median(p["engagement"] for p in scored)
        if eng_all and eng_top < eng_all * 0.6:
            out.append(_rec("dene", "En çok izlenen videolarda etkileşim düşük: izleniyor ama tepki yok. Sonuna net bir çağrı (yorum sorusu, kaydet/paylaş) ekle.",
                            f"En çok izlenen {q} videoda medyan etkileşim %{eng_top:.2f}, hesap geneli %{eng_all:.2f}", 2))
    # --- trend ---
    tr = ins.get("trend")
    if tr:
        if tr["label"] == "soğuyor":
            out.append(_rec("uyari", f"Son 30 gün önceki döneme göre zayıf ({tr['recent']}× → önceden {tr['before']}×): son dönemde ne değişti, o dönemin tutan videolarına bak.",
                            f"{tr['recent_n']} yeni, {tr['before_n']} eski video", 1))
        elif tr["label"] == "büyüyor":
            out.append(_rec("bilgi", f"Hesap yükselişte ({tr['before']}× → {tr['recent']}×): son dönemde yaptığını koru, değişiklik yapma.", f"{tr['recent_n']} yeni video", 3))
    # --- yayın sıklığı ---
    dts = []
    for p in posts:
        try:
            dts.append(datetime.strptime((p.get("posted_at") or "")[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    if dts and synced:
        last = max(dts)
        gap = (now - last).days
        per30 = sum((now - d).days <= 30 for d in dts)
        if gap > 14:
            out.append(_rec("uyari", f"Son videodan beri {gap} gün geçti: yayın ritmi kopmuş.", "Düzenli yayın algoritmada ve takipçi alışkanlığında önemli.", 1))
        elif per30 < 4:
            out.append(_rec("dene", f"Son 30 günde yalnızca {per30} video: haftada en az 1-2 video hedefle.", "Düşük sıklık, tutan kalıbı test etmeyi de yavaşlatır.", 2))
    # --- şüpheli trafik ---
    sus = [p for p in posts if p.get("suspicious")]
    if sus:
        out.append(_rec("uyari", f"{len(sus)} videoda beğeni oranı çok düşük (reklam ya da şüpheli trafik olabilir): bu videoları skor değerlendirmesinde ayrı tut.",
                        "Beğeni/1000 izlenme eşiğin altında.", 3))
    if n < 10:  # az veride kesin dil kullanma
        for r in out:
            if r["level"] in ("yap", "birak", "dene"):
                r["text"] = "İpucu: " + r["text"]
                r["why"] += " (örnek az: kesin değil)"
    out.sort(key=lambda r: (r["prio"], {"uyari": 0, "yap": 1, "birak": 2, "dene": 3, "bilgi": 4}[r["level"]]))
    return out[:14]
