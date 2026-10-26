"""izle.py komutları (Claude oturumlarından). Yerel veritabanına ya da, IZLE_SERVER verilmişse, yayındaki sunucuya yazar.

  python izle.py ekle <video> --baslik "..." --marka "Kanal" [--kategori "Başlık/Alt başlık"] [--format yatay|short]
                              [--platform youtube] [--proje <klasör>]
  python izle.py yeni-surum <video_id> <video>
  python izle.py metin-ekle <dosya.md> --baslik "..." --marka "Kanal" [--kategori "Başlık/Alt başlık"]
  python izle.py metin-guncelle <metin_id> <dosya.md> [--not "ne yaptın"] [--zorla]
  python izle.py metin-aktar <klasör> --marka "Kanal" [--haric klasor1,klasor2] [--derinlik 2]   # klasördeki .md/.txt dosyaları toplu ekler
  python izle.py metin-al <metin_id> [--cikti <dosya>]      # arayüzde düzenlenen güncel metni dosyaya yazar
  python izle.py bekleyen                                   # "Değişikliğe başla" denmiş video ve metinler
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import review, texts


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python izle.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ekle"); a.add_argument("dosya"); a.add_argument("--baslik", required=True)
    a.add_argument("--marka", default=""); a.add_argument("--kategori", default="")
    a.add_argument("--format", dest="kind", default="yatay", choices=review.KINDS)
    a.add_argument("--platform", default=""); a.add_argument("--proje", default="")
    s = sub.add_parser("yeni-surum"); s.add_argument("id", type=int); s.add_argument("dosya")
    m = sub.add_parser("metin-ekle"); m.add_argument("dosya"); m.add_argument("--baslik", required=True)
    m.add_argument("--marka", default=""); m.add_argument("--kategori", default="")
    g = sub.add_parser("metin-guncelle"); g.add_argument("id", type=int); g.add_argument("dosya"); g.add_argument("--not", dest="note", default=""); g.add_argument("--zorla", action="store_true")
    ak = sub.add_parser("metin-aktar"); ak.add_argument("klasor"); ak.add_argument("--marka", required=True)
    ak.add_argument("--haric", default=""); ak.add_argument("--derinlik", type=int, default=2, choices=(0, 1, 2))
    al = sub.add_parser("metin-al"); al.add_argument("id", type=int); al.add_argument("--cikti", default="")
    sub.add_parser("bekleyen")
    return ap


SKIP_DIRS = {"veri", "node_modules", "__pycache__", "out", "dist", "venv"}


def collect_docs(root: str, exclude: str = "", depth: int = 2) -> list[tuple[str, str, str]]:
    """(başlık, dosya yolu, kategori yolu): alt klasör adları başlık/alt başlık olur (en çok 2 düzey)."""
    skip = {x.strip().lower() for x in exclude.split(",") if x.strip()}
    base, out = Path(root), []
    for cur, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in SKIP_DIRS | skip)
        for f in sorted(files):
            p = Path(cur) / f
            if p.suffix.lower() not in (".md", ".txt") or p.stat().st_size > texts.MAX_DOC or p.stem.lower() in skip or f.lower() in skip:
                continue
            parts = p.relative_to(base).parts[:-1]
            out.append((p.stem.replace("-", " ").replace("_", " "), str(p.resolve()), "/".join(parts[:depth])))
    return out


def read_text(path: str) -> str:
    raw = Path(path).read_bytes()
    return raw.decode("utf-8-sig", errors="replace")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = Path(os.environ.get("IZLE_CWD") or ".")  # izle.py klasör değiştirmeden önceki çağıran klasör

    def abs_(p: str) -> str:
        q = Path(p).expanduser()
        return str(q if q.is_absolute() else (base / q).resolve())

    if os.environ.get("IZLE_SERVER"):
        from . import remote
        return remote.run(args, abs_)

    from . import db
    from .config import load_config
    cfg = load_config(abs_(os.environ["KAYDET_CONFIG"]) if os.environ.get("KAYDET_CONFIG") else "config.yaml")
    conn = db.connect(cfg.db_path)
    host = cfg.web_host if cfg.web_host not in ("0.0.0.0", "::", "") else "127.0.0.1"
    url = f"http://{host}:{cfg.web_port}/#/izle"
    try:
        if args.cmd == "ekle":
            vid, new = review.add_video(conn, abs_(args.dosya), args.baslik, brand=args.marka, kind=args.kind,
                                        platform=args.platform, project_dir=abs_(args.proje) if args.proje else "",
                                        category=args.kategori)
            print(f"video {vid} {'eklendi' if new else 'zaten kayıtlı'}: {url}/{vid}")
        elif args.cmd == "yeni-surum":
            ver_id = review.add_version(conn, args.id, abs_(args.dosya))
            print("sürüm", conn.execute("SELECT n FROM rv_versions WHERE id = ?", (ver_id,)).fetchone()["n"], "kaydedildi")
        elif args.cmd == "metin-ekle":
            path = abs_(args.dosya)
            did, new = texts.add_doc(conn, args.baslik, read_text(path), brand=args.marka, category=args.kategori, source_path=path)
            print(f"metin {did} {'eklendi' if new else 'zaten kayıtlı'}: {url.replace('/izle', '/metin')}/m/{did}")
        elif args.cmd == "metin-aktar":
            items = collect_docs(abs_(args.klasor), args.haric, args.derinlik)
            new = sum(texts.add_doc(conn, t, read_text(p), brand=args.marka, category=c, source_path=p)[1] for t, p, c in items)
            print(f"{len(items)} dosya tarandı, {new} yeni metin eklendi: {url.replace('/izle', '/metin')}")
        elif args.cmd == "metin-guncelle":
            texts.apply_update(conn, args.id, read_text(abs_(args.dosya)), args.note, force=args.zorla)
            print("metin güncellendi; açık yorumlar uygulandı olarak işaretlendi")
        elif args.cmd == "metin-al":
            doc = texts.get_doc(conn, args.id)
            out = abs_(args.cikti) if args.cikti else doc["source_path"]
            if not out:
                print("Kaynak dosya yok: --cikti ver")
                return 1
            Path(out).write_text(doc["content"], encoding="utf-8", newline="")
            if not args.cikti or out == doc["source_path"]:
                texts.mark_synced(conn, args.id)
            print("yazıldı:", out)
            edits = texts.user_edits(doc)
            if edits:
                print("Kullanıcının sitede yaptığı değişiklikler:")
                print(chr(10).join(edits))
        else:
            prompts = review.pending_prompts(conn) + texts.pending_prompts(conn)
            print("\n\n".join(prompts) if prompts else "Bekleyen revizyon yok.")
    except (review.ReviewError, texts.TextError) as e:
        print(e)
        return 1
    finally:
        conn.close()
    return 0
