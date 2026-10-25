"""Yayın için şifre girişi (çerez) ve izle.py için Bearer token. Şifre/token boşsa kimlik doğrulama kapalıdır (yerel kullanım)."""
from __future__ import annotations

import hashlib
import hmac
import time

COOKIE = "kaydet_session"
SESSION_DAYS = 30
MAX_FAILS, FAIL_WINDOW = 10, 300  # 5 dakikada 10 hatalı denemeden sonra giriş geçici kilitlenir

LOGIN_HTML = """<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Giriş</title><style>
:root{color-scheme:light dark;--bg:#F3F2F6;--ink:#17151F;--line:#DAD7E4;--accent:#3A33D1;--surface:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#121118;--ink:#F1EFF7;--line:#2E2C3B;--accent:#9A94FF;--surface:#1C1B25}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:16px system-ui,sans-serif}
form{width:min(340px,90vw);background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:24px;display:flex;flex-direction:column;gap:12px}
h1{margin:0;font-size:22px}input,button{font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:transparent;color:inherit}
button{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600;cursor:pointer}.err{color:#d33;font-size:14px;margin:0}
</style></head><body><form method="post" action="/login"><h1>Kaydet</h1><label for="p">Şifre</label>
<input id="p" name="password" type="password" autocomplete="current-password" autofocus required>__ERR__<button type="submit">Giriş</button></form></body></html>"""


def _sig(password: str, exp: int) -> str:
    return hmac.new(password.encode("utf-8"), f"kaydet-session-v1:{exp}".encode(), hashlib.sha256).hexdigest()


def make_cookie(password: str, now: float | None = None) -> str:
    exp = int((now or time.time()) + SESSION_DAYS * 86400)
    return f"{exp}.{_sig(password, exp)}"


def cookie_ok(password: str, value: str | None, now: float | None = None) -> bool:
    if not password or not value or "." not in value:
        return False
    exp_s, sig = value.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    return exp >= (now or time.time()) and hmac.compare_digest(sig.encode(), _sig(password, exp).encode())


def token_ok(token: str, header: str | None) -> bool:
    return bool(token) and bool(header) and header.startswith("Bearer ") and hmac.compare_digest(header[7:].strip().encode(), token.encode())


class FailLimiter:
    """Hatalı girişler istemci (IP) başına sınırlanır: bir saldırgan gerçek kullanıcıyı kilitleyemez."""

    def __init__(self) -> None:
        self.fails: dict[str, list[float]] = {}

    def blocked(self, key: str = "", now: float | None = None) -> bool:
        now = now or time.time()
        recent = [t for t in self.fails.get(key, []) if now - t < FAIL_WINDOW]
        if recent:
            self.fails[key] = recent
        else:
            self.fails.pop(key, None)
        return len(recent) >= MAX_FAILS

    def add(self, key: str = "", now: float | None = None) -> None:
        if len(self.fails) > 1000:  # bellek şişmesin
            self.fails.clear()
        self.fails.setdefault(key, []).append(now or time.time())
