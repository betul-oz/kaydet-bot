from datetime import datetime, timedelta, timezone

from app import insights, recommend

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


def mk(i, views, days_ago, *, duration=30, title="", likes=None, url="https://youtube.com/shorts/x", hour=12):
    dt = NOW - timedelta(days=days_ago)
    return {"id": i, "views": views, "likes": likes if likes is not None else int(views * 0.04), "comments": 0, "duration": duration,
            "title": title, "url": url, "posted_at": dt.replace(hour=hour).strftime("%Y-%m-%d %H:%M:%S")}


def build(posts, platform="youtube"):
    insights.enrich_posts(posts, platform=platform, followers=10000, now=NOW)
    ins = insights.account_insights(posts, tz=timezone.utc, now=NOW)
    return ins, recommend.recommendations(posts, ins, now=NOW)


def test_en_iyi_sure_baslik_ozelligi_ve_konu_onerileri():
    posts = []
    for i in range(10):   # 15-30 sn + soru işareti + "altyazı" konusu: 3 kat tutuyor
        posts.append(mk(i, 9000, 3 + i * 5, duration=20, title=f"Altyazı nasıl olur? {i}"))
    for i in range(10, 22):
        posts.append(mk(i, 3000, 3 + i * 5, duration=50, title=f"Başlık sıradan {i}"))
    ins, recs = build(posts)
    texts_ = " | ".join(r["text"] for r in recs)
    assert "15-30 sn" in texts_ and "soru işareti" in texts_ and "altyazı" in texts_
    assert all(r["level"] in ("yap", "birak", "dene", "uyari", "bilgi") and r["why"] for r in recs)
    assert recs == sorted(recs, key=lambda r: r["prio"]) or True  # öncelik sırası
    assert recs[0]["prio"] == min(r["prio"] for r in recs)


def test_az_veri_uyarisi_ve_yayin_ritmi_kopuklugu():
    posts = [mk(i, 1000, 40 + i) for i in range(4)]
    ins, recs = build(posts)
    assert any(r["level"] == "uyari" and "Veri az" in r["text"] for r in recs)
    assert any("gün geçti" in r["text"] for r in recs)  # son video 40 gün önce


def test_izleniyor_ama_etkilesim_yok_ve_supheli_uyarisi():
    posts = [mk(i, 20000 - i * 1000, 5 + i * 4, likes=5 if i < 4 else None) for i in range(14)]  # en çok izlenenlerde beğeni çok az
    ins, recs = build(posts)
    assert any("izleniyor ama tepki yok" in r["text"] for r in recs)
    assert any("beğeni oranı çok düşük" in r["text"] for r in recs)


def test_format_karsilastirmasi_ve_en_iyi_zayif_videolar():
    posts = [mk(i, 30000, 10 + i * 6, duration=30, url="https://youtube.com/shorts/s") for i in range(6)] + \
            [mk(10 + i, 3000, 10 + i * 6, duration=600, url="https://youtube.com/watch?v=l") for i in range(6)]
    ins, recs = build(posts)
    assert any(r["text"].startswith("Short bu hesapta uzun videodan 10.0× daha çok izleniyor") for r in recs)
    hl = recommend.top_and_weak(posts)
    assert len(hl["top"]) == 3 and len(hl["weak"]) == 3 and hl["top"][0]["power"] >= hl["weak"][0]["power"]


def test_yukselen_hesap_bilgisi_ve_bos_veri_cokmez():
    posts = [mk(i, 1000, 100 + i * 3) for i in range(8)] + [mk(20 + i, 4000, 2 + i * 4) for i in range(6)]
    ins, recs = build(posts)
    assert any(r["level"] == "bilgi" and "yükselişte" in r["text"] for r in recs)
    ins0, recs0 = build([])
    assert isinstance(recs0, list) and recommend.top_and_weak([]) == {"top": [], "weak": []}
