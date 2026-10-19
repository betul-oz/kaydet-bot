from contextlib import closing

import pytest
import yaml
from fastapi.testclient import TestClient

from app import db
from app.catalog import Catalog, CatalogError
from app.config import Config, load_categories
from app.web import create_app


@pytest.fixture
def env(tmp_path):
    cpath = tmp_path / "categories.yaml"
    cpath.write_text(
        "categories:\n"
        "  - name: diy\n    aliases: [d]\n    subcategories:\n      - {name: hook, aliases: [h]}\n      - metin\n      - gecis\n"
        "  - name: yemek\n    subcategories: [tarif, mekan]\n", encoding="utf-8")
    cats = load_categories(cpath)
    dbp = str(tmp_path / "t.db")
    with closing(db.connect(dbp)) as c:
        for n, (cat, sub) in enumerate([("diy", "hook"), ("diy", "hook"), ("diy", "metin"), ("yemek", "tarif")]):
            db.add_item(c, url=f"https://youtube.com/watch?v=v{n}", platform="youtube", category=cat, subcategory=sub)
    return Catalog(cats, cpath, dbp), cats, cpath, dbp


def disk(cpath):
    return yaml.safe_load(cpath.read_text(encoding="utf-8"))["categories"]


def rows(dbp):
    with closing(db.connect(dbp)) as c:
        return [(r["category"], r["subcategory"]) for r in db.list_items(c)]


def test_alt_baslik_ekle_ve_dosyaya_yazilir(env):
    cat, cats, cpath, _ = env
    cat.add_sub("diy", "  Sahne   arkası ")
    assert [s.name for s in cats.find("diy").subs][-1] == "Sahne arkası"
    assert "Sahne arkası" in str(disk(cpath))
    assert load_categories(cpath).resolve("diy", "sahne_arkası") == ("diy", "Sahne arkası")  # dosya geri okunur


def test_alt_baslik_yeniden_adlandir_videolari_tasir_takma_adi_korur(env):
    cat, cats, cpath, dbp = env
    cat.rename_sub("diy", "hook", "Açılış")
    assert ("diy", "Açılış") in rows(dbp) and ("diy", "hook") not in rows(dbp)
    assert cats.resolve("diy", "h") == ("diy", "Açılış")  # takma ad yaşıyor


def test_kategori_yeniden_adlandir(env):
    cat, cats, _, dbp = env
    cat.rename_category("yemek", "Tarifler")
    assert all(c != "yemek" for c, _ in rows(dbp)) and ("Tarifler", "tarif") in rows(dbp)
    assert cats.find("tarifler") is not None


@pytest.mark.parametrize("bad", ["", "   ", "a/b", "a|b", "x" * 41])
def test_gecersiz_adlar(env, bad):
    cat, *_ = env
    with pytest.raises(CatalogError):
        cat.add_sub("diy", bad)


def test_cakisan_ad_reddedilir_ve_geri_alinir(env):
    cat, cats, cpath, dbp = env
    before = cpath.read_text(encoding="utf-8")
    for fn in (lambda: cat.add_sub("diy", "HOOK"), lambda: cat.rename_sub("diy", "metin", "gecis"),
               lambda: cat.rename_category("yemek", "DİY"), lambda: cat.add_sub("diy", "h")):
        with pytest.raises(CatalogError):
            fn()
    assert cpath.read_text(encoding="utf-8") == before
    assert [s.name for s in cats.find("diy").subs] == ["hook", "metin", "gecis"]
    assert len(rows(dbp)) == 4


def test_sirala(env):
    cat, cats, cpath, _ = env
    cat.move_sub("diy", "gecis", -1)
    assert [s.name for s in cats.find("diy").subs] == ["hook", "gecis", "metin"]
    cat.move_sub("diy", "hook", -1)  # zaten en başta: değişmez
    assert [s.name for s in cats.find("diy").subs][0] == "hook"
    cat.move_category("yemek", -1)
    assert [c["name"] for c in disk(cpath)] == ["yemek", "diy"]


def test_alt_baslik_silme_videolu_ise_hedef_ister(env):
    cat, cats, _, dbp = env
    with pytest.raises(CatalogError) as e:
        cat.delete_sub("diy", "hook")
    assert e.value.status == 409 and "2 video" in str(e.value)
    with pytest.raises(CatalogError):
        cat.delete_sub("diy", "hook", "hook")
    cat.delete_sub("diy", "hook", "metin")
    assert rows(dbp).count(("diy", "metin")) == 3
    cat.delete_sub("diy", "gecis")  # boş başlık doğrudan silinir
    assert [s.name for s in cats.find("diy").subs] == ["metin"]
    with pytest.raises(CatalogError) as e:
        cat.delete_sub("diy", "metin", "x")
    assert e.value.status == 409  # son alt başlık


def test_kategori_silme(env):
    cat, cats, cpath, dbp = env
    with pytest.raises(CatalogError) as e:
        cat.delete_category("diy")
    assert e.value.status == 409
    with pytest.raises(CatalogError):
        cat.delete_category("diy", "diy", "metin")
    cat.delete_category("diy", "yemek", "mekan")
    assert rows(dbp).count(("yemek", "mekan")) == 3 and [c["name"] for c in disk(cpath)] == ["yemek"]
    with pytest.raises(CatalogError) as e:
        cat.delete_category("yemek")
    assert e.value.status == 409  # son kategori


def test_olmayan_kategori_404(env):
    cat, *_ = env
    with pytest.raises(CatalogError) as e:
        cat.add_sub("yok", "x")
    assert e.value.status == 404


def test_yaml_yazma_hatasinda_bellek_ve_db_geri_alinir(env, monkeypatch):
    cat, cats, cpath, dbp = env
    monkeypatch.setattr("app.catalog.save_yaml", lambda *a: (_ for _ in ()).throw(OSError("disk dolu")))
    with pytest.raises(OSError):
        cat.rename_sub("diy", "hook", "Açılış")
    assert cats.find("diy").subs[0].name == "hook" and ("diy", "hook") in rows(dbp)


def test_api_uctan_uca(env):
    cat, cats, cpath, dbp = env
    client = TestClient(create_app(Config(db_path=dbp, allowed_hosts=["testserver"]), cats, None, cat))
    r = client.post("/api/catalog/sub/add", json={"category": "yemek", "name": "tatlı"})
    assert r.status_code == 200 and "tatlı" in [s for c in r.json()["categories"] if c["name"] == "yemek" for s in c["subs"]]
    r = client.post("/api/catalog/sub/delete", json={"category": "diy", "name": "hook"})
    assert r.status_code == 409
    r = client.post("/api/catalog/sub/delete", json={"category": "diy", "name": "hook", "move_to_sub": "metin"})
    assert r.status_code == 200
    items = client.get("/api/state").json()["items"]
    assert sum(1 for i in items if i["subcategory"] == "metin") == 3
    assert client.post("/api/catalog/category/add", json={"name": "a/b", "first_sub": "x"}).status_code == 400
    assert client.post("/api/catalog/category/add", json={"name": "Spor", "first_sub": "antrenman"}).status_code == 200
    # kısa yol için bot tarafı aynı nesneyi görür
    assert cats.resolve("spor", "antrenman") == ("Spor", "antrenman")


def test_api_catalog_kapaliysa_503(tmp_path):
    cats = load_categories("categories.example.yaml")
    client = TestClient(create_app(Config(db_path=str(tmp_path / "t.db"), allowed_hosts=["testserver"]), cats, None, None))
    assert client.post("/api/catalog/sub/add", json={"category": "diy", "name": "x"}).status_code == 503


def test_harf_farkli_db_satirlari_yeniden_adlandirmada_ve_silmede_kaybolmaz(env):
    cat, cats, cpath, dbp = env
    with closing(db.connect(dbp)) as c:  # elle düzenlenmiş/eski kayıt: 'DİY' / 'Hook'
        c.execute("UPDATE items SET category = 'DİY', subcategory = 'Hook' WHERE id = 1")
        c.commit()
    with pytest.raises(CatalogError) as e:
        cat.delete_sub("diy", "hook")  # 'Hook' satırı da sayılmalı (3 değil 2 video)
    assert "2 video" in str(e.value)
    cat.rename_category("diy", "Kendin yap")
    assert all(not r[0].lower().startswith("di") for r in rows(dbp))
    assert ("Kendin yap", "hook") in rows(dbp)


def test_reconcile_harf_farkini_duzeltir(env):
    cat, cats, _, dbp = env
    with closing(db.connect(dbp)) as c:
        c.execute("UPDATE items SET category = 'DIY', subcategory = 'HOOK' WHERE id = 1")
        c.execute("UPDATE items SET category = 'bilinmeyen', subcategory = 'x' WHERE id = 2")
        c.commit()
    assert cat.reconcile() == 1
    r = rows(dbp)
    assert ("diy", "hook") in r and ("bilinmeyen", "x") in r  # bilinmeyen olan olduğu gibi kalır


@pytest.mark.parametrize("bad", ["<img src=x onerror=alert(1)>", "a​b", "x‮y"])
def test_tehlikeli_karakterli_adlar(env, bad):
    cat, *_ = env
    with pytest.raises(CatalogError):
        cat.add_sub("diy", bad)


def test_commit_hatasinda_yaml_eski_haline_doner(env, monkeypatch):
    cat, cats, cpath, dbp = env
    before = cpath.read_text(encoding="utf-8")
    real_connect = db.connect

    class Boom:
        def __init__(self, conn):
            self._c = conn

        def execute(self, sql, *a):
            if sql == "COMMIT":
                raise OSError("database is locked")
            return self._c.execute(sql, *a)

        def __getattr__(self, name):
            return getattr(self._c, name)

        @property
        def isolation_level(self):
            return self._c.isolation_level

        @isolation_level.setter
        def isolation_level(self, v):
            self._c.isolation_level = v

    monkeypatch.setattr("app.catalog.db.connect", lambda p: Boom(real_connect(p)))
    with pytest.raises(OSError):
        cat.rename_sub("diy", "hook", "Açılış")
    assert cpath.read_text(encoding="utf-8") == before  # yaml geri yazıldı
    assert cats.find("diy").subs[0].name == "hook"
    assert ("diy", "hook") in rows(dbp)


def test_catalog_uclari_capraz_siteden_reddedilir(env):
    cat, cats, _, dbp = env
    client = TestClient(create_app(Config(db_path=dbp, allowed_hosts=["testserver"]), cats, None, cat))
    r = client.post("/api/catalog/sub/add", json={"category": "diy", "name": "x"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert "x" not in [s.name for s in cats.find("diy").subs]


def test_es_zamanli_silme_ve_ekleme_video_kaybetmez(env):
    import threading
    cat, cats, _, dbp = env
    errors = []

    def adder():
        for n in range(30):
            with closing(db.connect(dbp)) as c:
                try:
                    cc = cats.find("yemek")
                    db.add_item(c, url=f"https://youtube.com/watch?v=t{n}", platform="youtube",
                                category="yemek", subcategory="mekan")
                except Exception as e:  # noqa
                    errors.append(e)

    t = threading.Thread(target=adder)
    t.start()
    try:
        cat.delete_sub("yemek", "mekan", "tarif")
    except CatalogError:
        pass
    t.join()
    assert not errors
    # silinen 'mekan' başlığında sahipsiz video kalmış olabilir ama bunlar reconcile/Kategorisiz ile görünür kalır
    with closing(db.connect(dbp)) as c:
        assert c.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 4 + 30
