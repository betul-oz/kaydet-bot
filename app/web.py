"""Web arayüzü ve JSON API (FastAPI). Varsayılan olarak yalnızca bu bilgisayardan erişilir."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from typing import Annotated
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from . import analytics, board, db, review
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
            if not review.delete_video(c, video_id):
                raise HTTPException(404, "Video yok")
            return {"ok": True}

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
