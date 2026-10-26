"""Web arayüzü ve JSON API (FastAPI). Varsayılan olarak yalnızca bu bilgisayardan erişilir."""
from __future__ import annotations

import hmac
import os
import re
import uuid
from contextlib import closing
from pathlib import Path

from typing import Annotated
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from . import analytics, auth, board, channels, db, planning, review, texts
from .cards import format_card
from .catalog import Catalog, CatalogError
from .config import Categories, Config
from .downloader import Downloader

STATIC = Path(__file__).parent / "static"


class ItemPatch(BaseModel):
    note: str | None = Field(None, max_length=5000)
    category: str | None = Field(None, max_length=200)
    subcategory: str | None = Field(None, max_length=200)


class SubRef(BaseModel):
    category: str = Field(max_length=200)
    subcategory: str = Field(max_length=200)


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class CardCreate(BaseModel):
    title: Title
    note: str = Field("", max_length=20000)


class CardPatch(BaseModel):
    title: Title | None = None
    note: str | None = Field(None, max_length=20000)


class CardItemAdd(BaseModel):
    item_id: int


class CardItemPatch(BaseModel):
    note: str | None = Field(None, max_length=5000)
    move: int | None = Field(None, description="-1 yukarı, 1 aşağı")


class TodoCreate(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class TodoPatch(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None
    done: bool | None = None


class CatAdd(BaseModel):
    name: str = Field(max_length=200)
    first_sub: str = Field(max_length=200)


class CatRef(BaseModel):
    name: str = Field(max_length=200)


class CatRename(CatRef):
    new_name: str = Field(max_length=200)


class CatMove(CatRef):
    direction: int


class CatDelete(CatRef):
    move_to_category: str = Field("", max_length=200)
    move_to_sub: str = Field("", max_length=200)


class SubAdd(BaseModel):
    category: str = Field(max_length=200)
    name: str = Field(max_length=200)


class SubRename(SubAdd):
    new_name: str = Field(max_length=200)


class SubMove(SubAdd):
    direction: int


class SubDelete(SubAdd):
    move_to_sub: str = Field("", max_length=200)


class AccountAdd(BaseModel):
    brand: str = Field(max_length=100)
    platform: str = Field(max_length=20)
    handle: str = Field(max_length=300)


class PostUrl(BaseModel):
    url: str = Field(max_length=500)


class TaskAdd(BaseModel):
    title: str = Field(max_length=200)
    brand: str = Field("", max_length=60)
    platform: str = Field("", max_length=20)
    due: str = Field("", max_length=10)
    note: str = Field("", max_length=2000)


class TaskPatch(BaseModel):
    status: str | None = Field(None, max_length=20)
    title: str | None = Field(None, max_length=200)
    note: str | None = Field(None, max_length=2000)
    due: str | None = Field(None, max_length=10)


class MessageAdd(BaseModel):
    text: str = Field(max_length=2000)
    author: str = Field("sen", max_length=10)


class NoteAdd(BaseModel):
    version_id: int
    t: float = Field(ge=0, le=86400)
    text: str = Field(max_length=2000)


class NoteEdit(BaseModel):
    text: str = Field(max_length=2000)


class NameBody(BaseModel):
    name: str = Field(max_length=100)


class CatCreate(NameBody):
    parent_id: int | None = None
    kind: str = Field("v", max_length=1)


class ItemPatch2(BaseModel):
    """Video veya metin: başlık, yerleşim, temizleme. Alan gelmediyse dokunulmaz."""
    title: str | None = Field(None, max_length=200)
    dismissed: bool | None = None
    channel_id: int | None = None
    cat_id: int | None = None


class CommentAdd(BaseModel):
    quote: str = Field(max_length=800)
    text: str = Field(max_length=4000)
    line: int = Field(0, ge=0, le=1_000_000)
    occ: int = Field(0, ge=0, le=1_000_000)


class TextBody(BaseModel):
    text: str = Field(max_length=4000)


class CommentPatch(BaseModel):
    text: str = Field(max_length=4000)


class DocContent(BaseModel):
    content: str = Field(max_length=4_000_000)
    expected_updated_at: str | None = None


MAX_UPLOAD = int(os.environ.get("KAYDET_MAX_UPLOAD_MB", "3072")) * 1024 * 1024


class HubVideo(BaseModel):
    ref: str = Field(max_length=100)
    title: str = Field(max_length=200)
    brand: str = Field("", max_length=60)
    category: str = Field("", max_length=130)
    kind: str = Field("yatay", max_length=10)
    platform: str = Field("", max_length=20)
    project_dir: str = Field("", max_length=500)


class HubVersion(BaseModel):
    ref: str = Field(max_length=100)


class HubDoc(BaseModel):
    title: str = Field(max_length=200)
    content: str = Field(max_length=4_000_000)
    brand: str = Field("", max_length=60)
    category: str = Field("", max_length=130)
    source_path: str = Field("", max_length=500)


class HubUpdate(BaseModel):
    content: str = Field(max_length=4_000_000)
    note: str = Field("", max_length=2000)
    force: bool = False


class BrandBody(BaseModel):
    name: str = Field(max_length=100)


class PlanBulk(BaseModel):
    text: str = Field(max_length=20000)
    platform: str = Field("", max_length=20)


class AccountMove(BaseModel):
    brand_id: int


class BatchAdd(BaseModel):
    title: str = Field("", max_length=100)
    start: str = Field(max_length=10)


def create_app(config: Config, categories: Categories,
               downloader: Downloader | None = None, catalog: Catalog | None = None,
               syncer: analytics.Syncer | None = None) -> FastAPI:
    app = FastAPI(title="kaydet-bot", docs_url=None, redoc_url=None, openapi_url=None)
    # DNS rebinding'e karşı: yalnızca yerel adlarla (ve config.allowed_hosts ile) erişim
    hosts = {"localhost", "127.0.0.1", "[::1]", *config.allowed_hosts}
    if config.web_host not in ("0.0.0.0", "::", ""):
        hosts.add(config.web_host)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(hosts))
    origin_hosts = {h.strip("[]") for h in hosts}

    @app.middleware("http")
    async def block_cross_site_writes(request: Request, call_next):
        # Başka bir sitenin tarayıcıdan yerel API'ye yazma isteği atmasını engelle (CSRF)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            cross = request.headers.get("sec-fetch-site") == "cross-site"
            if cross or (origin and (urlparse(origin).hostname or "") not in origin_hosts):
                return JSONResponse({"detail": "Başka siteden gelen istek reddedildi"}, status_code=403)
        return await call_next(request)

    # Yayın: şifre (tarayıcı, çerez) ve token (izle.py) ile giriş. İkisi de boşsa kapalı (yerel kullanım).
    auth_on = bool(config.password or config.api_token)
    limiter = auth.FailLimiter()

    @app.middleware("http")
    async def require_auth(request: Request, call_next):
        if not auth_on or request.url.path in ("/login", "/logout", "/healthz"):
            return await call_next(request)
        if auth.token_ok(config.api_token, request.headers.get("authorization")) or \
                auth.cookie_ok(config.password, request.cookies.get(auth.COOKIE)):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Giriş gerekli"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    @app.get("/healthz")
    def healthz():
        return PlainTextResponse("ok")

    @app.get("/login")
    def login_page():
        if not config.password:
            if config.api_token:
                return PlainTextResponse("Tarayıcı girişi için KAYDET_PASSWORD tanımlı değil.", status_code=503)
            return RedirectResponse("/", status_code=303)
        return HTMLResponse(auth.LOGIN_HTML.replace("__ERR__", ""), headers={"Cache-Control": "no-store"})

    @app.post("/login")
    async def login(request: Request):
        if not config.password:
            return RedirectResponse("/", status_code=303)
        # Proxy'nin (Traefik) eklediği son X-Forwarded-For değeri; yoksa doğrudan bağlanan adres
        who = request.headers.get("x-forwarded-for", "").split(",")[-1].strip() or (request.client.host if request.client else "")
        if limiter.blocked(who):
            return HTMLResponse(auth.LOGIN_HTML.replace("__ERR__", '<p class="err">Çok fazla hatalı deneme; birkaç dakika bekle.</p>'), status_code=429)
        raw = b""
        async for chunk in request.stream():  # giriş yapmamış istemci bellek dolduramasın
            raw += chunk
            if len(raw) > 4096:
                return HTMLResponse("Gövde çok büyük", status_code=413)
        form = parse_qs(raw.decode("utf-8", "replace"))
        given = (form.get("password") or [""])[0]
        if not hmac.compare_digest(given.encode(), config.password.encode()):
            limiter.add(who)
            return HTMLResponse(auth.LOGIN_HTML.replace("__ERR__", '<p class="err">Şifre yanlış.</p>'), status_code=401)
        secure = request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https"
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(auth.COOKIE, auth.make_cookie(config.password), max_age=auth.SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", secure=secure)
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(auth.COOKIE)
        return resp

    def conn():
        return closing(db.connect(config.db_path))

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/state")
    def state():
        with conn() as c:
            return {
                "categories": [{"name": cat.name, "subs": [s.name for s in cat.subs]}
                               for cat in categories.items],
                "items": [dict(r) for r in db.list_items(c)],
                "downloads_enabled": downloader is not None,
            }

    @app.patch("/api/items/{item_id}")
    def patch_item(item_id: int, body: ItemPatch):
        with conn() as c:
            if db.get_item(c, item_id) is None:
                raise HTTPException(404, "Kayıt yok")
            resolved = None
            if body.category is not None or body.subcategory is not None:
                resolved = categories.resolve(body.category or "", body.subcategory or "")
                if resolved is None:  # önce doğrula: kısmi güncelleme kalmasın
                    raise HTTPException(400, "Bilinmeyen kategori/alt başlık")
            if body.note is not None:
                db.set_note(c, item_id, body.note)
            if resolved:
                db.move_item(c, item_id, *resolved)
            return dict(db.get_item(c, item_id))

    @app.delete("/api/items/{item_id}")
    def delete_item(item_id: int):
        with conn() as c:
            if not db.delete_item(c, item_id):
                raise HTTPException(404, "Kayıt yok")
        return {"ok": True}

    @app.post("/api/items/{item_id}/download")
    def download_item(item_id: int):
        if downloader is None:
            raise HTTPException(503, "İndirme kapalı")
        if not downloader.enqueue(item_id):
            raise HTTPException(409, "Kayıt yok veya zaten indiriliyor")
        return {"ok": True}

    @app.post("/api/download-sub")
    def download_sub(body: SubRef):
        if downloader is None:
            raise HTTPException(503, "İndirme kapalı")
        with conn() as c:
            ids = [r["id"] for r in db.list_items(c, category=body.category, subcategory=body.subcategory)
                   if r["status"] in ("kayitli", "hata")]
        queued = sum(1 for i in ids if downloader.enqueue(i))
        return {"queued": queued}

    # ---- Plan kartları ----
    @app.get("/api/cards")
    def cards():
        with conn() as c:
            return db.list_cards(c)

    @app.post("/api/cards", status_code=201)
    def create_card(body: CardCreate):
        with conn() as c:
            return db.get_card(c, db.create_card(c, body.title, body.note))

    @app.patch("/api/cards/{card_id}")
    def patch_card(card_id: int, body: CardPatch):
        with conn() as c:
            if not db.update_card(c, card_id, title=body.title, note=body.note):
                raise HTTPException(404, "Kart yok")
            return db.get_card(c, card_id)

    @app.delete("/api/cards/{card_id}")
    def delete_card(card_id: int):
        with conn() as c:
            if not db.delete_card(c, card_id):
                raise HTTPException(404, "Kart yok")
        return {"ok": True}

    @app.post("/api/cards/{card_id}/items")
    def add_card_item(card_id: int, body: CardItemAdd):
        with conn() as c:
            if db.get_card(c, card_id) is None or db.get_item(c, body.item_id) is None:
                raise HTTPException(404, "Kart veya kayıt yok")
            db.add_card_item(c, card_id, body.item_id)  # zaten ekliyse sessizce geçer
            return db.get_card(c, card_id)

    @app.patch("/api/cards/{card_id}/items/{item_id}")
    def patch_card_item(card_id: int, item_id: int, body: CardItemPatch):
        with conn() as c:
            card = db.get_card(c, card_id)
            if card is None or item_id not in [i["id"] for i in card["items"]]:
                raise HTTPException(404, "Kartta böyle bir video yok")
            if body.note is not None:
                db.set_card_item_note(c, card_id, item_id, body.note)
            if body.move is not None and not db.move_card_item(c, card_id, item_id, body.move):
                raise HTTPException(400, "Geçersiz yön")
            return db.get_card(c, card_id)

    @app.delete("/api/cards/{card_id}/items/{item_id}")
    def remove_card_item(card_id: int, item_id: int):
        with conn() as c:
            if not db.remove_card_item(c, card_id, item_id):
                raise HTTPException(404, "Kartta böyle bir video yok")
            return db.get_card(c, card_id)

    @app.get("/api/cards/{card_id}/copy", response_class=PlainTextResponse)
    def copy_card(card_id: int):
        with conn() as c:
            card = db.get_card(c, card_id)
        if card is None:
            raise HTTPException(404, "Kart yok")
        return format_card(card)

    # ---- Genel notlar (todo) ----
    @app.get("/api/todos")
    def todos():
        with conn() as c:
            return db.list_todos(c)

    @app.post("/api/todos", status_code=201)
    def todo_add(body: TodoCreate):
        with conn() as c:
            return db.add_todo(c, body.text)

    @app.post("/api/todos/clear-done")
    def todo_clear_done():
        with conn() as c:
            return {"removed": db.clear_done_todos(c)}

    @app.patch("/api/todos/{todo_id}")
    def todo_patch(todo_id: int, body: TodoPatch):
        with conn() as c:
            row = db.update_todo(c, todo_id, text=body.text, done=body.done)
        if row is None:
            raise HTTPException(404, "Not yok")
        return row

    @app.delete("/api/todos/{todo_id}")
    def todo_delete(todo_id: int):
        with conn() as c:
            if not db.delete_todo(c, todo_id):
                raise HTTPException(404, "Not yok")
        return {"ok": True}

    # ---- Analiz: marka > hesap > gönderi ----
    @app.get("/api/analytics")
    def analytics_overview():
        with conn() as c:
            return analytics.overview(c)

    @app.post("/api/analytics/accounts", status_code=201)
    def account_add(body: AccountAdd):
        with conn() as c:
            try:
                analytics.add_account(c, body.brand, body.platform, body.handle)
            except analytics.AnalyticsError as e:
                raise HTTPException(e.status, str(e))
            return analytics.overview(c)

    def an_call(fn, *args):
        try:
            return fn(*args)
        except analytics.AnalyticsError as e:
            raise HTTPException(e.status, str(e))

    @app.post("/api/analytics/brands", status_code=201)
    def brand_add(body: BrandBody):
        with conn() as c:
            an_call(analytics.add_brand, c, body.name)
            return analytics.overview(c)

    @app.patch("/api/analytics/brands/{brand_id}")
    def brand_rename(brand_id: int, body: BrandBody):
        with conn() as c:
            an_call(analytics.rename_brand, c, brand_id, body.name)
            return analytics.overview(c)

    @app.delete("/api/analytics/brands/{brand_id}")
    def brand_delete(brand_id: int):
        with conn() as c:
            an_call(analytics.delete_brand, c, brand_id)
            return analytics.overview(c)

    @app.post("/api/analytics/brands/{brand_id}/plan", status_code=201)
    def brand_plan_add(brand_id: int, body: PlanBulk):
        """Toplu içerik planı: her satır 'Başlık | 2026-11-03 | youtube' -> iş panosunda bu marka için iş."""
        with conn() as c:
            row = c.execute("SELECT name FROM brands WHERE id = ?", (brand_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Marka yok")
            items = planning.parse_lines(body.text, body.platform)
            if not items:
                raise HTTPException(400, "En az bir satır yaz: Başlık | tarih | platform")
            for it in items:
                board_call(board.add_task, c, it["title"], brand=row["name"], platform=it["platform"], due=it["due"])
            return analytics.overview(c)

    @app.patch("/api/analytics/accounts/{account_id}")
    def account_move(account_id: int, body: AccountMove):
        with conn() as c:
            an_call(analytics.move_account, c, account_id, body.brand_id)
            return analytics.overview(c)

    @app.delete("/api/analytics/accounts/{account_id}")
    def account_delete(account_id: int):
        with conn() as c:
            if not analytics.delete_account(c, account_id):
                raise HTTPException(404, "Hesap yok")
        return {"ok": True}

    @app.post("/api/analytics/accounts/{account_id}/sync")
    def account_sync(account_id: int):
        if syncer is None:
            raise HTTPException(503, "Veri çekme kapalı")
        if not syncer.start(account_id):
            raise HTTPException(409, "Hesap yok veya zaten eşitleniyor")
        return {"ok": True}

    @app.post("/api/analytics/accounts/{account_id}/posts", status_code=201)
    def account_post_add(account_id: int, body: PostUrl):
        """Profil listesi alınamayan hesaplar için: tek video linkinden metrikleri çek."""
        url = body.url.strip()
        with conn() as c:
            acc = c.execute("SELECT platform FROM accounts WHERE id = ?", (account_id,)).fetchone()
            if acc is None:
                raise HTTPException(404, "Hesap yok")
            if not analytics.url_matches_platform(url, acc["platform"]):
                raise HTTPException(400, f"Link {acc['platform']} adresi olmalı (https://…)")
            try:
                extract = syncer.extract if syncer and syncer.extract else (
                    lambda u, n: analytics.ytdlp_extract(u, n, config.cookies_file))
                analytics.save_info(c, account_id, extract(url, 1))
            except analytics.AnalyticsError as e:
                raise HTTPException(e.status, str(e))
            except Exception as e:
                raise HTTPException(502, f"Video bilgisi alınamadı: {str(e)[:200]}")
            return analytics.overview(c)

    # ---- İş panosu (kullanıcı <-> Claude) ve 2 haftalık dönemler ----
    def board_call(fn, *args, **kw):
        try:
            return fn(*args, **kw)
        except board.BoardError as e:
            raise HTTPException(e.status, str(e))

    @app.get("/api/board")
    def board_overview():
        with conn() as c:
            return board.overview(c)

    @app.post("/api/board/tasks", status_code=201)
    def task_add(body: TaskAdd):
        with conn() as c:
            board_call(board.add_task, c, body.title, brand=body.brand, platform=body.platform,
                       due=body.due, note=body.note)
            return board.overview(c)

    @app.patch("/api/board/tasks/{task_id}")
    def task_patch(task_id: int, body: TaskPatch):
        with conn() as c:
            if not board_call(board.update_task, c, task_id, status=body.status, title=body.title,
                              note=body.note, due=body.due):
                raise HTTPException(404, "İş yok")
            return board.overview(c)

    @app.delete("/api/board/tasks/{task_id}")
    def task_delete(task_id: int):
        with conn() as c:
            if not board.delete_task(c, task_id):
                raise HTTPException(404, "İş yok")
            return board.overview(c)

    @app.post("/api/board/messages", status_code=201)
    def message_add(body: MessageAdd):
        if body.author not in ("sen", "claude"):
            raise HTTPException(400, "Yazar sen veya claude olmalı")
        with conn() as c:
            board_call(board.add_message, c, body.author, body.text)
            return board.overview(c)

    @app.post("/api/board/batches", status_code=201)
    def batch_add(body: BatchAdd):
        with conn() as c:
            board_call(board.add_batch, c, body.title, body.start)
            return board.overview(c)

    @app.delete("/api/board/batches/{batch_id}")
    def batch_delete(batch_id: int):
        with conn() as c:
            if not board.delete_batch(c, batch_id):
                raise HTTPException(404, "Dönem yok")
            return board.overview(c)

    # ---- Video inceleme (zaman damgalı not + revizyon talebi) ----
    def review_call(fn, *args, **kw):
        try:
            return fn(*args, **kw)
        except review.ReviewError as e:
            raise HTTPException(e.status, str(e))

    @app.get("/api/review/videos")
    def review_list():
        with conn() as c:
            return review.list_videos(c)

    @app.get("/api/review/videos/{video_id}")
    def review_get(video_id: int):
        with conn() as c:
            return review_call(review.get_video, c, video_id)

    @app.get("/api/review/media/{version_id}")
    def review_media(version_id: int, request: Request):
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Başka siteden gömülemez")
        # Yalnızca CLI ile kaydedilmiş sürümlerin dosyası; Range desteği oynatıcıda ileri/geri sarma için gerekli
        with conn() as c:
            path = review_call(review.media_path, c, version_id)
        if not Path(path).is_file():
            raise HTTPException(404, "Video dosyası bulunamadı (taşınmış veya silinmiş olabilir)")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.post("/api/review/notes", status_code=201)
    def review_note_add(body: NoteAdd):
        with conn() as c:
            review_call(review.add_note, c, body.version_id, body.t, body.text)
            vid = c.execute("SELECT video_id FROM rv_versions WHERE id = ?", (body.version_id,)).fetchone()["video_id"]
            return review.get_video(c, vid)

    @app.patch("/api/review/notes/{note_id}")
    def review_note_edit(note_id: int, body: NoteEdit):
        with conn() as c:
            review_call(review.edit_note, c, note_id, body.text)
            return {"ok": True}

    @app.delete("/api/review/notes/{note_id}")
    def review_note_delete(note_id: int):
        with conn() as c:
            review_call(review.delete_note, c, note_id)
            return {"ok": True}

    @app.post("/api/review/videos/{video_id}/revise")
    def review_revise(video_id: int):
        with conn() as c:
            prompt = review_call(review.request_revision, c, video_id)
            return {"prompt": prompt, "video": review.get_video(c, video_id)}

    @app.get("/api/review/videos/{video_id}/prompt", response_class=PlainTextResponse)
    def review_prompt(video_id: int):
        with conn() as c:
            review_call(review.get_video, c, video_id)
            return review.revision_prompt(c, video_id)

    @app.post("/api/review/videos/{video_id}/approve")
    def review_approve(video_id: int):
        with conn() as c:
            review_call(review.approve, c, video_id)
            return review.get_video(c, video_id)

    @app.delete("/api/review/videos/{video_id}")
    def review_delete(video_id: int):
        with conn() as c:
            paths = [r["path"] for r in c.execute("SELECT path FROM rv_versions WHERE video_id = ?", (video_id,))]
            if not review.delete_video(c, video_id):
                raise HTTPException(404, "Video yok")
        # Yalnızca sunucunun yüklediği (media_dir altındaki) dosyalar silinir; yerel yoldaki dosyaya dokunulmaz
        root = Path(config.media_dir).resolve()
        for p in paths:
            try:
                q = Path(p).resolve()
                if root in q.parents:
                    q.unlink(missing_ok=True)
            except OSError:
                pass
        return {"ok": True}

    # ---- Kanal > başlık > alt başlık ağacı ve temizleme ----
    def ch_call(fn, *args, **kw):
        try:
            return fn(*args, **kw)
        except channels.ChannelError as e:
            raise HTTPException(e.status, str(e))

    @app.get("/api/review/tree")
    def review_tree():
        with conn() as c:
            return review.tree(c)

    @app.post("/api/review/channels", status_code=201)
    def channel_add(body: NameBody):
        with conn() as c:
            ch_call(channels.add_channel, c, body.name)
            return review.tree(c)

    @app.patch("/api/review/channels/{channel_id}")
    def channel_rename(channel_id: int, body: NameBody):
        with conn() as c:
            ch_call(channels.rename_channel, c, channel_id, body.name)
            return review.tree(c)

    @app.delete("/api/review/channels/{channel_id}")
    def channel_delete(channel_id: int):
        with conn() as c:
            ch_call(channels.delete_channel, c, channel_id)
            return review.tree(c)

    @app.post("/api/review/channels/{channel_id}/cats", status_code=201)
    def cat_add_(channel_id: int, body: CatCreate):
        with conn() as c:
            ch_call(channels.add_cat, c, channel_id, body.name, body.parent_id, body.kind)
            return review.tree(c)

    @app.patch("/api/review/cats/{cat_id}")
    def cat_rename_(cat_id: int, body: NameBody):
        with conn() as c:
            ch_call(channels.rename_cat, c, cat_id, body.name)
            return review.tree(c)

    @app.delete("/api/review/cats/{cat_id}")
    def cat_delete_(cat_id: int):
        with conn() as c:
            ch_call(channels.delete_cat, c, cat_id)
            return review.tree(c)

    def patch_item_(c, table, item_id, body: ItemPatch2, fn, errcall):
        sent = body.model_fields_set
        if "channel_id" in sent or "cat_id" in sent:
            ch_call(channels.place, c, table, item_id, channel_id=body.channel_id, cat_id=body.cat_id,
                    set_channel="channel_id" in sent, set_cat="cat_id" in sent)
        if "title" in sent or "dismissed" in sent:
            errcall(fn, c, item_id, title=body.title, dismissed=body.dismissed)
        return review.tree(c)

    @app.patch("/api/review/videos/{video_id}")
    def review_video_patch(video_id: int, body: ItemPatch2):
        with conn() as c:
            return patch_item_(c, "rv_videos", video_id, body, review.patch_video, review_call)

    # ---- Metin inceleme ----
    def text_call(fn, *args, **kw):
        try:
            return fn(*args, **kw)
        except texts.TextError as e:
            raise HTTPException(e.status, str(e))

    @app.get("/api/review/docs/{doc_id}")
    def doc_get(doc_id: int):
        with conn() as c:
            return text_call(texts.get_doc, c, doc_id)

    @app.patch("/api/review/docs/{doc_id}")
    def doc_patch(doc_id: int, body: ItemPatch2):
        with conn() as c:
            return patch_item_(c, "rv_docs", doc_id, body, texts.patch_doc, text_call)

    @app.delete("/api/review/docs/{doc_id}")
    def doc_delete(doc_id: int):
        with conn() as c:
            text_call(texts.delete_doc, c, doc_id)
            return review.tree(c)

    @app.put("/api/review/docs/{doc_id}/content")
    def doc_content(doc_id: int, body: DocContent):
        with conn() as c:
            text_call(texts.save_content, c, doc_id, body.content, expected_updated_at=body.expected_updated_at)
            return texts.get_doc(c, doc_id)

    @app.post("/api/review/docs/{doc_id}/comments", status_code=201)
    def doc_comment_add(doc_id: int, body: CommentAdd):
        with conn() as c:
            text_call(texts.add_comment, c, doc_id, body.quote, body.text, line=body.line, occ=body.occ)
            return texts.get_doc(c, doc_id)

    @app.patch("/api/review/comments/{comment_id}")
    def doc_comment_edit(comment_id: int, body: CommentPatch):
        with conn() as c:
            text_call(texts.edit_comment, c, comment_id, body.text)
            return {"ok": True}

    @app.delete("/api/review/comments/{comment_id}")
    def doc_comment_delete(comment_id: int):
        with conn() as c:
            text_call(texts.delete_comment, c, comment_id)
            return {"ok": True}

    @app.post("/api/review/docs/{doc_id}/revise")
    def doc_revise(doc_id: int):
        with conn() as c:
            prompt = text_call(texts.request_revision, c, doc_id)
            return {"prompt": prompt, "doc": texts.get_doc(c, doc_id)}

    @app.get("/api/review/docs/{doc_id}/prompt", response_class=PlainTextResponse)
    def doc_prompt(doc_id: int):
        with conn() as c:
            text_call(texts.get_doc, c, doc_id)
            return texts.revision_prompt(c, doc_id)

    @app.post("/api/review/docs/{doc_id}/approve")
    def doc_approve(doc_id: int):
        with conn() as c:
            text_call(texts.approve, c, doc_id)
            return texts.get_doc(c, doc_id)

    # ---- Yayındaki sunucuya izle.py ile gönderme (token) ----
    media = Path(config.media_dir)

    def media_ref(ref: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]{2,5}", ref or ""):
            raise HTTPException(400, "Geçersiz dosya başvurusu")
        p = media / ref
        if not p.is_file():
            raise HTTPException(404, "Yüklenmiş dosya yok; önce yükle")
        return str(p)

    @app.put("/api/hub/upload")
    async def hub_upload(request: Request, filename: str):
        ext = Path(filename).suffix.lower()
        if ext not in review.VIDEO_EXT:
            raise HTTPException(400, "Desteklenen biçimler: " + ", ".join(sorted(review.VIDEO_EXT)))
        media.mkdir(parents=True, exist_ok=True)
        ref = f"{uuid.uuid4().hex}{ext}"
        tmp, size = media / (ref + ".part"), 0
        try:
            with open(tmp, "wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, "Dosya çok büyük")
                    f.write(chunk)
            os.replace(tmp, media / ref)
        finally:
            tmp.unlink(missing_ok=True)
        return {"ref": ref, "size": size}

    @app.post("/api/hub/videos", status_code=201)
    def hub_video(body: HubVideo):
        path = media_ref(body.ref)
        try:
            with conn() as c:
                vid, new = review_call(review.add_video, c, path, body.title, brand=body.brand, kind=body.kind,
                                       platform=body.platform, project_dir=body.project_dir, category=body.category)
        except HTTPException:
            Path(path).unlink(missing_ok=True)
            raise
        return {"id": vid}

    @app.post("/api/hub/videos/{video_id}/versions", status_code=201)
    def hub_version(video_id: int, body: HubVersion):
        path = media_ref(body.ref)
        try:
            with conn() as c:
                review_call(review.add_version, c, video_id, path)
        except HTTPException:
            Path(path).unlink(missing_ok=True)
            raise
        return {"ok": True}

    @app.post("/api/hub/docs", status_code=201)
    def hub_doc(body: HubDoc):
        with conn() as c:
            did, new = text_call(texts.add_doc, c, body.title, body.content, brand=body.brand,
                                 category=body.category, source_path=body.source_path)
            return {"id": did, "new": new}

    @app.post("/api/hub/docs/{doc_id}/update")
    def hub_doc_update(doc_id: int, body: HubUpdate):
        with conn() as c:
            text_call(texts.apply_update, c, doc_id, body.content, body.note, force=body.force)
            return {"ok": True}

    @app.post("/api/hub/docs/{doc_id}/synced")
    def hub_doc_synced(doc_id: int):
        with conn() as c:
            text_call(texts.get_doc, c, doc_id)
            texts.mark_synced(c, doc_id)
            return {"ok": True}

    @app.get("/api/hub/pending", response_class=PlainTextResponse)
    def hub_pending():
        with conn() as c:
            prompts = review.pending_prompts(c) + texts.pending_prompts(c)
            return "\n\n".join(prompts) if prompts else "Bekleyen revizyon yok."

    # ---- Kategori / alt başlık yönetimi ----
    def edit(fn, *args):
        if catalog is None:
            raise HTTPException(503, "Kategori düzenleme kapalı")
        try:
            fn(*args)
        except CatalogError as e:
            raise HTTPException(e.status, str(e))
        return state()

    @app.post("/api/catalog/category/add")
    def cat_add(b: CatAdd):
        return edit(catalog and catalog.add_category, b.name, b.first_sub)

    @app.post("/api/catalog/category/rename")
    def cat_rename(b: CatRename):
        return edit(catalog and catalog.rename_category, b.name, b.new_name)

    @app.post("/api/catalog/category/move")
    def cat_move(b: CatMove):
        return edit(catalog and catalog.move_category, b.name, b.direction)

    @app.post("/api/catalog/category/delete")
    def cat_delete(b: CatDelete):
        return edit(catalog and catalog.delete_category, b.name, b.move_to_category, b.move_to_sub)

    @app.post("/api/catalog/sub/add")
    def sub_add(b: SubAdd):
        return edit(catalog and catalog.add_sub, b.category, b.name)

    @app.post("/api/catalog/sub/rename")
    def sub_rename(b: SubRename):
        return edit(catalog and catalog.rename_sub, b.category, b.name, b.new_name)

    @app.post("/api/catalog/sub/move")
    def sub_move(b: SubMove):
        return edit(catalog and catalog.move_sub, b.category, b.name, b.direction)

    @app.post("/api/catalog/sub/delete")
    def sub_delete(b: SubDelete):
        return edit(catalog and catalog.delete_sub, b.category, b.name, b.move_to_sub)

    return app
