import pytest

from app.config import load_categories, load_config, parse_categories


def test_categories_example_yuklenir():
    cats = load_categories("categories.example.yaml")
    assert cats.resolve("D", "H") == ("diy", "hook")
    assert cats.resolve("yemek", "tarif") == ("yemek", "tarif")
    assert cats.resolve("diy", "yok") is None
    assert cats.resolve("yok", "hook") is None


def test_bos_categories_hata():
    with pytest.raises(ValueError):
        parse_categories({})


def test_gecersiz_alt_baslik_hata():
    with pytest.raises(ValueError):
        parse_categories({"categories": [{"name": "a", "subcategories": [{"x": 1}]}]})


def test_categories_dosya_yoksa_anlasilir_hata(tmp_path):
    with pytest.raises(FileNotFoundError, match="example"):
        load_categories(tmp_path / "yok.yaml")


def test_config_yoksa_varsayilan(tmp_path):
    c = load_config(tmp_path / "yok.yaml")
    assert c.allowed_user_ids == [] and c.auto_download is False


def test_config_okuma(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("allowed_user_ids: [1, '2']\nauto_download: true\n", encoding="utf-8")
    c = load_config(p)
    assert c.allowed_user_ids == [1, 2] and c.auto_download is True


def test_auto_download_metin_ve_gecersiz(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text('auto_download: "false"\n', encoding="utf-8")
    assert load_config(p).auto_download is False
    p.write_text("auto_download: belki\n", encoding="utf-8")
    with pytest.raises(ValueError, match="auto_download"):
        load_config(p)
    p.write_text("allowed_user_ids: [abc]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="allowed_user_ids"):
        load_config(p)


def test_kategori_dogrulama():
    with pytest.raises(ValueError, match="alt başlığı yok"):
        parse_categories({"categories": ["yemek"]})
    with pytest.raises(ValueError, match="çakış"):
        parse_categories({"categories": [
            {"name": "a", "aliases": ["x"], "subcategories": ["s"]},
            {"name": "x", "subcategories": ["s"]}]})
    with pytest.raises(ValueError, match="çakış"):
        parse_categories({"categories": [
            {"name": "a", "subcategories": ["s", {"name": "t", "aliases": ["S"]}]}]})
