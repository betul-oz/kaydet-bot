from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import channels, db, review, texts
from app.config import Config, parse_categories
from app.web import create_app

CATS = parse_categories({"categories": [{"name": "diy", "subcategories": ["hook"]}]})


@pytest.fixture
def conn(tmp_path):
    with closing(db.connect(tmp_path / "h.db")) as c:
        yield c


@pytest.fixture
def vid(tmp_path):
    p = tmp_path / "v.mp4"
    p.write_bytes(b"0" * 100)
    return p


def test_kanal_baslik_alt_baslik_yolu_ve_tekillik(conn, vid):
    v, _ = review.add_video(conn, str(vid), "Flag Derby · A", brand="Flag Derby", category="Maç araları/Son 16")
    ch = channels.channel_list(conn)[0]
    assert [(c["name"], c["parent_id"] is None) for c in ch["cats"]] == [("Maç araları", True), ("Son 16", False)]
    again = channels.ensure_cat(conn, ch["id"], "maç araları/son 16")  # büyük/küçük harf farkı yok sayılır
    assert again == ch["cats"][1]["id"]
    with pytest.raises(channels.ChannelError):
        channels.ensure_cat(conn, ch["id"], "a/b/c")  # en çok iki düzey
    with pytest.raises(channels.ChannelError):
        channels.add_cat(conn, ch["id"], "x", ch["cats"][1]["id"])  # alt başlığın altına yenisi olmaz
    with pytest.raises(channels.ChannelError):
        channels.add_cat(conn, ch["id"], "Maç araları")  # aynı yerde aynı ad
    assert review.get_video(conn, v)["cat_id"] == ch["cats"][1]["id"]


def test_yerlestirme_kanal_degisince_baslik_sifirlanir_baslik_silinince_oge_kalir(conn, vid):
    v, _ = review.add_video(conn, str(vid), "V", brand="A", category="K")
    b = channels.add_channel(conn, "B")
    channels.place(conn, "rv_videos", v, channel_id=b, cat_id=None, set_channel=True, set_cat=False)
    row = review.get_video(conn, v)
    assert row["channel_id"] == b and row["cat_id"] is None and row["brand"] == "B"
    a = channels.channel_list(conn)[0]
    with pytest.raises(channels.ChannelError):
        channels.place(conn, "rv_videos", v, channel_id=None, cat_id=a["cats"][0]["id"], set_channel=False, set_cat=True)  # başka kanalın başlığı
    channels.place(conn, "rv_videos", v, channel_id=a["id"], cat_id=a["cats"][0]["id"], set_channel=True, set_cat=True)
    channels.delete_cat(conn, a["cats"][0]["id"])
    assert review.get_video(conn, v)["cat_id"] is None
    with pytest.raises(channels.ChannelError):
        channels.delete_channel(conn, a["id"])  # içinde öğe var
    review.patch_video(conn, v, dismissed=True)
    assert review.list_videos(conn)[0]["dismissed"] == 1


def test_eski_kayitlar_kanala_tasinir(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript("CREATE TABLE rv_videos (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, brand TEXT NOT NULL DEFAULT '', "
                    "kind TEXT NOT NULL DEFAULT 'yatay', platform TEXT NOT NULL DEFAULT '', project_dir TEXT NOT NULL DEFAULT '', "
                    "status TEXT NOT NULL DEFAULT 'inceleme', task_id INTEGER, created_at TEXT DEFAULT (datetime('now')), "
                    "updated_at TEXT DEFAULT (datetime('now')));"
                    "INSERT INTO rv_videos (title, brand) VALUES ('x', 'Eski Kanal');")
    c.commit(); c.close()
    with closing(db.connect(path)) as c:
        assert [x["name"] for x in channels.channel_list(c)] == ["Eski Kanal"]
        assert c.execute("SELECT channel_id, dismissed FROM rv_videos").fetchone()["dismissed"] == 0


def test_metin_yorum_revizyon_dongusu(conn):
    did, _ = texts.add_doc(conn, "Senaryo", "Bir.\nİki cümle burada.\nÜç.", brand="K", category="Metinler", source_path="/x/s.md")
    assert texts.add_doc(conn, "Senaryo", "baska", source_path="/x/s.md") == (did, False)
    with pytest.raises(texts.TextError):
        texts.request_revision(conn, did)  # yorumsuz/düzenlemesiz revizyon olmaz
    cid = texts.add_comment(conn, did, "İki cümle", "kısalt", line=1)
    with pytest.raises(texts.TextError):
        texts.add_comment(conn, did, "  ", "x")
    prompt = texts.request_revision(conn, did)
    assert "“İki cümle” → kısalt" in prompt and "[satır 2]" in prompt
    for fn in (lambda: texts.add_comment(conn, did, "Üç", "x"), lambda: texts.edit_comment(conn, cid, "y"),
               lambda: texts.delete_comment(conn, cid), lambda: texts.save_content(conn, did, "z"), lambda: texts.approve(conn, did)):
        with pytest.raises(texts.TextError) as e:
            fn()
        assert e.value.status == 409
    assert len(texts.pending_prompts(conn)) == 1
    texts.apply_update(conn, did, "Bir.\nİki.\nÜç.", "kısalttım")
    d = texts.get_doc(conn, did)
    assert d["status"] == "inceleme" and d["comments"][0]["state"] == "uygulandi" and d["comments"][0]["claude_note"] == "kısalttım"
    assert conn.execute("SELECT status FROM tasks").fetchone()["status"] == "hazir"
    assert len(conn.execute("SELECT * FROM rv_doc_backups").fetchall()) == 1


def test_metin_arayuzde_duzenleme_dirty_ve_yedek_siniri(conn):
    did, _ = texts.add_doc(conn, "T", "a")
    stamp = texts.save_content(conn, did, "b")
    assert texts.get_doc(conn, did)["dirty"] == 1
    with pytest.raises(texts.TextError):
        texts.save_content(conn, did, "c", expected_updated_at="eski")  # başka yerden değişti
    for i in range(40):
        texts.save_content(conn, did, f"v{i}")
    assert conn.execute("SELECT COUNT(*) FROM rv_doc_backups").fetchone()[0] == texts.BACKUPS
    assert "doğrudan düzenlemiş" in texts.request_revision(conn, did) and stamp


def test_web_agac_temizleme_ve_metin_uclari(tmp_path, vid):
    cfg = Config(db_path=str(tmp_path / "w.db"), allowed_hosts=["testserver"])
    with closing(db.connect(cfg.db_path)) as c:
        v, _ = review.add_video(c, str(vid), "V", brand="K")
        d, _ = texts.add_doc(c, "D", "Merhaba dünya.", brand="K")
    cl = TestClient(create_app(cfg, CATS))
    t = cl.get("/api/review/tree").json()
    assert t["channels"][0]["name"] == "K" and len(t["videos"]) == 1 and len(t["docs"]) == 1 and "content" not in t["docs"][0]
    ch = t["channels"][0]["id"]
    t = cl.post(f"/api/review/channels/{ch}/cats", json={"name": "Başlık A"}).json()
    cat = t["channels"][0]["cats"][0]["id"]
    t = cl.post(f"/api/review/channels/{ch}/cats", json={"name": "Alt", "parent_id": cat}).json()
    assert cl.post(f"/api/review/channels/{ch}/cats", json={"name": "Alt"}).json()  # üst düzeyde aynı ad serbest
    assert cl.post(f"/api/review/channels/{ch}/cats", json={"name": "Alt", "parent_id": cat}).status_code == 409
    t = cl.patch(f"/api/review/videos/{v}", json={"cat_id": cat}).json()
    assert t["videos"][0]["cat_id"] == cat
    t = cl.patch(f"/api/review/videos/{v}", json={"dismissed": True}).json()
    assert t["videos"][0]["dismissed"] == 1 and t["videos"][0]["cat_id"] == cat  # alan gelmediyse dokunulmaz
    assert cl.patch(f"/api/review/videos/{v}", json={"cat_id": 999}).status_code == 400
    assert cl.patch("/api/review/videos/999", json={"dismissed": True}).status_code == 404
    assert cl.patch(f"/api/review/cats/{cat}", json={"name": "<b>x</b>"}).status_code == 400
    r = cl.post(f"/api/review/docs/{d}/comments", json={"quote": "dünya", "text": "büyük harf", "line": 0, "occ": 0})
    assert r.status_code == 201 and r.json()["comments"][0]["quote"] == "dünya"
    assert cl.put(f"/api/review/docs/{d}/content", json={"content": "Merhaba Dünya."}).json()["dirty"] == 1
    rv = cl.post(f"/api/review/docs/{d}/revise").json()
    assert "büyük harf" in rv["prompt"] and cl.post(f"/api/review/docs/{d}/revise").status_code == 409
    assert cl.put(f"/api/review/docs/{d}/content", json={"content": "x"}).status_code == 409
    assert cl.delete(f"/api/review/channels/{ch}").status_code == 409
    assert cl.delete(f"/api/review/docs/{d}").status_code == 200
    assert cl.post("/api/review/channels", json={"name": "K"}).status_code == 409


def test_cli_metin_ve_kategori(tmp_path, monkeypatch, capsys):
    from app import izle_cli
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"db_path: {(tmp_path / 'i.db').as_posix()}\n", encoding="utf-8")
    md = tmp_path / "s.md"
    md.write_text("Merhaba\n", encoding="utf-8")
    monkeypatch.setenv("KAYDET_CONFIG", str(cfg))
    monkeypatch.setenv("IZLE_CWD", str(tmp_path))
    monkeypatch.delenv("KAYDET_SERVER", raising=False)
    assert izle_cli.main(["metin-ekle", "s.md", "--baslik", "S", "--marka", "K", "--kategori", "A/B"]) == 0
    md.write_text("Değişti\n", encoding="utf-8")
    assert izle_cli.main(["metin-guncelle", "1", "s.md", "--not", "tamam"]) == 0
    md.write_text("elle bozuldu", encoding="utf-8")
    assert izle_cli.main(["metin-al", "1"]) == 0
    assert md.read_text(encoding="utf-8") == "Değişti\n"  # arayüzdeki güncel metin dosyaya yazıldı
    assert izle_cli.main(["metin-guncelle", "99", "s.md"]) == 1


def test_claude_guncellemesi_kullanici_duzenlemesini_ve_gorulmemis_yorumu_ezmez(conn):
    did, _ = texts.add_doc(conn, "T", "bir iki")
    texts.save_content(conn, did, "bir iki üç")  # kullanıcı arayüzde düzenledi (dirty)
    with pytest.raises(texts.TextError) as e:
        texts.apply_update(conn, did, "eski dosya")
    assert e.value.status == 409 and "metin-al" in str(e.value)
    texts.mark_synced(conn, did)
    texts.add_comment(conn, did, "iki", "değiştir")  # revizyon istenmedi
    with pytest.raises(texts.TextError):
        texts.apply_update(conn, did, "yeni")
    texts.apply_update(conn, did, "yeni", force=True)
    assert texts.get_doc(conn, did)["content"] == "yeni"


def test_hayalet_kanal_olmaz_ve_kanalsiz_ogeler_listelenir(conn, vid):
    review.add_video(conn, str(vid), "V", brand="A   B")
    assert [c["name"] for c in channels.channel_list(conn)] == ["A B"]
    channels.migrate(conn)
    assert len(channels.channel_list(conn)) == 1
