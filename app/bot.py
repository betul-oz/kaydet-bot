"""Telegram botu: link al, kategori/alt başlığı butonlarla sor, kaydet."""
from __future__ import annotations

import itertools
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from . import db
from .config import Categories, Config
from .links import Parsed, detect_platform, normalize_url, parse_message
from .meta import fetch_metadata_async

log = logging.getLogger(__name__)
_pending_ids = itertools.count(1)
MAX_PENDING = 50


def is_allowed(user_id: int | None, config: Config) -> bool:
    return user_id is not None and user_id in config.allowed_user_ids


def _uid(update: Update) -> int | None:
    return update.effective_user.id if update.effective_user else None


def _rows(buttons: list[InlineKeyboardButton], per_row: int = 2) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def snapshot(cats: Categories) -> list[tuple[str, list[str]]]:
    """Butonlar gösterildiği andaki kategori listesi; sıra/silme sonradan değişse de doğru adı bulmak için."""
    return [(c.name, [s.name for s in c.subs]) for c in cats.items]


def category_keyboard(snap: list, pid: int) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(name, callback_data=f"c|{pid}|{i}")
            for i, (name, _subs) in enumerate(snap)]
    rows = _rows(btns) + [[InlineKeyboardButton("İptal", callback_data=f"x|{pid}")]]
    return InlineKeyboardMarkup(rows)


def sub_keyboard(snap: list, pid: int, ci: int) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(name, callback_data=f"s|{pid}|{ci}|{si}")
            for si, name in enumerate(snap[ci][1])]
    rows = _rows(btns) + [[InlineKeyboardButton("‹ Geri", callback_data=f"b|{pid}"),
                           InlineKeyboardButton("İptal", callback_data=f"x|{pid}")]]
    return InlineKeyboardMarkup(rows)


async def enrich_item(conn, item_id: int, url: str, meta: dict | None = None) -> None:
    """Kayıttan sonra arka planda başlık ve thumbnail doldurur (meta hazırsa tekrar çekmez)."""
    if meta is None:
        meta = await fetch_metadata_async(url)
    if meta:
        db.set_meta(conn, item_id, title=meta.get("title", ""), thumb_url=meta.get("thumb_url", ""))


async def save_parsed(context: ContextTypes.DEFAULT_TYPE, parsed: Parsed,
                      category: str, subcategory: str) -> tuple[bool, str, int]:
    """Kaydeder. (yeni_mi, kayıtlı_adres, id) döner. TikTok kısa linkleri önce çözülür."""
    conn = context.bot_data["conn"]
    resolved_names = context.bot_data["categories"].resolve(category, subcategory)
    if resolved_names is None:
        raise CategoryChanged()
    url = parsed.url
    meta: dict | None = None
    if parsed.platform == "tiktok" and "/video/" not in url:
        meta = await fetch_metadata_async(url)
        resolved = meta.get("webpage_url", "")
        if resolved and detect_platform(resolved) == "tiktok":
            url = normalize_url(resolved)
    # TikTok kısa linki çözülürken (await) kategori web'den değişmiş olabilir: eklemeden hemen önce tekrar doğrula
    resolved_names = context.bot_data["categories"].resolve(category, subcategory)
    if resolved_names is None:
        raise CategoryChanged()
    category, subcategory = resolved_names
    item_id, is_new = db.add_item(conn, url=url, platform=parsed.platform,
                                  category=category, subcategory=subcategory)
    if is_new:
        context.application.create_task(enrich_item(conn, item_id, url, meta))
        downloader = context.bot_data.get("downloader")
        if downloader is not None and context.bot_data["config"].auto_download:
            downloader.enqueue(item_id)
    return is_new, url, item_id


class CategoryChanged(Exception):
    """Kategori/alt başlık, kullanıcı seçim yaparken web sayfasından silindi veya yeniden adlandırıldı."""


CHANGED_TEXT = "Kategori listesi değişti, bu seçenek artık yok. Linki tekrar gönder."


def _dup_text(row) -> str:
    return f"Bu link zaten kayıtlı: {row['category']} / {row['subcategory']} (#{row['id']})"


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not is_allowed(_uid(update), context.bot_data["config"]):
        return
    await update.message.reply_text(
        "Merhaba! Instagram, TikTok veya YouTube linki gönder, nereye koyacağımı soracağım.\n"
        "Hızlı yol: linkin yanına kategori/alt başlık yaz, örn. 'link diy/hook'.\n"
        "/kategoriler yazarsan seçenekleri görürsün.")


async def on_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not is_allowed(_uid(update), context.bot_data["config"]):
        return
    lines = []
    for c in context.bot_data["categories"].items:
        alias = f" ({', '.join(c.aliases)})" if c.aliases else ""
        subs = ", ".join(s.name + (f" ({'/'.join(s.aliases)})" if s.aliases else "") for s in c.subs)
        lines.append(f"• {c.name}{alias}: {subs}")
    await update.message.reply_text("\n".join(lines))


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not is_allowed(_uid(update), context.bot_data["config"]):
        return
    cats: Categories = context.bot_data["categories"]
    parsed = parse_message(msg.text or msg.caption or "", cats)
    if parsed is None:
        await msg.reply_text("Instagram, TikTok veya YouTube linki bulamadım.")
        return
    conn = context.bot_data["conn"]
    existing = db.get_item_by_url(conn, parsed.url)
    if existing:
        await msg.reply_text(_dup_text(existing))
        return
    if parsed.category and parsed.subcategory:
        try:
            is_new, _url, item_id = await save_parsed(context, parsed, parsed.category, parsed.subcategory)
        except CategoryChanged:
            await msg.reply_text(CHANGED_TEXT)
            return
        if is_new:
            await msg.reply_text(f"✅ Kaydedildi: {parsed.category} / {parsed.subcategory} (#{item_id})")
        else:
            await msg.reply_text(_dup_text(db.get_item(conn, item_id)))
        return
    pending: dict = context.user_data.setdefault("pending", {})
    while len(pending) >= MAX_PENDING:
        pending.pop(next(iter(pending)))
    pid = next(_pending_ids)
    snap = snapshot(cats)
    pending[pid] = {"parsed": parsed, "snap": snap}
    await msg.reply_text(f"Nereye koyayım?\n{parsed.url}", reply_markup=category_keyboard(snap, pid),
                         disable_web_page_preview=True)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or not is_allowed(q.from_user.id if q.from_user else None, context.bot_data["config"]):
        return
    parts = (q.data or "").split("|")
    try:
        action, pid = parts[0], int(parts[1])
        ci = int(parts[2]) if len(parts) > 2 else None
        si = int(parts[3]) if len(parts) > 3 else None
    except (ValueError, IndexError):
        await q.answer()
        return
    pending: dict = context.user_data.setdefault("pending", {})
    entry = pending.get(pid)
    if entry is None:
        await q.answer("Süresi dolmuş, linki tekrar gönder.", show_alert=True)
        return
    parsed: Parsed = entry["parsed"]
    snap: list = entry["snap"]
    await q.answer()
    if action == "x":
        pending.pop(pid, None)
        await q.edit_message_text("İptal edildi.")
    elif action == "b":
        await q.edit_message_text(f"Nereye koyayım?\n{parsed.url}",
                                  reply_markup=category_keyboard(snap, pid),
                                  disable_web_page_preview=True)
    elif action == "c" and ci is not None and 0 <= ci < len(snap):
        await q.edit_message_text(f"{snap[ci][0]} içinde hangi başlık?\n{parsed.url}",
                                  reply_markup=sub_keyboard(snap, pid, ci),
                                  disable_web_page_preview=True)
    elif (action == "s" and ci is not None and si is not None
          and 0 <= ci < len(snap) and 0 <= si < len(snap[ci][1])):
        pending.pop(pid, None)
        cat, sub = snap[ci][0], snap[ci][1][si]  # butonların gösterildiği andaki adlar
        try:
            is_new, _url, item_id = await save_parsed(context, parsed, cat, sub)
        except CategoryChanged:
            await q.edit_message_text(CHANGED_TEXT)
            return
        if is_new:
            await q.edit_message_text(f"✅ Kaydedildi: {cat} / {sub} (#{item_id})")
        else:
            await q.edit_message_text(_dup_text(db.get_item(context.bot_data["conn"], item_id)))


def build_application(token: str, config: Config, categories: Categories, conn) -> Application:
    app = Application.builder().token(token).build()
    app.bot_data.update(config=config, categories=categories, conn=conn)
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler(["kategoriler", "yardim"], on_categories))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler((filters.TEXT & ~filters.COMMAND) | filters.CAPTION, on_message))
    return app
