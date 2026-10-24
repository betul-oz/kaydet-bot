from contextlib import closing
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import board, db
from app.config import Config, parse_categories
from app.web import create_app

CATS = parse_categories({"categories": [{"name": "diy", "subcategories": ["hook"]}]})


@pytest.fixture
def conn(tmp_path):
    with closing(db.connect(tmp_path / "b.db")) as c:
        yield c


def test_donem_14_gun_ve_5_gun_kala_hatirlatma(conn):
    bid = board.add_batch(conn, "Kasım 1", "2026-11-01")
    b = conn.execute("SELECT * FROM batches WHERE id=?", (bid,)).fetchone()
    assert b["end_date"] == "2026-11-14"
    assert board.due_reminders(conn, date(2026, 11, 8)) == []      # 6 gün kala: henüz değil
    assert len(board.due_reminders(conn, date(2026, 11, 9))) == 1  # tam 5 gün kala
    assert board.due_reminders(conn, date(2026, 11, 15)) == []     # bitmiş dönem hatırlatılmaz


def test_hatirlatma_yalniz_basarili_gonderimde_isaretlenir(conn):
    board.add_batch(conn, "K", "2026-11-01")
    today = date(2026, 11, 10)
    assert board.run_reminders(conn, lambda t: False, today) == 0
    assert board.run_reminders(conn, lambda t: (_ for _ in ()).throw(RuntimeError("ağ yok")), today) == 0
    sent = []
    assert board.run_reminders(conn, lambda t: sent.append(t) or True, today) == 1
    assert "4 gün kaldı" in sent[0]
    assert board.run_reminders(conn, lambda t: sent.append(t) or True, today) == 0  # tekrar atmaz
    assert len(sent) == 1


def test_is_durum_degisimi_mesaj_birakir(conn):
    tid = board.add_task(conn, "3 reels yükle", brand="A", platform="tiktok", actor="claude")
    assert board.update_task(conn, tid, status="uretimde", actor="claude")
    msgs = [m["text"] for m in board.overview(conn)["messages"]]
    assert any("bekliyor → uretimde" in m for m in msgs)
    with pytest.raises(board.BoardError):
        board.update_task(conn, tid, status="uçtu")
    with pytest.raises(board.BoardError):
        board.add_task(conn, "x", due="03.11.2026")
    assert board.delete_task(conn, tid) and not board.delete_task(conn, tid)


def test_tarih_gecersiz(conn):
    with pytest.raises(board.BoardError):
        board.add_batch(conn, "x", "yarın")


@pytest.fixture
def client(tmp_path):
    cfg = Config(db_path=str(tmp_path / "w.db"), allowed_hosts=["testserver"])
    db.connect(cfg.db_path).close()
    return TestClient(create_app(cfg, CATS))


def test_api_pano_akisi(client):
    r = client.post("/api/board/tasks", json={"title": "Reels yükle", "platform": "youtube"})
    assert r.status_code == 201
    tid = r.json()["tasks"][0]["id"]
    r = client.patch(f"/api/board/tasks/{tid}", json={"status": "yuklendi", "note": "tamam"})
    assert r.json()["tasks"][0]["status"] == "yuklendi"
    assert client.patch(f"/api/board/tasks/{tid}", json={"status": "olmaz"}).status_code == 400
    assert client.patch("/api/board/tasks/999", json={"note": "x"}).status_code == 404
    assert client.post("/api/board/messages", json={"text": "selam", "author": "sistem"}).status_code == 400
    assert client.post("/api/board/messages", json={"text": "  "}).status_code == 400
    assert client.post("/api/board/messages", json={"text": "selam", "author": "claude"}).status_code == 201
    r = client.post("/api/board/batches", json={"title": "", "start": "2026-11-01"})
    assert r.json()["batches"][0]["end_date"] == "2026-11-14"
    assert client.post("/api/board/batches", json={"start": "bozuk"}).status_code == 400
    bid = r.json()["batches"][0]["id"]
    assert client.delete(f"/api/board/batches/{bid}").status_code == 200
    assert client.delete(f"/api/board/tasks/{tid}").status_code == 200


def test_kismi_gonderimde_en_az_biri_giderse_isaretlenir(conn):
    from app import reminders
    board.add_batch(conn, "K", "2026-11-01")
    calls = []

    class R:
        def __init__(self, code): self.status_code = code

    def fake_post(url, json, timeout):
        calls.append(json["chat_id"])
        return R(200 if json["chat_id"] == 1 else 403)

    orig = reminders.httpx.post
    reminders.httpx.post = fake_post
    try:
        send = reminders.telegram_sender("TOKEN", [1, 2])
        assert board.run_reminders(conn, send, date(2026, 11, 10)) == 1
        assert board.run_reminders(conn, send, date(2026, 11, 10)) == 0
    finally:
        reminders.httpx.post = orig
    assert calls == [1, 2]


def test_son_tarih_bicimi_duzeltilir(conn):
    tid = board.add_task(conn, "x", due="20261103")
    assert conn.execute("SELECT due FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "2026-11-03"
    board.update_task(conn, tid, due=" 2026-11-05 ")
    assert conn.execute("SELECT due FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "2026-11-05"
    board.update_task(conn, tid, due="")
    assert conn.execute("SELECT due FROM tasks WHERE id=?", (tid,)).fetchone()[0] == ""
