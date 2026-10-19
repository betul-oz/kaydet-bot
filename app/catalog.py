"""Kategori/alt başlık düzenleme: bellekteki Categories + categories.yaml + items tablosu birlikte güncellenir.

Her işlem tek kilit ve tek SQLite yazma işlemi (BEGIN IMMEDIATE) içinde yapılır: arama, sayım,
bellek değişikliği, DB güncellemesi ve yaml yazımı birlikte başarılı olur ya da birlikte geri alınır.
"""
from __future__ import annotations

import copy
import os
import threading
import unicodedata
from pathlib import Path

import yaml

from . import db
from .config import Categories, Category, Sub, _validate, fold

MAX_NAME = 40
FORBIDDEN = set("/|\\<>")


class CatalogError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def to_data(cats: Categories) -> dict:
    out = []
    for c in cats.items:
        subs = []
        for s in c.subs:
            subs.append({"name": s.name, "aliases": s.aliases} if s.aliases else s.name)
        entry: dict = {"name": c.name}
        if c.aliases:
            entry["aliases"] = c.aliases
        entry["subcategories"] = subs
        out.append(entry)
    return {"categories": out}


def yaml_text(cats: Categories) -> str:
    return ("# Kategoriler. Web sayfasından düzenlenebilir; elle de düzenleyebilirsin.\n"
            "# Not: web sayfasından yapılan her değişiklikte dosya yeniden yazılır, yorumların silinir.\n"
            + yaml.safe_dump(to_data(cats), allow_unicode=True, sort_keys=False))


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # yarım yazılmış dosya kalmasın


def save_yaml(cats: Categories, path: str | Path) -> None:
    _write(Path(path), yaml_text(cats))


def _clean(raw: str, what: str) -> str:
    name = " ".join((raw or "").split())
    if not name:
        raise CatalogError(f"{what} boş olamaz")
    if len(name) > MAX_NAME:
        raise CatalogError(f"{what} en fazla {MAX_NAME} karakter olabilir")
    if any(ch in FORBIDDEN for ch in name):
        raise CatalogError(f"{what} içinde / | \\ < > karakterleri kullanılamaz")
    if any(unicodedata.category(ch) in ("Cc", "Cf") for ch in name):  # görünmez/yön değiştiren karakterler
        raise CatalogError(f"{what} içinde görünmez veya yön değiştiren karakter olamaz")
    return name


class Catalog:
    def __init__(self, categories: Categories, path: str | Path, db_path: str):
        self.cats = categories
        self.path = Path(path)
        self.db_path = db_path
        self._lock = threading.RLock()

    # ---- bellek içi arama (kilit altında çağrılır) ----
    def _cat(self, name: str) -> Category:
        c = next((c for c in self.cats.items if fold(c.name) == fold(name)), None)
        if c is None:
            raise CatalogError("Kategori bulunamadı", 404)
        return c

    def _sub(self, cat: Category, name: str) -> Sub:
        s = next((s for s in cat.subs if fold(s.name) == fold(name)), None)
        if s is None:
            raise CatalogError("Alt başlık bulunamadı", 404)
        return s

    @staticmethod
    def _ids(conn, cat: str, sub: str | None = None) -> list[int]:
        """Harf farkını (Diy/diy, İ/i) yok sayarak bir kategorideki/başlıktaki video id'leri."""
        fc, fs = fold(cat), None if sub is None else fold(sub)
        return [r["id"] for r in conn.execute("SELECT id, category, subcategory FROM items")
                if fold(r["category"]) == fc and (fs is None or fold(r["subcategory"]) == fs)]

    # ---- ortak işlem çerçevesi ----
    def _tx(self, op):
        """op(conn) kilit + yazma işlemi içinde çalışır. Hata olursa bellek, DB ve yaml eski haline döner."""
        with self._lock:
            snapshot = copy.deepcopy(self.cats.items)
            old_yaml = self.path.read_text(encoding="utf-8") if self.path.exists() else None
            conn = db.connect(self.db_path)
            conn.isolation_level = None  # elle BEGIN/COMMIT
            yaml_written = False
            try:
                conn.execute("BEGIN IMMEDIATE")  # bot yazmaları commit'e kadar bekler (sayım ile silme arasına video giremez)
                op(conn)
                try:
                    _validate(self.cats.items)
                except ValueError as e:
                    raise CatalogError(str(e)) from e
                save_yaml(self.cats, self.path)
                yaml_written = True
                conn.execute("COMMIT")
            except BaseException:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                self.cats.items[:] = snapshot
                if yaml_written and old_yaml is not None:
                    _write(self.path, old_yaml)  # commit patlarsa yaml da eski haline dönsün
                raise
            finally:
                conn.close()
            return to_data(self.cats)

    def reconcile(self) -> int:
        """Açılışta: adı yalnızca harf farkıyla tutmayan videoları yapılandırmadaki yazıma çeker."""
        fixed = 0
        with self._lock:
            conn = db.connect(self.db_path)
            try:
                known = {(c.name, s.name) for c in self.cats.items for s in c.subs}
                for r in conn.execute("SELECT id, category, subcategory FROM items").fetchall():
                    if (r["category"], r["subcategory"]) in known:
                        continue
                    hit = next(((c.name, s.name) for c in self.cats.items for s in c.subs
                                if fold(c.name) == fold(r["category"]) and fold(s.name) == fold(r["subcategory"])), None)
                    if hit:
                        conn.execute("UPDATE items SET category = ?, subcategory = ? WHERE id = ?", (*hit, r["id"]))
                        fixed += 1
                conn.commit()
            finally:
                conn.close()
        return fixed

    # ---- kategori ----
    def add_category(self, name: str, first_sub: str) -> dict:
        name, first_sub = _clean(name, "Kategori adı"), _clean(first_sub, "Alt başlık adı")
        return self._tx(lambda conn: self.cats.items.append(Category(name=name, subs=[Sub(name=first_sub)])))

    def rename_category(self, name: str, new_name: str) -> dict:
        new_name = _clean(new_name, "Kategori adı")

        def op(conn):
            cat = self._cat(name)
            ids = self._ids(conn, cat.name)
            cat.name = new_name
            conn.executemany("UPDATE items SET category = ? WHERE id = ?", [(new_name, i) for i in ids])
        return self._tx(op)

    def move_category(self, name: str, direction: int) -> dict:
        def op(conn):
            cat = self._cat(name)
            i = self.cats.items.index(cat)
            j = i + (-1 if direction < 0 else 1)
            if 0 <= j < len(self.cats.items):
                self.cats.items[i], self.cats.items[j] = self.cats.items[j], self.cats.items[i]
        return self._tx(op)

    def delete_category(self, name: str, move_to_category: str = "", move_to_sub: str = "") -> dict:
        def op(conn):
            cat = self._cat(name)
            if len(self.cats.items) <= 1:
                raise CatalogError("Son kategori silinemez", 409)
            ids = self._ids(conn, cat.name)
            if ids:
                if not move_to_category:
                    raise CatalogError(f"Bu kategoride {len(ids)} video var; taşınacak yeri seç", 409)
                dest = self._cat(move_to_category)
                if dest is cat:
                    raise CatalogError("Videolar silinen kategoriye taşınamaz", 400)
                dsub = self._sub(dest, move_to_sub)
                conn.executemany("UPDATE items SET category = ?, subcategory = ? WHERE id = ?",
                                 [(dest.name, dsub.name, i) for i in ids])
            self.cats.items.remove(cat)
        return self._tx(op)

    # ---- alt başlık ----
    def add_sub(self, category: str, name: str) -> dict:
        name = _clean(name, "Alt başlık adı")
        return self._tx(lambda conn: self._cat(category).subs.append(Sub(name=name)))

    def rename_sub(self, category: str, name: str, new_name: str) -> dict:
        new_name = _clean(new_name, "Alt başlık adı")

        def op(conn):
            cat = self._cat(category)
            sub = self._sub(cat, name)
            ids = self._ids(conn, cat.name, sub.name)
            sub.name = new_name
            conn.executemany("UPDATE items SET subcategory = ? WHERE id = ?", [(new_name, i) for i in ids])
        return self._tx(op)

    def move_sub(self, category: str, name: str, direction: int) -> dict:
        def op(conn):
            cat = self._cat(category)
            sub = self._sub(cat, name)
            i = cat.subs.index(sub)
            j = i + (-1 if direction < 0 else 1)
            if 0 <= j < len(cat.subs):
                cat.subs[i], cat.subs[j] = cat.subs[j], cat.subs[i]
        return self._tx(op)

    def delete_sub(self, category: str, name: str, move_to_sub: str = "") -> dict:
        def op(conn):
            cat = self._cat(category)
            sub = self._sub(cat, name)
            if len(cat.subs) <= 1:
                raise CatalogError("Bir kategoride en az bir alt başlık kalmalı", 409)
            ids = self._ids(conn, cat.name, sub.name)
            if ids:
                if not move_to_sub:
                    raise CatalogError(f"Bu başlıkta {len(ids)} video var; taşınacak yeri seç", 409)
                dest = self._sub(cat, move_to_sub)
                if dest is sub:
                    raise CatalogError("Videolar silinen başlığa taşınamaz", 400)
                conn.executemany("UPDATE items SET subcategory = ? WHERE id = ?", [(dest.name, i) for i in ids])
            cat.subs.remove(sub)
        return self._tx(op)
