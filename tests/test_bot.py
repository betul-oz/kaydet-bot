import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import bot, db
from app.config import Config, parse_categories

CATS = parse_categories({"categories": [
    {"name": "diy", "aliases": ["d"], "subcategories": [{"name": "hook", "aliases": ["h"]}, "metin"]},
    {"name": "yemek", "subcategories": ["tarif"]},
]})
CFG = Config(allowed_user_ids=[42])
YT = "https://youtu.be/abcdef123"
YT_NORM = "https://youtube.com/watch?v=abcdef123"


@pytest.fixture
def env(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "t.db")
    tasks = []

    async def fake_meta(url, timeout=30):
        return {"title": "Başlık", "thumb_url": "http://t/x.jpg", "webpage_url": "https://www.tiktok.com/@u/video/777?x=1"}

    monkeypatch.setattr(bot, "fetch_metadata_async", fake_meta)
    app = SimpleNamespace(create_task=lambda coro: tasks.append(coro))
    ctx = SimpleNamespace(bot_data={"config": CFG, "categories": CATS, "conn": conn},
                          user_data={}, application=app)
    yield SimpleNamespace(conn=conn, ctx=ctx, tasks=tasks)
    for t in tasks:
        t.close()  # await edilmeyen arka plan görevleri uyarı vermesin
    conn.close()


def _update(text, uid=42):
    msg = SimpleNamespace(text=text, caption=None, reply_text=AsyncMock())
    return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=uid), callback_query=None)


def _cb(data, uid=42):
    q = SimpleNamespace(data=data, from_user=SimpleNamespace(id=uid), answer=AsyncMock(),
                        edit_message_text=AsyncMock())
    return SimpleNamespace(callback_query=q, message=None, effective_user=SimpleNamespace(id=uid)), q


def run(coro):
    return asyncio.run(coro)


def test_izinsiz_kullaniciya_cevap_yok(env):
    u = _update(YT, uid=999)
    run(bot.on_message(u, env.ctx))
    u.message.reply_text.assert_not_called()
    assert db.list_items(env.conn) == []
    u2, q = _cb("c|1|0", uid=999)
    run(bot.on_callback(u2, env.ctx))
    q.answer.assert_not_called()


def test_bos_izin_listesi_kimseye_cevap_vermez(env):
    env.ctx.bot_data["config"] = Config(allowed_user_ids=[])
    u = _update(YT)
    run(bot.on_message(u, env.ctx))
    u.message.reply_text.assert_not_called()


def test_link_yoksa_uyari(env):
    u = _update("merhaba")
    run(bot.on_message(u, env.ctx))
    assert "bulamadım" in u.message.reply_text.call_args.args[0]


def test_kisa_yol_sormadan_kaydeder(env):
    u = _update(f"{YT} d/h")
    run(bot.on_message(u, env.ctx))
    row = db.get_item_by_url(env.conn, YT_NORM)
    assert (row["category"], row["subcategory"]) == ("diy", "hook")
    assert "Kaydedildi" in u.message.reply_text.call_args.args[0]
    assert len(env.tasks) == 1  # arka plan başlık doldurma
    run(env.tasks[0])
    assert db.get_item_by_url(env.conn, YT_NORM)["title"] == "Başlık"


def test_butonlu_akis(env):
    u = _update(YT)
    run(bot.on_message(u, env.ctx))
    kb = u.message.reply_text.call_args.kwargs["reply_markup"]
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert any(d.startswith("c|") for d in data) and any(d.startswith("x|") for d in data)
    assert all(len(d.encode()) <= 64 for d in data)
    pid = int(data[0].split("|")[1])

    u2, q = _cb(f"c|{pid}|0")
    run(bot.on_callback(u2, env.ctx))
    kb2 = q.edit_message_text.call_args.kwargs["reply_markup"]
    sub_data = [b.callback_data for row in kb2.inline_keyboard for b in row]
    assert f"s|{pid}|0|1" in sub_data and f"b|{pid}" in sub_data

    u3, q3 = _cb(f"s|{pid}|0|1")
    run(bot.on_callback(u3, env.ctx))
    row = db.get_item_by_url(env.conn, YT_NORM)
    assert (row["category"], row["subcategory"]) == ("diy", "metin")
    assert "Kaydedildi" in q3.edit_message_text.call_args.args[0]


def test_iptal_ve_suresi_dolmus(env):
    u = _update(YT)
    run(bot.on_message(u, env.ctx))
    pid = next(iter(env.ctx.user_data["pending"]))
    u2, q = _cb(f"x|{pid}")
    run(bot.on_callback(u2, env.ctx))
    assert db.list_items(env.conn) == []
    u3, q3 = _cb(f"s|{pid}|0|0")  # artık bekleyen yok
    run(bot.on_callback(u3, env.ctx))
    assert q3.answer.call_args.kwargs.get("show_alert") is True
    assert db.list_items(env.conn) == []


def test_ayni_link_ikinci_kez_uyarir(env):
    run(bot.on_message(_update(f"{YT} diy/hook"), env.ctx))
    u = _update(f"{YT}?t=5 yemek/tarif")
    run(bot.on_message(u, env.ctx))
    assert "zaten kayıtlı" in u.message.reply_text.call_args.args[0]
    assert len(db.list_items(env.conn)) == 1


def test_bozuk_callback_verisi_cokmez(env):
    for data in ["", "c", "c|abc", "s|1|99|99", "z|1"]:
        u, q = _cb(data)
        run(bot.on_callback(u, env.ctx))


def test_tiktok_kisa_link_cozulur_ve_cift_kayit_olmaz(env):
    short = "https://vm.tiktok.com/ZM123"
    run(bot.on_message(_update(f"{short} yemek/tarif"), env.ctx))
    row = db.get_item_by_url(env.conn, "https://tiktok.com/@u/video/777")
    assert row is not None and row["platform"] == "tiktok"
    u = _update(f"{short}x https://vt.tiktok.com/ABC yemek/tarif")  # farklı kısa link, aynı video
    run(bot.on_message(u, env.ctx))
    assert len(db.list_items(env.conn)) == 1
    assert "zaten kayıtlı" in u.message.reply_text.call_args.args[0]


def test_kategoriler_komutu(env):
    u = _update("/kategoriler")
    run(bot.on_categories(u, env.ctx))
    text = u.message.reply_text.call_args.args[0]
    assert "diy" in text and "hook" in text and "yemek" in text


def test_gecerli_pid_ile_aralik_disi_indeks_kaydetmez(env):
    run(bot.on_message(_update(YT), env.ctx))
    pid = next(iter(env.ctx.user_data["pending"]))
    for data in [f"s|{pid}|99|0", f"s|{pid}|0|99", f"c|{pid}|99", f"s|{pid}|-1|0"]:
        u, q = _cb(data)
        run(bot.on_callback(u, env.ctx))
    assert db.list_items(env.conn) == []
    assert pid in env.ctx.user_data["pending"]


def test_izinsiz_start_ve_kategoriler_sessiz(env):
    for fn in (bot.on_start, bot.on_categories):
        u = _update("/start", uid=999)
        run(fn(u, env.ctx))
        u.message.reply_text.assert_not_called()


def test_tiktok_kisa_link_baska_platforma_cikarsa_kisa_link_kalir(env, monkeypatch):
    async def fake_meta(url, timeout=30):
        return {"webpage_url": "https://example.com/video/1"}
    monkeypatch.setattr(bot, "fetch_metadata_async", fake_meta)
    run(bot.on_message(_update("https://vm.tiktok.com/ZM9 yemek/tarif"), env.ctx))
    assert db.get_item_by_url(env.conn, "https://vm.tiktok.com/ZM9") is not None


def test_build_application_handlerlari_baglar():
    app = bot.build_application("123:abc", CFG, CATS, None)
    handlers = [type(h).__name__ for g in app.handlers.values() for h in g]
    assert handlers.count("CommandHandler") == 2
    assert "CallbackQueryHandler" in handlers and "MessageHandler" in handlers
