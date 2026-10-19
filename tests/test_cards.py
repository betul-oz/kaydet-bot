import pytest

from app import db
from app.cards import format_card


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    yield c
    c.close()


def _item(conn, n, **kw):
    i, _ = db.add_item(conn, url=f"https://youtube.com/watch?v=v{n}", platform="youtube",
                       category="diy", subcategory="hook", title=kw.get("title", f"Video {n}"))
    return i


def test_kart_olustur_ekle_sirala(conn):
    a, b, c = _item(conn, 1), _item(conn, 2), _item(conn, 3)
    card = db.create_card(conn, "Plan", "notum")
    for i in (a, b, c):
        assert db.add_card_item(conn, card, i)
    assert not db.add_card_item(conn, card, a)  # çift ekleme yok
    assert [x["id"] for x in db.get_card(conn, card)["items"]] == [a, b, c]
    db.move_card_item(conn, card, c, -1)
    assert [x["id"] for x in db.get_card(conn, card)["items"]] == [a, c, b]
    db.move_card_item(conn, card, a, -1)  # en üstte: sıra bozulmaz
    assert [x["id"] for x in db.get_card(conn, card)["items"]] == [a, c, b]
    assert db.remove_card_item(conn, card, c)
    assert [x["id"] for x in db.get_card(conn, card)["items"]] == [a, b]


def test_olmayan_kart_veya_video(conn):
    a = _item(conn, 1)
    card = db.create_card(conn, "P")
    assert not db.add_card_item(conn, 999, a)
    assert not db.add_card_item(conn, card, 999)
    assert db.get_card(conn, 999) is None
    assert not db.update_card(conn, 999, title="x")
    assert not db.delete_card(conn, 999)


def test_kart_silinince_videolar_kalir(conn):
    a = _item(conn, 1)
    card = db.create_card(conn, "P")
    db.add_card_item(conn, card, a)
    db.delete_card(conn, card)
    assert db.get_item(conn, a) is not None


def test_kopyala_bicimi_link_ve_notlar_eksiksiz(conn):
    a, b = _item(conn, 1, title="Hook videosu"), _item(conn, 2, title="Metin videosu")
    db.set_note(conn, b, "kayıt notu satır1\nsatır2")
    db.set_status(conn, a, "indirildi", file_path="C:/d/hook.mp4")
    card = db.create_card(conn, "Cuma reels", "Açılışta soru sor.\nSonda takip çağrısı.")
    db.add_card_item(conn, card, a)
    db.add_card_item(conn, card, b)
    db.set_card_item_note(conn, card, a, "ilk 3 sn bunu kullan")
    text = format_card(db.get_card(conn, card))
    assert text.startswith("# Cuma reels\n")
    assert "## Notlarım\nAçılışta soru sor.\nSonda takip çağrısı." in text
    assert "1. [diy / hook] Hook videosu (youtube)" in text
    assert "   Link: https://youtube.com/watch?v=v1" in text
    assert "   Not: ilk 3 sn bunu kullan" in text
    assert "   Dosya: C:/d/hook.mp4" in text
    assert "2. [diy / hook] Metin videosu (youtube)" in text
    assert "   Link: https://youtube.com/watch?v=v2" in text
    assert "Kayıt notu: kayıt notu satır1\n        satır2" in text
    assert text.index("1. [diy / hook] Hook videosu") < text.index("2. [diy / hook] Metin videosu")


def test_bos_kart_ve_basliksiz_video(conn):
    card = db.create_card(conn, "Boş")
    assert "(henüz video eklenmedi)" in format_card(db.get_card(conn, card))
    a = _item(conn, 1, title="")
    db.add_card_item(conn, card, a)
    assert "(başlıksız)" in format_card(db.get_card(conn, card))
    assert "## Notlarım" not in format_card(db.get_card(conn, card))
