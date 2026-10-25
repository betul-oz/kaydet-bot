import socket
import threading
import time
from contextlib import closing

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app import auth, db, izle_cli
from app.config import Config, apply_env, parse_categories
from app.web import create_app

CATS = parse_categories({"categories": [{"name": "diy", "subcategories": ["hook"]}]})


def cfg_for(tmp_path, **kw):
    return Config(db_path=str(tmp_path / "d.db"), media_dir=str(tmp_path / "media"), allowed_hosts=["testserver"], **kw)


def test_cerez_imza_sure_ve_token():
    c = auth.make_cookie("sifre", now=1000)
    assert auth.cookie_ok("sifre", c, now=1001) and not auth.cookie_ok("baska", c, now=1001)
    assert not auth.cookie_ok("sifre", c, now=1000 + auth.SESSION_DAYS * 86400 + 5)  # süresi doldu
    assert not auth.cookie_ok("sifre", "abc.def") and not auth.cookie_ok("sifre", None) and not auth.cookie_ok("", c)
    assert auth.token_ok("t", "Bearer t") and not auth.token_ok("t", "Bearer x") and not auth.token_ok("", "Bearer ")


def test_ortam_degiskenleri_config_i_ezer():
    cfg = apply_env(Config(), {"PORT": "9100", "KAYDET_HOST": "0.0.0.0", "KAYDET_ALLOWED_HOSTS": "a.com, b.com",
                              "KAYDET_PASSWORD": "p", "KAYDET_TOKEN": "t", "KAYDET_DB": "/data/k.db"})
    assert (cfg.web_port, cfg.web_host, cfg.allowed_hosts, cfg.password, cfg.api_token, cfg.db_path) == \
        (9100, "0.0.0.0", ["a.com", "b.com"], "p", "t", "/data/k.db")


def test_sifre_yokken_acik_sifre_varken_kapali(tmp_path):
    open_cl = TestClient(create_app(cfg_for(tmp_path), CATS))
    assert open_cl.get("/api/review/tree").status_code == 200
    cl = TestClient(create_app(cfg_for(tmp_path, password="gizli", api_token="tok"), CATS), follow_redirects=False)
    assert cl.get("/healthz").text == "ok"
    assert cl.get("/api/review/tree").status_code == 401
    r = cl.get("/")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert cl.get("/api/review/tree", headers={"Authorization": "Bearer tok"}).status_code == 200
    assert cl.get("/api/review/tree", headers={"Authorization": "Bearer yanlis"}).status_code == 401
    bad = cl.post("/login", content="password=yanlis", headers={"content-type": "application/x-www-form-urlencoded"})
    assert bad.status_code == 401 and "Şifre yanlış" in bad.text
    ok = cl.post("/login", content="password=gizli", headers={"content-type": "application/x-www-form-urlencoded"})
    assert ok.status_code == 303 and "httponly" in ok.headers["set-cookie"].lower() and "samesite=lax" in ok.headers["set-cookie"].lower()
    assert cl.get("/api/review/tree").status_code == 200  # çerez oturumu
    assert cl.post("/logout").status_code == 303
    assert cl.get("/api/review/tree").status_code == 401


def test_kilit_ip_basina_ve_gövde_siniri(tmp_path):
    cl = TestClient(create_app(cfg_for(tmp_path, password="gizli"), CATS), follow_redirects=False)
    h = {"content-type": "application/x-www-form-urlencoded", "x-forwarded-for": "6.6.6.6"}
    for _ in range(auth.MAX_FAILS):
        cl.post("/login", content="password=x", headers=h)
    assert cl.post("/login", content="password=x", headers=h).status_code == 429
    ok = cl.post("/login", content="password=gizli", headers={**h, "x-forwarded-for": "1.2.3.4"})
    assert ok.status_code == 303  # saldırganın kilidi gerçek kullanıcıyı etkilemez
    assert cl.post("/login", content="p=" + "a" * 5000, headers={**h, "x-forwarded-for": "9.9.9.9"}).status_code == 413
    assert not auth.token_ok("tok", "Bearer çş") and not auth.cookie_ok("p", "1.çş")  # ASCII dışı: 500 değil, red


def test_giris_kaba_kuvvete_kilitlenir(tmp_path):
    cl = TestClient(create_app(cfg_for(tmp_path, password="gizli"), CATS), follow_redirects=False)
    for _ in range(auth.MAX_FAILS):
        assert cl.post("/login", content="password=x", headers={"content-type": "application/x-www-form-urlencoded"}).status_code == 401
    r = cl.post("/login", content="password=gizli", headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 429  # doğru şifre bile geçici olarak reddedilir


@pytest.fixture
def live(tmp_path):
    cfg = cfg_for(tmp_path, password="gizli", api_token="tok")
    cfg.allowed_hosts = []
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(create_app(cfg, CATS), host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", cfg
    srv.should_exit = True
    th.join(5)


def test_izle_py_uzak_sunucuya_yukler_ve_revizyonu_okur(live, tmp_path, monkeypatch, capsys):
    url, cfg = live
    monkeypatch.setenv("KAYDET_SERVER", url)
    monkeypatch.setenv("KAYDET_TOKEN", "tok")
    monkeypatch.setenv("IZLE_CWD", str(tmp_path))
    mp4 = tmp_path / "v.mp4"
    mp4.write_bytes(b"x" * 5000)
    md = tmp_path / "s.md"
    md.write_text("Merhaba dünya\n", encoding="utf-8")
    assert izle_cli.main(["ekle", "v.mp4", "--baslik", "Uzak video", "--marka", "K", "--kategori", "A/B"]) == 0
    assert izle_cli.main(["metin-ekle", "s.md", "--baslik", "Uzak metin", "--marka", "K"]) == 0
    out = capsys.readouterr().out
    assert "/#/izle/1" in out and "/#/metin/m/1" in out
    with closing(db.connect(cfg.db_path)) as c:
        from app import review, texts
        v = review.get_video(c, 1)
        assert c.execute("SELECT path FROM rv_versions").fetchone()["path"].startswith(str(tmp_path / "media")) and v["cat_id"]
        texts.add_comment(c, 1, "dünya", "büyük harf")
        texts.request_revision(c, 1)
    assert izle_cli.main(["bekleyen"]) == 0
    assert "büyük harf" in capsys.readouterr().out
    md.write_text("Merhaba Dünya\n", encoding="utf-8")
    assert izle_cli.main(["metin-guncelle", "1", "s.md", "--not", "tamam"]) == 0
    assert izle_cli.main(["metin-al", "1"]) == 0
    assert md.read_text(encoding="utf-8") == "Merhaba Dünya\n"
    monkeypatch.setenv("KAYDET_TOKEN", "yanlis")
    assert izle_cli.main(["bekleyen"]) == 1
    assert "401" in capsys.readouterr().out


def test_yukleme_guvenligi(tmp_path):
    cl = TestClient(create_app(cfg_for(tmp_path, password="g", api_token="tok"), CATS))
    h = {"Authorization": "Bearer tok"}
    assert cl.put("/api/hub/upload?filename=x.exe", content=b"a", headers=h).status_code == 400
    assert cl.post("/api/hub/videos", json={"ref": "../../etc/passwd", "title": "x"}, headers=h).status_code == 400
    assert cl.post("/api/hub/videos", json={"ref": "a" * 32 + ".mp4", "title": "x"}, headers=h).status_code == 404
    ref = cl.put("/api/hub/upload?filename=a.MP4", content=b"abc", headers=h).json()["ref"]
    assert ref.endswith(".mp4") and (tmp_path / "media" / ref).read_bytes() == b"abc"
    assert not list((tmp_path / "media").glob("*.part"))
