import pytest

from app import db


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def _add(conn, url="https://youtu.be/a", cat="diy", sub="hook"):
    return db.add_item(conn, url=url, platform="youtube", category=cat, subcategory=sub)


def test_ekle_ve_cift_kayit_engeli(conn):
    i1, yeni1 = _add(conn)
    i2, yeni2 = _add(conn)
    assert yeni1 and not yeni2 and i1 == i2
    assert len(db.list_items(conn)) == 1


def test_filtre_ve_arama(conn):
    _add(conn, "https://youtu.be/a", "diy", "hook")
    _add(conn, "https://youtu.be/b", "yemek", "tarif")
    assert len(db.list_items(conn, category="diy")) == 1
    assert len(db.list_items(conn, subcategory="tarif")) == 1
    assert len(db.list_items(conn, search="youtu.be/b")) == 1


def test_tasima_not_durum_silme(conn):
    i, _ = _add(conn)
    assert db.move_item(conn, i, "yemek", "tarif")
    assert db.set_note(conn, i, "güzel geçiş")
    assert db.set_status(conn, i, "indirildi", file_path="downloads/x.mp4")
    row = db.get_item(conn, i)
    assert (row["category"], row["subcategory"]) == ("yemek", "tarif")
    assert row["note"] == "güzel geçiş" and row["status"] == "indirildi"
    assert db.delete_item(conn, i)
    assert db.get_item(conn, i) is None


def test_gecersiz_durum(conn):
    i, _ = _add(conn)
    with pytest.raises(ValueError):
        db.set_status(conn, i, "uydurma")


def test_olmayan_kayit_false_doner(conn):
    assert not db.move_item(conn, 999, "a", "b")
    assert not db.delete_item(conn, 999)


def test_arama_ozel_karakterler_kacislanir(conn):
    _add(conn, "https://youtu.be/a")
    assert db.list_items(conn, search="_") == []
    assert db.list_items(conn, search="%") == []
    assert len(db.list_items(conn, search="youtu.be/a")) == 1


def test_item_silinince_kart_baglantisi_duser(conn):
    i, _ = _add(conn)
    conn.execute("INSERT INTO cards (title) VALUES ('k')")
    conn.execute("INSERT INTO card_items (card_id, item_id, position) VALUES (1, ?, 0)", (i,))
    db.delete_item(conn, i)
    assert conn.execute("SELECT COUNT(*) FROM card_items").fetchone()[0] == 0
