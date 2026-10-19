from contextlib import closing
from pathlib import Path

import pytest

from app import db
from app.downloader import Downloader, safe_dir


@pytest.fixture
def setup(tmp_path):
    path = tmp_path / "t.db"
    conn = db.connect(path)
    i, _ = db.add_item(conn, url="https://youtu.be/aaaaaa", platform="youtube",
                       category="diy", subcategory="hook")
    yield SetupObj(path, tmp_path, i)
    conn.close()


class SetupObj:
    def __init__(self, path, tmp, item_id):
        self.path, self.tmp, self.item_id = path, tmp, item_id

    def status(self):
        with closing(db.connect(self.path)) as c:
            return dict(db.get_item(c, self.item_id))


def test_basarili_indirme(setup):
    def fake(url, target: Path):
        target.mkdir(parents=True, exist_ok=True)
        f = target / "v.mp4"
        f.write_bytes(b"x")
        return str(f)
    d = Downloader(str(setup.path), str(setup.tmp / "dl"), run=fake)
    assert d.enqueue(setup.item_id)
    assert setup.status()["status"] == "bekliyor"
    assert not d.enqueue(setup.item_id)  # zaten sırada
    d.process(setup.item_id)
    row = setup.status()
    assert row["status"] == "indirildi" and row["file_path"].endswith("v.mp4")
    assert "diy" in row["file_path"] and "hook" in row["file_path"]


def test_hata_kuyrugu_durdurmaz_ve_mesaj_yazar(setup):
    def boom(url, target):
        raise RuntimeError("giriş gerekli")
    d = Downloader(str(setup.path), str(setup.tmp / "dl"), run=boom)
    d.enqueue(setup.item_id)
    d.process(setup.item_id)
    row = setup.status()
    assert row["status"] == "hata" and "giriş gerekli" in row["error"]
    assert d.enqueue(setup.item_id)  # hatadan sonra tekrar denenebilir


def test_start_yarida_kalani_kuyruga_alir(setup):
    with closing(db.connect(setup.path)) as c:
        db.set_status(c, setup.item_id, "iniyor")
    seen = []
    d = Downloader(str(setup.path), str(setup.tmp / "dl"), run=lambda u, t: seen.append(u) or str(setup.path))
    d.start()
    for _ in range(50):
        if setup.status()["status"] == "indirildi":
            break
        import time; time.sleep(0.05)
    assert seen == ["https://youtu.be/aaaaaa"]
    assert setup.status()["status"] == "indirildi"


def test_safe_dir_yol_cikisini_engeller(tmp_path):
    base = tmp_path / "dl"
    d = safe_dir(base, "../../etc", "..\\x/y")
    assert base.resolve() in d.parents
    assert safe_dir(base, "diy", "hook").name == "hook"
    assert safe_dir(base, "", "...").name == "diger"


def test_enqueue_atomik_ve_hata_sonrasi_yeniden(setup):
    d = Downloader(str(setup.path), str(setup.tmp / "dl"), run=lambda u, t: "x")
    assert d.enqueue(setup.item_id)
    assert not d.enqueue(setup.item_id) and not d.enqueue(999)
    assert d._queue.qsize() == 1  # çift kuyruklama yok
