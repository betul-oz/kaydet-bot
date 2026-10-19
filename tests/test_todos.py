from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import Config, load_categories
from app.web import create_app


@pytest.fixture
def client(tmp_path):
    cfg = Config(db_path=str(tmp_path / "t.db"), allowed_hosts=["testserver"])
    return TestClient(create_app(cfg, load_categories("categories.example.yaml"), None))


def test_ekle_listele_tamamla_duzenle_sil(client):
    a = client.post("/api/todos", json={"text": "  Cuma için hook bul  "}).json()
    b = client.post("/api/todos", json={"text": "Müzik seç"}).json()
    assert a["text"] == "Cuma için hook bul" and a["done"] == 0
    r = client.patch(f"/api/todos/{a['id']}", json={"done": True}).json()
    assert r["done"] == 1
    # açık olanlar önce, tamamlananlar sonra
    assert [t["id"] for t in client.get("/api/todos").json()] == [b["id"], a["id"]]
    assert client.patch(f"/api/todos/{b['id']}", json={"text": "Müzik seç (sakin)"}).json()["text"] == "Müzik seç (sakin)"
    assert client.patch(f"/api/todos/{a['id']}", json={"done": False}).json()["done"] == 0
    assert client.delete(f"/api/todos/{a['id']}").status_code == 200
    assert client.delete(f"/api/todos/{a['id']}").status_code == 404
    assert [t["id"] for t in client.get("/api/todos").json()] == [b["id"]]


def test_gecersiz_girisler(client):
    assert client.post("/api/todos", json={"text": "   "}).status_code == 422
    assert client.post("/api/todos", json={"text": "x" * 501}).status_code == 422
    t = client.post("/api/todos", json={"text": "a"}).json()
    assert client.patch(f"/api/todos/{t['id']}", json={"text": "  "}).status_code == 422
    assert client.patch("/api/todos/999", json={"done": True}).status_code == 404


def test_tamamlananlari_temizle(client):
    ids = [client.post("/api/todos", json={"text": f"n{i}"}).json()["id"] for i in range(3)]
    client.patch(f"/api/todos/{ids[0]}", json={"done": True})
    client.patch(f"/api/todos/{ids[2]}", json={"done": True})
    assert client.post("/api/todos/clear-done").json() == {"removed": 2}
    assert [t["id"] for t in client.get("/api/todos").json()] == [ids[1]]


def test_capraz_site_not_yazma_reddedilir(client):
    r = client.post("/api/todos", json={"text": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and client.get("/api/todos").json() == []


def test_eski_veritabanina_todos_tablosu_eklenir(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    sqlite3.connect(path).executescript("CREATE TABLE items (id INTEGER PRIMARY KEY, url TEXT UNIQUE, platform TEXT,"
        " title TEXT DEFAULT '', thumb_url TEXT DEFAULT '', category TEXT, subcategory TEXT, note TEXT DEFAULT '',"
        " status TEXT DEFAULT 'kayitli', file_path TEXT DEFAULT '', error TEXT DEFAULT '', created_at TEXT DEFAULT '');")
    with closing(db.connect(path)) as c:
        assert db.list_todos(c) == []


def test_uzunluk_siniri_ve_bos_patch(client):
    assert client.post("/api/todos", json={"text": "x" * 500}).status_code == 201  # sınırda kabul
    t = client.post("/api/todos", json={"text": "a"}).json()
    assert client.patch(f"/api/todos/{t['id']}", json={"text": "y" * 501}).status_code == 422
    r = client.patch(f"/api/todos/{t['id']}", json={})  # değişiklik yok: not aynen döner
    assert r.status_code == 200 and r.json()["text"] == "a"


def test_temizlenecek_yokken_sifir_doner(client):
    client.post("/api/todos", json={"text": "açık not"})
    assert client.post("/api/todos/clear-done").json() == {"removed": 0}
    assert len(client.get("/api/todos").json()) == 1
