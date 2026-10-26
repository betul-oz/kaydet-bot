from contextlib import closing
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import analytics, board, db, planning
from app.config import Config, parse_categories
from app.web import create_app

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
TODAY = NOW.date()
CATS = parse_categories({"categories": [{"name": "diy", "subcategories": ["hook"]}]})


def t(i, status, due="", days_created=20, days_updated=0, platform="youtube"):
    f = lambda d: (NOW - timedelta(days=d)).strftime("%Y-%m-%d %H:%M:%S")
    return {"id": i, "title": f"İş {i}", "status": status, "due": due, "platform": platform,
            "created_at": f(days_created), "updated_at": f(days_updated)}


def test_tahmini_bitis_hiz_ve_dogru_kararlar():
    # son 20 günde 10 iş yüklendi (haftada 3.5), 7 iş kaldı -> 14 gün
    tasks = [t(i, "yuklendi", days_updated=i) for i in range(10)] + [t(100 + i, "bekliyor", due="2026-11-30") for i in range(7)]
    s = planning.summarize(tasks, TODAY, NOW)
    assert s["total"] == 17 and s["done"] == 10 and s["remaining"] == 7 and s["progress"] == 0.588
    assert s["pace_per_week"] == 3.5 and s["forecast"] == "2026-11-09" and s["verdict"] == "zamaninda"
    # aynı iş yükü ama son tarih yakın: gecikme riski
    tasks2 = [t(i, "yuklendi", days_updated=i) for i in range(10)] + [t(100 + i, "bekliyor", due="2026-11-03") for i in range(7)]
    s2 = planning.summarize(tasks2, TODAY, NOW)
    assert s2["verdict"] == "gecikme" and s2["late_days"] == 6


def test_plan_yok_bitti_hiz_yok_ve_gecikmis():
    assert planning.summarize([], TODAY, NOW)["verdict"] == "plan-yok"
    assert planning.summarize([t(1, "yuklendi")], TODAY, NOW)["verdict"] == "bitti"
    s = planning.summarize([t(1, "bekliyor", due="2026-11-05", days_created=2)], TODAY, NOW)
    assert s["verdict"] == "hiz-yok" and s["forecast"] is None and s["due_next"] == "2026-11-05"
    late = planning.summarize([t(1, "yuklendi", days_updated=1), t(2, "uretimde", due="2026-10-20"), t(3, "bekliyor", due="2027-01-01")], TODAY, NOW)
    assert late["overdue"] == 1 and late["upcoming"][0]["id"] == 2 and late["upcoming"][0]["overdue"]


def test_toplu_plan_satiri_ayrisir():
    items = planning.parse_lines("Video A | 2026-11-03 | tiktok\n\nVideo B\nVideo C | instagram | 2026-12-01\nBozuk | tarih-degil", "youtube")
    assert [(i["title"], i["due"], i["platform"]) for i in items] == [
        ("Video A", "2026-11-03", "tiktok"), ("Video B", "", "youtube"), ("Video C", "2026-12-01", "instagram"), ("Bozuk", "", "youtube")]


@pytest.fixture
def client(tmp_path):
    cfg = Config(db_path=str(tmp_path / "p.db"), allowed_hosts=["testserver"])
    db.connect(cfg.db_path).close()
    return TestClient(create_app(cfg, CATS))


def test_marka_yonetimi_ve_plan_apisi(client):
    r = client.post("/api/analytics/brands", json={"name": "Flag Derby"})
    assert r.status_code == 201 and [b["brand"] for b in r.json()["brands"]] == ["Flag Derby"]
    assert client.post("/api/analytics/brands", json={"name": "flag derby"}).status_code == 409  # harf farkı yok sayılır
    assert client.post("/api/analytics/brands", json={"name": "<b>"}).status_code == 400
    bid = r.json()["brands"][0]["id"]
    # aynı markaya farklı platformlarda çok hesap
    for plat, h in (("youtube", "fd_tr"), ("youtube", "fd_en"), ("tiktok", "fd")):
        assert client.post("/api/analytics/accounts", json={"brand": "Flag Derby", "platform": plat, "handle": h}).status_code == 201
    brands = client.get("/api/analytics").json()["brands"]
    assert len(brands) == 1 and len(brands[0]["accounts"]) == 3
    # toplu plan
    r = client.post(f"/api/analytics/brands/{bid}/plan", json={"text": "Video 1 | 2026-11-03\nVideo 2 | tiktok", "platform": "youtube"})
    assert r.status_code == 201
    plan = r.json()["brands"][0]["plan"]
    assert plan["total"] == 2 and plan["remaining"] == 2 and plan["due_last"] == "2026-11-03"
    assert client.post(f"/api/analytics/brands/{bid}/plan", json={"text": "  \n"}).status_code == 400
    # yeniden adlandırma hesapları ve planı birlikte taşır
    r = client.patch(f"/api/analytics/brands/{bid}", json={"name": "FD Global"})
    b = r.json()["brands"][0]
    assert b["brand"] == "FD Global" and all(a["brand"] == "FD Global" for a in b["accounts"]) and b["plan"]["total"] == 2
    # hesaplı marka silinmez; boş marka silinir; hesap taşınır
    assert client.delete(f"/api/analytics/brands/{bid}").status_code == 409
    other = client.post("/api/analytics/brands", json={"name": "SafeKids"}).json()["brands"][1]["id"]
    acc = client.get("/api/analytics").json()["brands"][0]["accounts"][0]["id"]
    moved = client.patch(f"/api/analytics/accounts/{acc}", json={"brand_id": other}).json()["brands"]
    assert [len(x["accounts"]) for x in moved] == [2, 1]
    assert client.delete(f"/api/analytics/brands/{other}").status_code == 409
    empty = client.post("/api/analytics/brands", json={"name": "Boş"}).json()["brands"][-1]["id"]
    assert client.delete(f"/api/analytics/brands/{empty}").status_code == 200


def test_eski_hesaplar_markaya_tasinir_ve_eslesmeyen_isler_ayri_gorunur(tmp_path):
    path = tmp_path / "m.db"
    with closing(db.connect(path)) as c:
        c.execute("INSERT INTO accounts (brand, platform, handle) VALUES ('Eski Marka', 'youtube', 'abc')")
        board.add_task(c, "Sahipsiz iş", brand="Bilinmeyen")
        c.commit()
    analytics._migrated.clear()
    with closing(db.connect(path)) as c:
        ov = analytics.overview(c)
        assert [b["brand"] for b in ov["brands"]] == ["Eski Marka"] and ov["brands"][0]["id"]
        assert ov["plan_unassigned"]["total"] == 1
