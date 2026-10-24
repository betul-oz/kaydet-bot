import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import analytics, db
from app.config import Config, parse_categories
from app.web import create_app

CATS = parse_categories({"categories": [{"name": "diy", "subcategories": ["hook"]}]})


def fake_extract(url, limit):
    if url.endswith("/shorts"):
        return {"channel_follower_count": 1500, "entries": [{"id": "a1"}, {"id": "a2"}]}
    if url.endswith("/videos"):
        return {"entries": [{"id": "a3"}]}
    vid = url.rsplit("=", 1)[-1]
    data = {"a1": (1000, 50, 5, 30), "a2": (9000, 700, 90, 25), "a3": (2000, 100, 10, 600)}
    if vid in data:
        v, l, c, d = data[vid]
        return {"id": vid, "title": f"Video {vid}", "webpage_url": f"https://www.youtube.com/watch?v={vid}",
                "view_count": v, "like_count": l, "comment_count": c, "duration": d,
                "timestamp": 1760000000, "thumbnail": "https://img/x.jpg"}
    return {"id": "tt9", "title": "Tik", "webpage_url": url, "view_count": 500, "like_count": 5,
            "comment_count": 1, "duration": 20, "upload_date": "20251001"}


@pytest.fixture
def conn(tmp_path):
    with closing(db.connect(tmp_path / "a.db")) as c:
        yield c


def test_handle_temizleme():
    assert analytics.clean_handle("youtube", "@marka") == "marka"
    assert analytics.clean_handle("tiktok", "https://www.tiktok.com/@marka.x/") == "marka.x"
    assert analytics.clean_handle("instagram", "https://instagram.com/marka_1?hl=tr") == "marka_1"
    with pytest.raises(analytics.AnalyticsError):
        analytics.clean_handle("youtube", "bad handle!")


def test_hesap_ekle_tekrar_ve_sil(conn):
    aid = analytics.add_account(conn, "  Marka   A ", "youtube", "@abc")
    assert conn.execute("SELECT brand FROM accounts WHERE id=?", (aid,)).fetchone()[0] == "Marka A"
    with pytest.raises(analytics.AnalyticsError) as e:
        analytics.add_account(conn, "Marka A", "youtube", "abc")
    assert e.value.status == 409
    with pytest.raises(analytics.AnalyticsError):
        analytics.add_account(conn, "M", "facebook", "abc")
    assert analytics.delete_account(conn, aid) and not analytics.delete_account(conn, aid)


def test_guc_skoru_medyana_gore():
    assert analytics.outlier_scores([1000, 9000, 2000]) == [0.5, 4.5, 1.0]
    assert analytics.outlier_scores([None, None]) == [None, None]
    assert analytics.engagement_rate(1000, 50, 5) == 5.5
    assert analytics.engagement_rate(0, 1, 1) is None


def test_upsert_bos_alan_eskiyi_ezmez_ve_anlik_goruntu(conn):
    aid = analytics.add_account(conn, "M", "youtube", "abc")
    analytics.upsert_post(conn, aid, ext_id="x", url="u", title="Baslik", views=10)
    analytics.upsert_post(conn, aid, ext_id="x", url="u", title="", views=25)
    row = conn.execute("SELECT title, views FROM posts").fetchone()
    assert (row["title"], row["views"]) == ("Baslik", 25)
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 2


def test_youtube_esitleme(conn):
    aid = analytics.add_account(conn, "M", "youtube", "abc")
    assert analytics.sync_youtube(conn, aid, "abc", extract=fake_extract) == 3
    o = analytics.overview(conn)
    acc = o["brands"][0]["accounts"][0]
    assert acc["followers"] == 1500 and acc["post_count"] == 3 and acc["median_views"] == 2000
    assert acc["best"]["ext_id"] == "a2"
    top = max(acc["posts"], key=lambda p: p["outlier"])
    assert top["outlier"] == 4.5 and top["is_short"] is True
    assert [p["is_short"] for p in acc["posts"] if p["ext_id"] == "a3"] == [False]


@pytest.fixture
def client(tmp_path):
    cfg = Config(db_path=str(tmp_path / "w.db"), allowed_hosts=["testserver"])
    db.connect(cfg.db_path).close()
    syncer = analytics.Syncer(cfg.db_path, db.connect, extract=fake_extract)
    return TestClient(create_app(cfg, CATS, None, None, syncer))


def test_api_hesap_esitleme_ve_link_ekleme(client):
    r = client.post("/api/analytics/accounts", json={"brand": "Marka A", "platform": "youtube", "handle": "@abc"})
    assert r.status_code == 201
    yt = r.json()["brands"][0]["accounts"][0]["id"]
    assert client.post("/api/analytics/accounts", json={"brand": "x", "platform": "youtube", "handle": "abc"}).status_code == 409
    assert client.post(f"/api/analytics/accounts/{yt}/sync").status_code == 200
    for _ in range(50):
        acc = client.get("/api/analytics").json()["brands"][0]["accounts"][0]
        if acc["sync_status"] != "calisiyor":
            break
        time.sleep(0.1)
    assert acc["sync_status"] == "tamam" and acc["post_count"] == 3

    tt = client.post("/api/analytics/accounts", json={"brand": "Marka A", "platform": "tiktok", "handle": "abc"}).json()
    tt_id = [a["id"] for a in tt["brands"][0]["accounts"] if a["platform"] == "tiktok"][0]
    assert client.post(f"/api/analytics/accounts/{tt_id}/sync").status_code == 200
    for _ in range(50):
        tacc = [a for a in client.get("/api/analytics").json()["brands"][0]["accounts"] if a["id"] == tt_id][0]
        if tacc["sync_status"] != "calisiyor":
            break
        time.sleep(0.1)
    assert tacc["sync_status"] == "hata" and "elle ekle" in tacc["sync_error"]

    r = client.post(f"/api/analytics/accounts/{tt_id}/posts", json={"url": "https://www.tiktok.com/@abc/video/1"})
    assert r.status_code == 201
    tacc = [a for a in r.json()["brands"][0]["accounts"] if a["id"] == tt_id][0]
    assert tacc["post_count"] == 1 and tacc["posts"][0]["posted_at"].startswith("2025-10-01")
    assert client.post(f"/api/analytics/accounts/{tt_id}/posts", json={"url": "javascript:alert(1)"}).status_code == 400
    assert client.post("/api/analytics/accounts/999/posts", json={"url": "https://x.com/v"}).status_code == 404
    assert client.delete(f"/api/analytics/accounts/{tt_id}").status_code == 200
    assert client.delete(f"/api/analytics/accounts/{tt_id}").status_code == 404


def test_handle_yanlis_linkler_reddedilir_ve_kucuk_harf():
    for bad in ("https://youtube.com/channel/UCabc", "https://instagram.com/reel/XYZ/", "https://youtube.com/watch?v=1"):
        with pytest.raises(analytics.AnalyticsError):
            analytics.clean_handle("youtube", bad)
    assert analytics.clean_handle("tiktok", "@Marka") == "marka"


def test_harf_farkli_ayni_hesap_iki_kez_eklenmez(conn):
    analytics.add_account(conn, "M", "tiktok", "@Marka")
    with pytest.raises(analytics.AnalyticsError) as e:
        analytics.add_account(conn, "M", "tiktok", "marka")
    assert e.value.status == 409


def test_sekme_veya_video_hatasi_tumunu_durdurmaz(conn):
    aid = analytics.add_account(conn, "M", "youtube", "abc")

    def flaky(url, limit):
        if url.endswith("/shorts"):
            raise RuntimeError("This channel does not have a shorts tab")
        if url.endswith("/videos"):
            return {"channel_follower_count": 7, "entries": [{"id": "a1"}, {"id": "bad"}]}
        if url.endswith("=bad"):
            raise RuntimeError("Private video")
        return fake_extract(url, limit)

    assert analytics.sync_youtube(conn, aid, "abc", extract=flaky) == 1
    assert conn.execute("SELECT followers FROM accounts").fetchone()[0] == 7

    def all_bad(url, limit):
        raise RuntimeError("kanal yok")

    with pytest.raises(analytics.AnalyticsError):
        analytics.sync_youtube(conn, aid, "abc", extract=all_bad)


def test_medyan_ekranla_guc_skoru_ayni(conn):
    aid = analytics.add_account(conn, "M", "tiktok", "abc")
    for i, v in enumerate([0, 0, 0, 100, 200]):
        analytics.upsert_post(conn, aid, ext_id=str(i), url="u", views=v)
    acc = analytics.overview(conn)["brands"][0]["accounts"][0]
    assert acc["median_views"] == 150
    assert [p["outlier"] for p in acc["posts"] if p["views"] == 200] == [1.33]


def test_acilista_takili_calisiyor_serbest_birakilir(tmp_path):
    with closing(db.connect(tmp_path / "s.db")) as c:
        aid = analytics.add_account(c, "M", "youtube", "abc")
        c.execute("UPDATE accounts SET sync_status='calisiyor' WHERE id=?", (aid,))
        c.commit()
    analytics.Syncer(str(tmp_path / "s.db"), db.connect)
    with closing(db.connect(tmp_path / "s.db")) as c:
        assert c.execute("SELECT sync_status FROM accounts").fetchone()[0] == "hata"


def test_link_ekleme_platform_ve_liste_kontrolu(client):
    tt = client.post("/api/analytics/accounts", json={"brand": "M", "platform": "tiktok", "handle": "abc"}).json()
    aid = tt["brands"][0]["accounts"][0]["id"]
    for bad in ("http://127.0.0.1:9/x", "https://www.youtube.com/watch?v=1", "https://evil.com/tiktok.com/v",
                "https://tiktok.com@evil.com/v"):
        assert client.post(f"/api/analytics/accounts/{aid}/posts", json={"url": bad}).status_code == 400
    assert client.post(f"/api/analytics/accounts/{aid}/posts",
                       json={"url": "  https://vm.tiktok.com/abc/ "}).status_code == 201
    assert analytics.url_matches_platform("https://m.youtube.com/watch?v=1", "youtube")


def test_hesap_silinince_gonderiler_de_silinir(conn):
    aid = analytics.add_account(conn, "M", "youtube", "abc")
    analytics.upsert_post(conn, aid, ext_id="x", url="u", views=1)
    analytics.delete_account(conn, aid)
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
