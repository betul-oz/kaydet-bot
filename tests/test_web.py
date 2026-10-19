from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import Config, parse_categories
from app.web import create_app

CATS = parse_categories({"categories": [
    {"name": "diy", "aliases": ["d"], "subcategories": ["hook", "metin"]},
    {"name": "yemek", "subcategories": ["tarif"]},
]})


class FakeDownloader:
    def __init__(self):
        self.queued = []

    def enqueue(self, item_id):
        if item_id in self.queued:
            return False
        self.queued.append(item_id)
        return True


@pytest.fixture
def env(tmp_path):
    cfg = Config(db_path=str(tmp_path / "t.db"), allowed_hosts=["testserver"])
    dl = FakeDownloader()
    with closing(db.connect(cfg.db_path)) as c:
        ids = [db.add_item(c, url=f"https://youtube.com/watch?v=v{n}", platform="youtube",
                           category="diy", subcategory="hook", title=f"V{n}")[0] for n in range(3)]
    client = TestClient(create_app(cfg, CATS, dl))
    client._db_path = cfg.db_path
    return client, dl, ids


def test_ana_sayfa_ve_durum(env):
    client, _, ids = env
    r = client.get("/")
    assert r.status_code == 200 and "Kaydet" in r.text
    st = client.get("/api/state").json()
    assert [c["name"] for c in st["categories"]] == ["diy", "yemek"]
    assert len(st["items"]) == 3 and st["downloads_enabled"] is True


def test_tasima_kalicidir_ve_dogrulanir(env):
    client, _, ids = env
    r = client.patch(f"/api/items/{ids[0]}", json={"category": "yemek", "subcategory": "tarif"})
    assert r.status_code == 200
    items = {i["id"]: i for i in client.get("/api/state").json()["items"]}  # "sayfa yenileme"
    assert (items[ids[0]]["category"], items[ids[0]]["subcategory"]) == ("yemek", "tarif")
    bad = client.patch(f"/api/items/{ids[0]}", json={"category": "yok", "subcategory": "x"})
    assert bad.status_code == 400
    assert client.patch("/api/items/999", json={"note": "a"}).status_code == 404


def test_not_ve_silme(env):
    client, _, ids = env
    assert client.patch(f"/api/items/{ids[0]}", json={"note": "güzel"}).json()["note"] == "güzel"
    assert client.delete(f"/api/items/{ids[0]}").status_code == 200
    assert client.delete(f"/api/items/{ids[0]}").status_code == 404
    assert client.patch(f"/api/items/{ids[1]}", json={"note": "x" * 6000}).status_code == 422


def test_indirme_endpointleri(env):
    client, dl, ids = env
    assert client.post(f"/api/items/{ids[0]}/download").status_code == 200
    assert client.post(f"/api/items/{ids[0]}/download").status_code == 409
    r = client.post("/api/download-sub", json={"category": "diy", "subcategory": "hook"}).json()
    assert r["queued"] == 2 and set(dl.queued) == set(ids)  # ids[0] zaten sıradaydı; diğer ikisi eklendi


def test_indirme_kapaliysa_503(tmp_path):
    cfg = Config(db_path=str(tmp_path / "t.db"), allowed_hosts=["testserver"])
    client = TestClient(create_app(cfg, CATS, None))
    assert client.post("/api/items/1/download").status_code == 503


def test_plan_karti_ve_kopyala(env):
    client, _, ids = env
    card = client.post("/api/cards", json={"title": "Cuma", "note": "benim metnim"}).json()
    cid = card["id"]
    for i in ids[:2]:
        client.post(f"/api/cards/{cid}/items", json={"item_id": i})
    client.post(f"/api/cards/{cid}/items", json={"item_id": ids[0]})  # çift: sessiz
    r = client.patch(f"/api/cards/{cid}/items/{ids[1]}", json={"note": "geçiş için", "move": -1}).json()
    assert [v["id"] for v in r["items"]] == [ids[1], ids[0]]
    text = client.get(f"/api/cards/{cid}/copy").text
    assert "# Cuma" in text and "benim metnim" in text and "geçiş için" in text
    assert "https://youtube.com/watch?v=v0" in text and "https://youtube.com/watch?v=v1" in text
    assert client.get("/api/cards/999/copy").status_code == 404
    assert client.post("/api/cards", json={"title": ""}).status_code == 422
    assert client.delete(f"/api/cards/{cid}").status_code == 200
    assert client.get("/api/cards").json() == []


def test_yabanci_host_basligi_reddedilir(env):
    client, _, _ = env
    assert client.get("/api/state", headers={"Host": "evil.example"}).status_code == 400


def test_download_sub_sadece_kayitli_ve_hata_olanlari_alir(env):
    client, dl, ids = env
    with closing(db.connect(client._db_path)) as c:
        db.set_status(c, ids[0], "indirildi", file_path="x.mp4")
        db.set_status(c, ids[1], "hata", error="boom")
        db.set_status(c, ids[2], "iniyor")
    r = client.post("/api/download-sub", json={"category": "diy", "subcategory": "hook"}).json()
    assert r["queued"] == 1 and dl.queued == [ids[1]]


def test_capraz_site_yazma_istegi_reddedilir(env):
    client, dl, ids = env
    r = client.post(f"/api/items/{ids[0]}/download", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and dl.queued == []
    r = client.post(f"/api/items/{ids[0]}/download", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    ok = client.post(f"/api/items/{ids[0]}/download", headers={"Origin": "http://127.0.0.1:8000"})
    assert ok.status_code == 200 and dl.queued == [ids[0]]
    assert client.get("/api/state", headers={"Origin": "https://evil.example"}).status_code == 200  # okuma serbest


def test_bos_baslik_ve_kismi_guncelleme(env):
    client, _, ids = env
    cid = client.post("/api/cards", json={"title": "  Plan  "}).json()
    assert cid["title"] == "Plan"
    assert client.patch(f"/api/cards/{cid['id']}", json={"title": "   "}).status_code == 422
    r = client.patch(f"/api/items/{ids[0]}", json={"note": "yeni", "category": "yok", "subcategory": "x"})
    assert r.status_code == 400
    items = {i["id"]: i for i in client.get("/api/state").json()["items"]}
    assert items[ids[0]]["note"] == ""  # not da yazılmadı


def test_card_item_asagi_tasima(env):
    client, _, ids = env
    cid = client.post("/api/cards", json={"title": "P"}).json()["id"]
    for i in ids:
        client.post(f"/api/cards/{cid}/items", json={"item_id": i})
    r = client.patch(f"/api/cards/{cid}/items/{ids[0]}", json={"move": 1}).json()
    assert [v["id"] for v in r["items"]] == [ids[1], ids[0], ids[2]]
    r = client.patch(f"/api/cards/{cid}/items/{ids[2]}", json={"move": 1}).json()  # en altta: değişmez
    assert [v["id"] for v in r["items"]] == [ids[1], ids[0], ids[2]]


def test_0000_host_basligi_reddedilir(tmp_path):
    cfg = Config(db_path=str(tmp_path / "t.db"), web_host="0.0.0.0", allowed_hosts=["192.168.1.20"])
    client = TestClient(create_app(cfg, CATS, None))
    assert client.get("/api/state", headers={"Host": "0.0.0.0"}).status_code == 400
    assert client.get("/api/state", headers={"Host": "192.168.1.20:8000"}).status_code == 200
