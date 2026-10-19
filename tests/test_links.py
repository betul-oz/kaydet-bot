from app.config import parse_categories
from app.links import detect_platform, extract_urls, normalize_url, parse_message

CATS = parse_categories({"categories": [
    {"name": "diy", "aliases": ["d"], "subcategories": [
        {"name": "hook", "aliases": ["h"]}, "metin"]},
]})


def test_platform_tanima():
    assert detect_platform("https://www.instagram.com/reel/abc/") == "instagram"
    assert detect_platform("https://vm.tiktok.com/ZM123/") == "tiktok"
    assert detect_platform("https://www.tiktok.com/@u/video/1") == "tiktok"
    assert detect_platform("https://youtu.be/xyz") == "youtube"
    assert detect_platform("https://m.youtube.com/watch?v=1") == "youtube"
    assert detect_platform("https://example.com/x") is None
    assert detect_platform("https://evilinstagram.com/x") is None


def test_normalize_takip_parametreleri_atilir():
    a = normalize_url("https://www.instagram.com/reel/abc/?igsh=XYZ&utm_source=ig")
    b = normalize_url("http://instagram.com/reel/abc")
    assert a == b == "https://instagram.com/reel/abc"


def test_normalize_youtube_v_korunur():
    assert normalize_url("https://www.youtube.com/watch?v=abc&si=zzz&feature=share") \
        == "https://youtube.com/watch?v=abc"


def test_extract_urls_noktalama():
    assert extract_urls("bak https://youtu.be/xyz.") == ["https://youtu.be/xyz"]


def test_kisa_yol_ad_ve_takma_ad():
    p = parse_message("https://youtu.be/xyz diy/hook", CATS)
    assert (p.category, p.subcategory) == ("diy", "hook")
    p = parse_message("d/h https://youtu.be/xyz", CATS)
    assert (p.category, p.subcategory) == ("diy", "hook")


def test_kisa_yol_yoksa_veya_gecersizse_bos():
    assert parse_message("https://youtu.be/xyz", CATS).category is None
    assert parse_message("https://youtu.be/xyz foo/bar", CATS).category is None


def test_link_icinde_slash_kisa_yol_sayilmaz():
    p = parse_message("https://www.instagram.com/reel/abc/", CATS)
    assert p.category is None


def test_desteklenmeyen_link_none():
    assert parse_message("https://example.com/a diy/hook", CATS) is None
    assert parse_message("merhaba", CATS) is None


def test_youtube_tum_bicimler_ayni_kayit():
    hedef = "https://youtube.com/watch?v=abcdef123"
    for u in ["https://youtu.be/abcdef123", "https://youtu.be/abcdef123?t=15",
              "https://www.youtube.com/watch?v=abcdef123&list=PL1&t=15s",
              "https://m.youtube.com/watch?v=abcdef123&si=zz",
              "https://youtube.com/shorts/abcdef123?feature=share"]:
        assert normalize_url(u) == hedef, u


def test_instagram_bicimler_ayni_kayit():
    hedef = "https://instagram.com/reel/AbC_d-1"
    for u in ["https://www.instagram.com/reel/AbC_d-1/?igsh=x&hl=tr",
              "https://instagram.com/reels/AbC_d-1/",
              "https://www.instagram.com/p/AbC_d-1/?img_index=1",
              "https://www.instagram.com/kullanici/reel/AbC_d-1/"]:
        assert normalize_url(u) == hedef, u


def test_tiktok_sorgu_atilir_ve_kisa_link_korunur():
    assert normalize_url("https://www.tiktok.com/@u/video/123?lang=tr&share_app_id=1&u_code=x") \
        == "https://tiktok.com/@u/video/123"
    assert normalize_url("https://vm.tiktok.com/ZM123/?foo=1") == "https://vm.tiktok.com/ZM123"


def test_kisa_yol_noktalama_bosluk_buyuk_harf():
    cats = parse_categories({"categories": [
        {"name": "diy", "subcategories": ["hook"]},
        {"name": "el işi", "subcategories": ["tarif"]}]})
    for msg in ["https://youtu.be/xyzxyz diy/hook,", "https://youtu.be/xyzxyz (diy/hook)",
                "https://youtu.be/xyzxyz diy / hook", "https://youtu.be/xyzxyz DİY/HOOK",
                "https://youtu.be/xyzxyz Diy/Hook"]:
        p = parse_message(msg, cats)
        assert (p.category, p.subcategory) == ("diy", "hook"), msg
    p = parse_message("https://youtu.be/xyzxyz el_işi/tarif", cats)
    assert (p.category, p.subcategory) == ("el işi", "tarif")


def test_kullanici_bilgili_sahte_adres_reddedilir():
    for u in ["https://tiktok.com:443@127.0.0.1:8080/admin", "https://instagram.com:1@evil.example/x",
              "https://youtube.com@evil.example/watch?v=abcdef123"]:
        assert detect_platform(u) is None, u
        assert parse_message(u, CATS) is None, u
