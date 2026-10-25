"""config.yaml ve categories.yaml okuma."""
from __future__ import annotations

import os

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    allowed_user_ids: list[int] = field(default_factory=list)
    auto_download: bool = False
    downloads_dir: str = "downloads"
    db_path: str = "kaydet.db"
    cookies_file: str = ""  # Instagram vb. giriş isteyen videolar için (cookies.txt)
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    allowed_hosts: list[str] = field(default_factory=list)  # web_host=0.0.0.0 iken erişilecek adlar
    media_dir: str = "media"  # yayındaki sunucuya yüklenen videolar (izle.py --sunucu)
    password: str = ""  # doluysa web arayüzü şifreyle açılır (yayın için zorunlu)
    api_token: str = ""  # izle.py'nin yayındaki sunucuya yazması için (Bearer)


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


def _as_port(value) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        raise ValueError(f"config.yaml: 'web_port' 1-65535 arası olmalı, bulunan: {value!r}")
    return port


def load_config(path: str | Path) -> Config:
    """config.yaml, sonra KAYDET_* ortam değişkenleri (yayın/Docker için) okunur; ortam değişkeni önceliklidir."""
    return apply_env(_load_file(path))


def apply_env(cfg: Config, env=None) -> Config:
    env = os.environ if env is None else env
    if env.get("KAYDET_DB"):
        cfg.db_path = env["KAYDET_DB"]
    if env.get("KAYDET_MEDIA_DIR"):
        cfg.media_dir = env["KAYDET_MEDIA_DIR"]
    if env.get("KAYDET_HOST"):
        cfg.web_host = env["KAYDET_HOST"]
    if env.get("KAYDET_PORT") or env.get("PORT"):
        try:
            cfg.web_port = _as_port(int(env.get("KAYDET_PORT") or env["PORT"]))
        except ValueError:
            raise ValueError("KAYDET_PORT/PORT sayı olmalı")
    if env.get("KAYDET_ALLOWED_HOSTS"):
        cfg.allowed_hosts = [h.strip() for h in env["KAYDET_ALLOWED_HOSTS"].split(",") if h.strip()]
    if env.get("KAYDET_PASSWORD"):
        cfg.password = env["KAYDET_PASSWORD"]
    if env.get("KAYDET_TOKEN"):
        cfg.api_token = env["KAYDET_TOKEN"]
    return cfg


def _load_file(path: str | Path) -> Config:
    p = Path(path)
    if not p.exists():
        return Config()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Config(
        allowed_user_ids=_as_int_list(data.get("allowed_user_ids"), "allowed_user_ids"),
        auto_download=_as_bool(data.get("auto_download", False), "auto_download"),
        downloads_dir=str(data.get("downloads_dir", "downloads")),
        db_path=str(data.get("db_path", "kaydet.db")),
        cookies_file=str(data.get("cookies_file") or ""),
        web_host=str(data.get("web_host", "127.0.0.1")),
        web_port=_as_port(data.get("web_port", 8000)),
        allowed_hosts=_as_list(data.get("allowed_hosts")),
        media_dir=str(data.get("media_dir", "media")),
        password=str(data.get("password") or ""),
        api_token=str(data.get("api_token") or ""),
    )
