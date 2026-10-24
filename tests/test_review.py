from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import board, db, review
from app.config import Config, parse_categories
from app.web import create_app

CATS = parse_categories({"categories": [{"name": "diy", "subcategories": ["hook"]}]})


@pytest.fixture
def conn(tmp_path):
    with closing(db.connect(tmp_path / "r.db")) as c:
        yield c


@pytest.fixture
def vids(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    a.write_bytes(b"0" * 2048)
    b.write_bytes(b"1" * 2048)
    return a, b


def test_ayni_dosya_iki_kez_eklenmez_ve_gecersiz_dosya_reddedilir(conn, vids, tmp_path):
    vid, new = review.add_video(conn, str(vids[0]), "Kısa 1", kind="short")
    assert new and review.add_video(conn, str(vids[0]), "Kısa 1") == (vid, False)
    with pytest.raises(review.ReviewError):
        review.add_video(conn, str(tmp_path / "yok.mp4"), "x")
    (tmp_path / "gizli.txt").write_text("sir")
    with pytest.raises(review.ReviewError):
        review.add_video(conn, str(tmp_path / "gizli.txt"), "x")


def test_not_zaman_damgasi_ve_revizyon_dongusu(conn, vids):
    vid, _ = review.add_video(conn, str(vids[0]), "Video", brand="BA")
    v1 = review.get_video(conn, vid)["versions"][0]["id"]
    with pytest.raises(review.ReviewError):
        review.request_revision(conn, vid)  # notsuz revizyon olmaz
    review.add_note(conn, v1, 12.34, "Burada altyazı kayıyor")
    review.add_note(conn, v1, 3.0, "Müzik çok yüksek")
    notes = review.get_video(conn, vid)["versions"][0]["notes"]
    assert [n["t"] for n in notes] == [3.0, 12.34]  # zamana göre sıralı
    prompt = review.request_revision(conn, vid)
    assert "[0:03.0] Müzik çok yüksek" in prompt and "[0:12.3] Burada altyazı kayıyor" in prompt
    assert review.get_video(conn, vid)["status"] == "revizyon"
    with pytest.raises(review.ReviewError):
        review.request_revision(conn, vid)  # çift tıklama
    assert len(review.pending_prompts(conn)) == 1
    task = conn.execute("SELECT * FROM tasks").fetchone()
    assert task["status"] == "uretimde"

    v2 = review.add_version(conn, vid, str(vids[1]))
    got = review.get_video(conn, vid)
    assert got["status"] == "inceleme" and [x["n"] for x in got["versions"]] == [1, 2]
    assert conn.execute("SELECT status FROM tasks").fetchone()["status"] == "hazir"
    assert review.pending_prompts(conn) == []
    with pytest.raises(review.ReviewError):
        review.add_note(conn, v1, 1.0, "eski sürüme not")  # eski sürüm kilitli
    review.add_note(conn, v2, 1.0, "yeni sürüm notu")
    assert len(got["versions"][0]["notes"]) == 2  # eski notlar geçmişte kalır


def test_not_dogrulama_duzenleme_silme(conn, vids):
    vid, _ = review.add_video(conn, str(vids[0]), "V")
    v1 = review.get_video(conn, vid)["versions"][0]["id"]
    for bad in ("", "   "):
        with pytest.raises(review.ReviewError):
            review.add_note(conn, v1, 1, bad)
    with pytest.raises(review.ReviewError):
        review.add_note(conn, v1, -1, "x")
    nid = review.add_note(conn, v1, 2, "a")
    review.edit_note(conn, nid, "b")
    assert review.get_video(conn, vid)["versions"][0]["notes"][0]["text"] == "b"
    review.delete_note(conn, nid)
    assert review.get_video(conn, vid)["versions"][0]["notes"] == []


def test_web_api_ve_video_aktarimi_range(tmp_path, vids):
    cfg = Config(db_path=str(tmp_path / "w.db"), allowed_hosts=["testserver"])
    with closing(db.connect(cfg.db_path)) as c:
        vid, _ = review.add_video(c, str(vids[0]), "Web", kind="short")
    cl = TestClient(create_app(cfg, CATS))
    v = cl.get(f"/api/review/videos/{vid}").json()
    ver = v["versions"][0]["id"]
    assert cl.get(f"/api/review/media/{ver}").content == b"0" * 2048
    r = cl.get(f"/api/review/media/{ver}", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10
    assert cl.get("/api/review/media/999").status_code == 404
    res = cl.post("/api/review/notes", json={"version_id": ver, "t": 5.5, "text": "kes"})
    assert res.status_code == 201 and res.json()["versions"][0]["notes"][0]["t"] == 5.5
    assert cl.post("/api/review/notes", json={"version_id": ver, "t": 5, "text": " "}).status_code == 400
    assert cl.post("/api/review/notes", json={"version_id": ver, "t": -1, "text": "x"}).status_code == 422
    rv = cl.post(f"/api/review/videos/{vid}/revise")
    assert rv.status_code == 200 and "kes" in rv.json()["prompt"]
    assert cl.post(f"/api/review/videos/{vid}/revise").status_code == 409
    assert cl.get("/api/board").json()["tasks"][0]["status"] == "uretimde"
    assert cl.delete(f"/api/review/videos/{vid}").status_code == 200
    assert vids[0].exists()  # kayıt silinir, dosya kalır


def test_dosya_silindiyse_medya_404(tmp_path, vids):
    cfg = Config(db_path=str(tmp_path / "w.db"), allowed_hosts=["testserver"])
    with closing(db.connect(cfg.db_path)) as c:
        vid, _ = review.add_video(c, str(vids[0]), "Web")
        ver = review.get_video(c, vid)["versions"][0]["id"]
    vids[0].unlink()
    cl = TestClient(create_app(cfg, CATS))
    assert cl.get(f"/api/review/media/{ver}").status_code == 404
    assert cl.get(f"/api/review/videos/{vid}").json()["versions"][0]["exists"] is False


def test_revizyon_sirasinda_notlar_donar_ve_onay_engellenir(conn, vids):
    vid, _ = review.add_video(conn, str(vids[0]), "V")
    v1 = review.get_video(conn, vid)["versions"][0]["id"]
    nid = review.add_note(conn, v1, 2, "a")
    with pytest.raises(review.ReviewError):
        review.approve(conn, vid)  # notlu video onaylanmaz
    review.request_revision(conn, vid)
    for fn in (lambda: review.add_note(conn, v1, 3, "b"), lambda: review.edit_note(conn, nid, "c"),
               lambda: review.delete_note(conn, nid), lambda: review.approve(conn, vid)):
        with pytest.raises(review.ReviewError) as e:
            fn()
        assert e.value.status == 409
    assert len(review.pending_prompts(conn)) == 1  # Claude'un işi kaybolmadı


def test_onay_yuklendi_isini_geriye_dusurmez_ve_silme_acik_isi_kaldirir(conn, vids):
    vid, _ = review.add_video(conn, str(vids[0]), "V")
    v1 = review.get_video(conn, vid)["versions"][0]["id"]
    review.add_note(conn, v1, 1, "x")
    review.request_revision(conn, vid)
    tid = review.get_video(conn, vid)["task_id"]
    board.update_task(conn, tid, status="yuklendi")
    review.add_version(conn, vid, str(vids[1]))
    assert conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()["status"] == "yuklendi"
    review.approve(conn, vid)
    assert review.get_video(conn, vid)["status"] == "onaylandi"


def test_zaman_bicimi_60_sn_tasmaz():
    assert review.fmt_time(59.96) == "1:00.0" and review.fmt_time(119.97) == "2:00.0" and review.fmt_time(7.3) == "0:07.3"


def test_izle_py_goreli_yol_baska_klasorden(tmp_path, vids, monkeypatch):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"db_path: {(tmp_path / 'i.db').as_posix()}\n", encoding="utf-8")
    monkeypatch.setenv("KAYDET_CONFIG", str(cfg))
    monkeypatch.setenv("IZLE_CWD", str(vids[0].parent))
    assert review.main(["ekle", "a.mp4", "--baslik", "Göreli", "--proje", "."]) == 0
    with closing(db.connect(tmp_path / "i.db")) as c:
        v = review.get_video(c, 1)
        assert v["project_dir"] == str(vids[0].parent.resolve())
    monkeypatch.setenv("IZLE_CWD", str(tmp_path))
    assert review.main(["bekleyen"]) == 0


def test_medya_baska_siteden_gomulemez(tmp_path, vids):
    cfg = Config(db_path=str(tmp_path / "w.db"), allowed_hosts=["testserver"])
    with closing(db.connect(cfg.db_path)) as c:
        vid, _ = review.add_video(c, str(vids[0]), "V")
        ver = review.get_video(c, vid)["versions"][0]["id"]
    cl = TestClient(create_app(cfg, CATS))
    assert cl.get(f"/api/review/media/{ver}", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert cl.get(f"/api/review/media/{ver}", headers={"sec-fetch-site": "same-origin"}).status_code == 200
    assert cl.post("/api/review/notes", json={"version_id": ver, "t": 1, "text": "x"},
                   headers={"origin": "http://evil.example"}).status_code == 403
