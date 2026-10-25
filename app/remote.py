"""izle.py'nin yayındaki sunucu modu: IZLE_SERVER=https://alan-adi IZLE_TOKEN=... ile videolar ve metinler
yerel veritabanı yerine sunucuya gönderilir; revizyon notları sunucudan okunur."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TIMEOUT = 600


def _server() -> str:
    url = os.environ["IZLE_SERVER"].rstrip("/")
    host = urllib.parse.urlparse(url).hostname or ""
    if not url.startswith("https://") and host not in ("localhost", "127.0.0.1", "::1"):
        raise OSError("IZLE_SERVER https:// ile başlamalı (token açık metin gitmesin)")
    return url


def _headers(extra: dict | None = None) -> dict:
    h = {"Authorization": "Bearer " + os.environ.get("IZLE_TOKEN", "")}
    h.update(extra or {})
    return h


def _call(method: str, path: str, body=None, raw: bool = False):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(_server() + path, data=data, method=method,
                                 headers=_headers({"Content-Type": "application/json"} if body is not None else {}))
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        out = r.read().decode("utf-8")
    return out if raw else json.loads(out)


def upload(path: str) -> str:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Dosya yok: {p}")
    with open(p, "rb") as f:
        req = urllib.request.Request(_server() + "/api/hub/upload?filename=" + urllib.parse.quote(p.name), data=f, method="PUT",
                                     headers=_headers({"Content-Length": str(p.stat().st_size), "Content-Type": "application/octet-stream"}))
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))["ref"]


def run(args, abs_) -> int:
    from .izle_cli import read_text
    try:
        if args.cmd == "ekle":
            ref = upload(abs_(args.dosya))
            r = _call("POST", "/api/hub/videos", {"ref": ref, "title": args.baslik, "brand": args.marka, "category": args.kategori,
                                                 "kind": args.kind, "platform": args.platform,
                                                 "project_dir": abs_(args.proje) if args.proje else ""})
            print(f"video {r['id']} eklendi: {_server()}/#/izle/{r['id']}")
        elif args.cmd == "yeni-surum":
            _call("POST", f"/api/hub/videos/{args.id}/versions", {"ref": upload(abs_(args.dosya))})
            print("yeni sürüm kaydedildi")
        elif args.cmd == "metin-ekle":
            path = abs_(args.dosya)
            r = _call("POST", "/api/hub/docs", {"title": args.baslik, "content": read_text(path), "brand": args.marka,
                                               "category": args.kategori, "source_path": path})
            print(f"metin {r['id']} {'eklendi' if r['new'] else 'zaten kayıtlı'}: {_server()}/#/metin/m/{r["id"]}")
        elif args.cmd == "metin-aktar":
            from .izle_cli import collect_docs
            items = collect_docs(abs_(args.klasor), args.haric, args.derinlik)
            new = 0
            for t, p, c in items:
                new += bool(_call("POST", "/api/hub/docs", {"title": t, "content": read_text(p), "brand": args.marka,
                                                           "category": c, "source_path": p})["new"])
            print(f"{len(items)} dosya tarandı, {new} yeni metin eklendi: {_server()}/#/metin")
        elif args.cmd == "metin-guncelle":
            _call("POST", f"/api/hub/docs/{args.id}/update", {"content": read_text(abs_(args.dosya)), "note": args.note, "force": args.zorla})
            print("metin güncellendi; açık yorumlar uygulandı olarak işaretlendi")
        elif args.cmd == "metin-al":
            doc = _call("GET", f"/api/review/docs/{args.id}")
            out = abs_(args.cikti) if args.cikti else doc["source_path"]
            if not out:
                print("Kaynak dosya yok: --cikti ver")
                return 1
            Path(out).write_text(doc["content"], encoding="utf-8", newline="")
            if not args.cikti or out == doc["source_path"]:
                _call("POST", f"/api/hub/docs/{args.id}/synced", {})
            print("yazıldı:", out)
        else:
            print(_call("GET", "/api/hub/pending", raw=True))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", "")
        except Exception:
            detail = ""
        print(f"Sunucu hatası {e.code}: {detail or e.reason}" + (" (IZLE_TOKEN yanlış olabilir)" if e.code == 401 else ""))
        return 1
    except (urllib.error.URLError, FileNotFoundError, OSError) as e:
        print(f"Sunucuya ulaşılamadı: {e}")
        return 1
    return 0
