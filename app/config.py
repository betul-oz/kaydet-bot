"""config.yaml ve categories.yaml okuma."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    allowed_user_ids: list[int] = field(default_factory=list)
    auto_download: bool = False
    downloads_dir: str = "downloads"
    db_path: str = "kaydet.db"


def fold(text: str) -> str:
    """Eşleştirme için: Türkçe İ/I/ı -> i, küçük harf, '_' ve '-' boşluk, fazla boşluk tek."""
    t = text.translate(str.maketrans({"İ": "i", "I": "i", "ı": "i"})).lower()
    return " ".join(t.replace("_", " ").replace("-", " ").split())


@dataclass
class Sub:
    name: str
    aliases: list[str] = field(default_factory=list)

    def matches(self, text: str) -> bool:
        t = fold(text)
        return t == fold(self.name) or t in (fold(a) for a in self.aliases)


@dataclass
class Category:
    name: str
    aliases: list[str] = field(default_factory=list)
    subs: list[Sub] = field(default_factory=list)

    def matches(self, text: str) -> bool:
        t = fold(text)
        return t == fold(self.name) or t in (fold(a) for a in self.aliases)

    def find_sub(self, text: str) -> Sub | None:
        return next((s for s in self.subs if s.matches(text)), None)


@dataclass
class Categories:
    items: list[Category] = field(default_factory=list)

    def find(self, text: str) -> Category | None:
        return next((c for c in self.items if c.matches(text)), None)

    def resolve(self, cat_text: str, sub_text: str) -> tuple[str, str] | None:
        """Kategori ve alt başlık yazısını (ad veya takma ad) gerçek adlara çevirir."""
        cat = self.find(cat_text)
        if cat is None:
            return None
        sub = cat.find_sub(sub_text)
        if sub is None:
            return None
        return cat.name, sub.name


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _parse_sub(raw) -> Sub:
    if isinstance(raw, str):
        return Sub(name=raw)
    if isinstance(raw, dict) and raw.get("name"):
        return Sub(name=str(raw["name"]), aliases=_as_list(raw.get("aliases")))
    raise ValueError(f"Geçersiz alt başlık tanımı: {raw!r}")


def parse_categories(data: dict) -> Categories:
    raw_cats = (data or {}).get("categories")
    if not raw_cats:
        raise ValueError("categories.yaml içinde 'categories' listesi boş veya yok")
    cats: list[Category] = []
    for raw in raw_cats:
        if isinstance(raw, str):
            cats.append(Category(name=raw))
            continue
        if not isinstance(raw, dict) or not raw.get("name"):
            raise ValueError(f"Geçersiz kategori tanımı: {raw!r}")
        cats.append(
            Category(
                name=str(raw["name"]),
                aliases=_as_list(raw.get("aliases")),
                subs=[_parse_sub(s) for s in (raw.get("subcategories") or [])],
            )
        )
    _validate(cats)
    return Categories(items=cats)


def _validate(cats: list[Category]) -> None:
    seen: set[str] = set()
    for c in cats:
        if not c.subs:
            raise ValueError(f"'{c.name}' kategorisinin alt başlığı yok; en az bir alt başlık ekle")
        keys = [fold(c.name), *(fold(a) for a in c.aliases)]
        if seen & set(keys) or len(set(keys)) != len(keys):
            raise ValueError(f"'{c.name}' adı veya takma adı başka bir kategoriyle çakışıyor")
        seen |= set(keys)
        sub_seen: set[str] = set()
        for s in c.subs:
            sk = [fold(s.name), *(fold(a) for a in s.aliases)]
            if sub_seen & set(sk) or len(set(sk)) != len(sk):
                raise ValueError(f"'{c.name}' içinde '{s.name}' adı veya takma adı çakışıyor")
            sub_seen |= set(sk)


def load_categories(path: str | Path) -> Categories:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} bulunamadı. categories.example.yaml dosyasını kopyalayıp düzenle."
        )
    return parse_categories(yaml.safe_load(p.read_text(encoding="utf-8")))


def _as_bool(value, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ValueError(f"config.yaml: '{field_name}' true veya false olmalı, bulunan: {value!r}")


def _as_int_list(value, field_name: str) -> list[int]:
    try:
        return [int(i) for i in value or []]
    except (TypeError, ValueError):
        raise ValueError(f"config.yaml: '{field_name}' sayı listesi olmalı, bulunan: {value!r}")


def load_config(path: str | Path) -> Config:
    p = Path(path)
    if not p.exists():
        return Config()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Config(
        allowed_user_ids=_as_int_list(data.get("allowed_user_ids"), "allowed_user_ids"),
        auto_download=_as_bool(data.get("auto_download", False), "auto_download"),
        downloads_dir=str(data.get("downloads_dir", "downloads")),
        db_path=str(data.get("db_path", "kaydet.db")),
    )
