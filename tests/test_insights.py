from datetime import datetime, timedelta, timezone

import pytest

from app import insights

NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


def mk(i, views, days_ago, *, duration=30, title="", likes=None, url="u", hour=12):
    dt = NOW - timedelta(days=days_ago)
    return {"id": i, "views": views, "likes": likes, "comments": 0, "duration": duration, "title": title, "url": url,
            "posted_at": dt.replace(hour=hour).strftime("%Y-%m-%d %H:%M:%S")}


def test_taban_ayni_bicim_olgun_video_ve_kendisi_haric():
    posts = [mk(i, 1000, 20 + i, duration=20) for i in range(12)]           # short, olgun
    posts.append(mk(100, 50000, 40, duration=900))                            # uzun video: kısa tabanı bozmaz
    posts.append(mk(101, 9000, 1, duration=20))                               # 1 günlük short: tabana girmez ama skoru hesaplanır
    insights.enrich_posts(posts, platform="youtube", followers=10000, now=NOW)
    new = next(p for p in posts if p["id"] == 101)
    assert new["format"] == "short" and new["outlier"] == 9.0 and new["base_n"] == 12 and new["reliable"]
    long_ = next(p for p in posts if p["id"] == 100)
    assert long_["format"] == "uzun" and long_["outlier"] is None or long_["base_scope"] == "hesap"  # aynı biçimde başka video yok
    assert new["vsr"] == 0.9


def test_az_video_guvenilmez_isaretlenir_ve_hesap_medyanina_duser():
    posts = [mk(1, 100, 30), mk(2, 300, 30)]
    insights.enrich_posts(posts, platform="tiktok", followers=None, now=NOW)
    assert not posts[0]["reliable"] and posts[0]["outlier"] == 0.33 and posts[1]["outlier"] == 3.0


def test_sagirlam_z_ve_sicak_etiketi():
    posts = [mk(i, 1000 + (i % 3) * 100, 30 + i) for i in range(12)] + [mk(99, 20000, 10)]
    insights.enrich_posts(posts, platform="youtube", followers=None, now=NOW)
    star = next(p for p in posts if p["id"] == 99)
    assert star["z"] > insights.HOT_Z and star["hot"]
    assert insights.robust_z(5, [1, 2]) is None  # az veri
    assert insights.robust_z(5, [3] * 10) is None  # MAD = 0


def test_supheli_trafik_ve_etkilesim():
    posts = [mk(1, 5000, 30, likes=2), mk(2, 5000, 30, likes=500), mk(3, 500, 30, likes=0)]
    insights.enrich_posts(posts, platform="youtube", followers=None, now=NOW)
    assert posts[0]["suspicious"] and not posts[1]["suspicious"] and not posts[2]["suspicious"]  # 1000 altı izlenmede işaretlenmez
    assert posts[1]["engagement"] == 10.0


def test_izlenme_hizi_ve_ivme():
    t = lambda h: (NOW + timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
    v = insights.velocity([{"taken_at": t(0), "views": 100}, {"taken_at": t(2), "views": 300}, {"taken_at": t(4), "views": 700}])
    assert v == {"vph": 200.0, "accel": 100.0, "snapshots": 3}
    assert insights.velocity([{"taken_at": t(0), "views": 5}])["vph"] is None
    assert insights.velocity([{"taken_at": t(0), "views": 5}, {"taken_at": t(0.1), "views": 9}])["vph"] is None  # çok kısa aralık


def test_gun_saat_sure_ve_lift():
    posts = []
    for i in range(12):  # çarşamba 18:00 hep tutuyor, soru işaretli başlıklar da
        posts.append(mk(i, 3000, 7 * i + 5, duration=20, title=f"Neden? {i}", hour=18))
    for i in range(12, 24):
        posts.append(mk(i, 1000, 7 * i + 6, duration=45, title=f"Başlık {i}", hour=9))
    insights.enrich_posts(posts, platform="youtube", followers=None, now=NOW)
    ins = insights.account_insights(posts, tz=timezone.utc, now=NOW)
    q = next(r for r in ins["features"] if r["feature"] == "soru işareti")
    assert q["n_yes"] == 12 and q["n_no"] == 12 and not q["few"] and q["lift"] > 1.5
    assert {r["bucket"] for r in ins["duration"]} == {"15-30 sn", "30-60 sn"}
    assert [r["slot"] for r in ins["hour"]] == ["00-06", "06-12", "12-18", "18-24"]
    assert next(r for r in ins["hour"] if r["slot"] == "18-24")["median"] > next(r for r in ins["hour"] if r["slot"] == "06-12")["median"]
    assert sum(d["n"] for d in ins["weekday"]) == 24


def test_saatsiz_tarihlerde_saat_analizi_yok_ve_trend():
    posts = [{"id": i, "views": 1000 if i < 6 else 3000, "likes": None, "comments": 0, "duration": 20, "title": "", "url": "u",
              "posted_at": (NOW - timedelta(days=(100 - i * 3) if i < 6 else (i - 5) * 4)).strftime("%Y-%m-%d")} for i in range(12)]
    insights.enrich_posts(posts, platform="tiktok", followers=None, now=NOW)
    ins = insights.account_insights(posts, tz=timezone.utc, now=NOW)
    assert ins["hour"] == []  # yalnız tarih var
    assert ins["trend"] is None or ins["trend"]["label"] in ("büyüyor", "soğuyor", "sabit")


def test_hashtag_tablosu_ve_baslik_ozellikleri():
    posts = [mk(i, 2000, 20 + i, title="Ev #diy #hack") for i in range(4)] + [mk(9, 500, 25, title="Düz")]
    insights.enrich_posts(posts, platform="instagram", followers=None, now=NOW)
    ins = insights.account_insights(posts, tz=timezone.utc, now=NOW)
    assert [h["tag"] for h in ins["hashtags"]] == ["#diy", "#hack"] and ins["hashtags"][0]["n"] == 4
    f = insights.title_features("TEKRAR 5 neden? 🔥 #x")
    assert f["sayı var"] and f["soru işareti"] and f["emoji"] and f["hashtag"] and f["BÜYÜK HARF kelime"] and not f["uzun başlık (60+)"]
