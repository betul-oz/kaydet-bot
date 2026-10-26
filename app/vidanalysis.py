"""Video içi analiz (yerel, ücretsiz, yalnızca ffmpeg/ffprobe): hook, ritim, ses, enerji zaman çizgisi ve Türkçe brief.

Ne ölçer: görsel değişim (sahne skoru, saniyede 4 örnek), kesmeler, sessizlik, ses seviyesi (LUFS), saniye bazlı 'enerji'.
Ne ölçmez: izleyicinin gerçekte nerede bıraktığı (tutma eğrisi) yalnızca platform paneli/API'sinde olur. Brief'ler bu yüzden
'otomatik tahmin'dir: durağan açılış, ölü hava, enerjisi düşen bölüm gibi bilinen terk nedenlerini işaretler.
Konuşma metni (Whisper) ve yüz/ekran yazısı ilk sürümde yok; derin yorum için istem Claude oturumuna verilir.
"""
from __future__ import annotations

import json
import math
import queue
import re
import shutil
import sqlite3
import statistics
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

SCENE_FPS = 4
CUT_T = 0.30             # sahne skoru bunun üstündeyse kesme sayılır
HOOK_SEC = 3
LOW_E = 0.22             # bu enerjinin altı 'durağan/ölü' sayılır
LOW_MIN_SEC = 5          # en az bu kadar süren düşük enerji bölümü sorun sayılır
LUFS_LO, LUFS_HI = -17.0, -11.0
TARGET_LUFS = -14
SILENCE_DB = "-35dB"
MAX_SECONDS = 20 * 60    # bundan uzun video analiz edilmez (süre/kaynak koruması)

SCHEMA = """
CREATE TABLE IF NOT EXISTS video_analysis (
    key TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class AnalysisError(Exception):
    pass


def _ffmpeg(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise AnalysisError("ffmpeg bulunamadı (kurulu ve PATH'te olmalı)")
    return subprocess.run([exe, "-hide_banner", *args], capture_output=True, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def probe(path: str) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        raise AnalysisError("ffprobe bulunamadı (ffmpeg ile birlikte kurulur)")
    r = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
                        path], capture_output=True, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode != 0:
        raise AnalysisError("Video okunamadı: " + (r.stderr.strip().splitlines() or ["bozuk dosya"])[-1][:150])
    d = json.loads(r.stdout or "{}")
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise AnalysisError("Dosyada video akışı yok")
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    fps = round(float(num) / float(den or 1), 2) if float(den or 1) else None
    return {"duration": round(float(d.get("format", {}).get("duration") or 0), 2), "width": v.get("width"), "height": v.get("height"),
            "fps": fps, "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


_PTS = re.compile(r"pts_time:([\d.]+)")
_SCORE = re.compile(r"lavfi\.scene_score=([\d.]+)")


def parse_scene(out: str) -> list[tuple[float, float]]:
    res, t = [], None
    for line in out.splitlines():
        m = _PTS.search(line)
        if m:
            t = float(m.group(1))
            continue
        m = _SCORE.search(line)
        if m and t is not None:
            res.append((t, float(m.group(1))))
            t = None
    return res


_M = re.compile(r"\bt:\s*([\d.]+)\s.*?\bM:\s*(-?[\d.]+|-?inf|nan)")
_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*([\d.]+)")
_INTEGRATED = re.compile(r"Summary:.*?I:\s*(-?[\d.]+)\s*LUFS", re.S)


def parse_audio(err: str, duration: float) -> dict:
    loud: list[tuple[float, float]] = []
    for line in err.splitlines():
        m = _M.search(line)
        if m:
            try:
                v = float(m.group(2))
            except ValueError:
                continue
            if v > -70:  # -120 ve altı = sessizlik/ölçüm başlangıcı
                loud.append((float(m.group(1)), v))
    sil: list[list[float]] = []
    for line in err.splitlines():
        m = _SIL_START.search(line)
        if m:
            sil.append([max(float(m.group(1)), 0.0), duration])
            continue
        m = _SIL_END.search(line)
        if m and sil and sil[-1][1] == duration:
            sil[-1][1] = float(m.group(1))
    m = _INTEGRATED.search(err)
    return {"loud": loud, "silences": [(a, min(b, duration)) for a, b in sil], "integrated": float(m.group(1)) if m else None}


def build_timeline(duration: float, scene: list[tuple[float, float]], audio: dict | None) -> dict:
    n = max(1, math.ceil(duration))
    motion, cuts, loud, sil = [[] for _ in range(n)], [0] * n, [[] for _ in range(n)], [0.0] * n
    cut_times = []
    for t, sc in scene:
        s = min(int(t), n - 1)
        if sc >= CUT_T:
            cuts[s] += 1
            cut_times.append(round(t, 2))
        else:
            motion[s].append(sc)
    has_audio = audio is not None
    if has_audio:
        for t, v in audio["loud"]:
            loud[min(int(t), n - 1)].append(v)
        for a, b in audio["silences"]:
            for s in range(int(a), min(math.ceil(b), n)):
                sil[s] += max(0.0, min(b, s + 1) - max(a, s))
    mot = [statistics.fmean(x) if x else 0.0 for x in motion]
    nz = sorted(x for x in mot if x > 0)
    mot_ref = max(nz[int(len(nz) * 0.8)] if nz else 0.0, 0.01)
    lo = [statistics.fmean(x) if x else None for x in loud]
    energy = []
    for s in range(n):
        m = min(1.0, mot[s] / mot_ref)
        c = 1.0 if cuts[s] else 0.0
        if has_audio:
            lv = 0.0 if lo[s] is None else min(1.0, max(0.0, (lo[s] + 50) / 36))
            energy.append(round(0.45 * m + 0.35 * lv + 0.20 * c, 3))
        else:
            energy.append(round(0.7 * m + 0.3 * c, 3))
    return {"seconds": n, "motion": [round(x, 4) for x in mot], "cuts": cuts, "cut_times": cut_times,
            "loud": [None if x is None else round(x, 1) for x in lo], "silence": [round(min(x, 1.0), 2) for x in sil], "energy": energy}


def _runs(flags: list[bool], min_len: int) -> list[tuple[int, int]]:
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


def features_from(info: dict, tl: dict, audio: dict | None) -> dict:
    n, energy, cuts = tl["seconds"], tl["energy"], tl["cuts"]
    dur = info["duration"] or n
    cut_times = tl["cut_times"]
    first_cut = cut_times[0] if cut_times else None
    mot = tl["motion"]
    mot_all = statistics.fmean(mot) if mot else 0.0
    mot_hook = statistics.fmean(mot[:HOOK_SEC]) if mot[:HOOK_SEC] else 0.0
    lows = _runs([e < LOW_E and not cuts[i] for i, e in enumerate(energy)], LOW_MIN_SEC)
    shots = [b - a for a, b in zip([0.0] + cut_times, cut_times + [dur]) if b - a > 0.2]
    f = {"duration": dur, "width": info["width"], "height": info["height"], "fps": info["fps"], "has_audio": info["has_audio"],
         "cut_count": len(cut_times), "first_cut": first_cut, "avg_shot": round(statistics.fmean(shots), 2) if shots else None,
         "cuts_per_10s": round(len(cut_times) / dur * 10, 2) if dur else 0,
         "hook_motion_ratio": round(mot_hook / mot_all, 2) if mot_all else None,
         "low_zones": [{"start": a, "end": b} for a, b in lows],
         "low_seconds": sum(b - a for a, b in lows), "avg_energy": round(statistics.fmean(energy), 3) if energy else 0}
    if audio is not None:
        lo = [x for x in tl["loud"] if x is not None]
        silent = [s < 0.5 and x is not None and x > -45 for s, x in zip(tl["silence"], tl["loud"])]
        f.update(integrated_lufs=audio["integrated"], audio_start=next((i for i, a in enumerate(silent) if a), None),
                 loud_mean=round(statistics.fmean(lo), 1) if lo else None,
                 hook_loud=round(statistics.fmean([x for x in tl["loud"][:HOOK_SEC] if x is not None]), 1) if any(x is not None for x in tl["loud"][:HOOK_SEC]) else None,
                 silence_ratio=round(sum(tl["silence"]) / n, 2))
    tail = energy[-3:] if n >= 6 else []
    f["end_ratio"] = round(statistics.fmean(tail) / f["avg_energy"], 2) if tail and f["avg_energy"] else None
    return f


def _mmss(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def make_briefs(f: dict) -> list[dict]:
    """Kural tabanlı Türkçe brief: {section, level: sorun|dikkat|iyi, at: [bas, bit], text, fix}. Eşikler önerilerdir."""
    out: list[dict] = []

    def add(section, level, at, text, fix=""):
        out.append({"section": section, "level": level, "at": at, "text": text, "fix": fix})

    dur, long_video = f["duration"], f["duration"] > 180
    fc = f["first_cut"]
    # ---- hook ----
    if fc is None or fc > HOOK_SEC:
        if f.get("hook_motion_ratio") is not None and f["hook_motion_ratio"] < 0.7 or fc is None and f["cut_count"] == 0:
            add("hook", "sorun", [0, HOOK_SEC], f"İlk {HOOK_SEC} saniyede görsel hareket yok" + (f" (ilk kesme {fc:.1f} sn'de)." if fc else " (hiç kesme yok)."),
                "İlk karede sonucu ya da iddiayı göster; ilk 1-2 saniyede kesme, zoom veya hareket ekle.")
        else:
            add("hook", "dikkat", [0, HOOK_SEC], f"İlk kesme geç ({fc:.1f} sn).", "Açılıştaki ilk planı kısalt; ilk 2 saniye içinde görsel değişim koy.")
    elif fc > 2.0:
        add("hook", "dikkat", [0, HOOK_SEC], f"İlk kesme {fc:.1f} sn'de: açılış biraz yavaş.", "Hook'u ilk 2 saniyeye sıkıştır.")
    else:
        add("hook", "iyi", [0, HOOK_SEC], "İlk 3 saniyede hareket/kesme var: açılış canlı.")
    if f["has_audio"]:
        a0 = f.get("audio_start")
        if a0 is None:
            add("hook", "sorun", [0, HOOK_SEC], "Videoda duyulur bir ses/konuşma yok.", "Anlatım, müzik veya ses efekti ekle.")
        elif a0 > 1.5:
            add("hook", "sorun", [0, a0 + 1], f"Ses/konuşma {a0} saniye sonra başlıyor: açılışta ölü hava var.", "İlk cümleyi başa al, açılıştaki boşluğu kes.")
        elif a0 > 0.5:
            add("hook", "dikkat", [0, a0 + 1], f"Ses {a0} saniye sonra başlıyor.", "Sesi ilk karede başlat (nefes boşluğunu kes).")
        if f.get("hook_loud") is not None and f.get("loud_mean") is not None and f["hook_loud"] <= f["loud_mean"] - 6:
            add("hook", "dikkat", [0, HOOK_SEC], f"Açılış sesi videonun geri kalanından belirgin kısık ({f['hook_loud']} LUFS, ortalama {f['loud_mean']}).",
                "Açılışı daha yüksek/net başlat; telefonda sessiz izleyenler kaydırır.")
    # ---- orta ----
    for z in f["low_zones"][:3]:
        d = z["end"] - z["start"]
        add("orta", "sorun" if d >= 7 else "dikkat", [z["start"], z["end"]],
            f"{_mmss(z['start'])}–{_mmss(z['end'])} arası enerji çok düşük ({d} sn): kesme, belirgin hareket ve ses yoğunluğu yok; izleyici burada sıkılabilir.",
            "Bu bölümü kısalt ya da araya B-roll, zoom, vurgu metni veya ses efekti ekle.")
    limit = 8 if long_video else 5
    if f["avg_shot"] and f["avg_shot"] > limit and f["cut_count"] > 0:
        add("ritim", "dikkat", [0, dur], f"Planlar uzun: ortalama {f['avg_shot']} sn ({f['cut_count']} kesme).", "Kesme sıklığını artır; kısa videoda 2-4 saniyede bir görsel değişim hedefle.")
    elif f["cut_count"] == 0 and dur > 8:
        add("ritim", "dikkat", [0, dur], "Hiç kesme tespit edilmedi (tek plan ya da yavaş geçişler).", "Plan değişimi ve ritim ekle.")
    elif f["cut_count"] and f["avg_shot"] and f["avg_shot"] <= limit:
        add("ritim", "iyi", [0, dur], f"Ritim iyi: ortalama plan {f['avg_shot']} sn.")
    # ---- ses ----
    if f["has_audio"]:
        if f.get("silence_ratio", 0) > 0.25:
            add("ses", "dikkat", [0, dur], f"Videonun %{int(f['silence_ratio'] * 100)}'i sessiz.", "Sessiz boşlukları kes ya da müzik/atmosfer sesi koy.")
        i = f.get("integrated_lufs")
        if i is not None and not (LUFS_LO <= i <= LUFS_HI):
            add("ses", "dikkat", [0, dur], f"Ses seviyesi hedef dışı ({i} LUFS).", f"Sosyal medya için yaklaşık {TARGET_LUFS} LUFS'a getir.")
    else:
        add("ses", "sorun", [0, dur], "Videoda ses yok.", "Anlatım ya da müzik ekle; sessiz izleyenler için altyazı koy.")
    # ---- bitiş ----
    if f.get("end_ratio") is not None and f["end_ratio"] < 0.5:
        add("bitis", "dikkat", [max(0, dur - 3), dur], "Son 3 saniyede enerji düşüyor: video sönerek bitiyor.", "Net bir kapanış cümlesi ya da çağrı (yorum, takip, sıradaki video) ekle, son karede hareket olsun.")
    return out


def scores(f: dict, briefs: list[dict]) -> dict:
    """Basit 0-100 göstergeler (brief'lerden türer; mutlak doğru değil, videoları kıyaslamak için)."""
    def pen(section):
        p = 0
        for b in briefs:
            if b["section"] == section:
                p += {"sorun": 35, "dikkat": 15, "iyi": 0}[b["level"]]
        return max(0, 100 - p)
    mid = max(0, 100 - int(f["low_seconds"] / f["duration"] * 200)) if f["duration"] else 100
    return {"hook": pen("hook"), "orta": min(mid, pen("orta")), "ritim": pen("ritim"), "ses": pen("ses"), "bitis": pen("bitis")}


def analyze_file(path: str) -> dict:
    info = probe(path)
    if info["duration"] > MAX_SECONDS:
        raise AnalysisError(f"Video çok uzun ({int(info['duration'] // 60)} dk); en çok {MAX_SECONDS // 60} dk analiz edilir")
    if info["duration"] <= 0:
        raise AnalysisError("Video süresi okunamadı")
    r = _ffmpeg("-v", "error", "-i", path, "-an", "-vf", f"fps={SCENE_FPS},scale=160:-2,select=gte(scene\\,0),metadata=print:key=lavfi.scene_score:file=-", "-f", "null", "-")
    scene = parse_scene(r.stdout + "\n" + r.stderr)
    if not scene:
        raise AnalysisError("Görüntü analiz edilemedi (desteklenmeyen biçim olabilir)")
    audio = None
    if info["has_audio"]:
        r2 = _ffmpeg("-v", "verbose", "-i", path, "-vn", "-af", f"ebur128=peak=true:framelog=verbose,silencedetect=n={SILENCE_DB}:d=0.4", "-f", "null", "-")
        audio = parse_audio(r2.stderr, info["duration"])
    tl = build_timeline(info["duration"], scene, audio)
    f = features_from(info, tl, audio)
    briefs = make_briefs(f)
    return {"features": f, "timeline": tl, "briefs": briefs, "scores": scores(f, briefs), "version": 1}


def claude_prompt(title: str, res: dict) -> str:
    """Derin yorum için Claude'a verilecek istem (API anahtarı yok: yorumu Claude oturumu yapar)."""
    f, b = res["features"], res["briefs"]
    lines = [f"Video analizi: “{title}”", f"Süre {f['duration']} sn, {f['width']}x{f['height']}, {f['cut_count']} kesme (ort. plan {f['avg_shot']} sn), "
             f"ilk kesme {f['first_cut']} sn, ses başlangıcı {f.get('audio_start')} sn, ses {f.get('integrated_lufs')} LUFS, sessizlik %{int((f.get('silence_ratio') or 0) * 100)}.",
             f"Göstergeler (0-100): " + ", ".join(f"{k} {v}" for k, v in res["scores"].items()), "", "Otomatik bulgular:"]
    for x in b:
        lines.append(f"- [{x['section']}/{x['level']}] {_mmss(x['at'][0])}–{_mmss(x['at'][1])}: {x['text']}" + (f" → {x['fix']}" if x["fix"] else ""))
    en = res["timeline"]["energy"]
    lines += ["", "Saniye bazlı enerji (0-1): " + " ".join(f"{e:.1f}" for e in en[:240]),
              "", "Yap: bu veriye ve videoya bakarak (varsa dosyayı/kareleri incele) şunları yaz: 1) hook neden zayıf/güçlü ve 3 alternatif açılış cümlesi/görseli, "
              "2) sıkıcılaşan bölümlerde ne kesilmeli ya da eklenmeli (zaman damgalı), 3) bir sonraki videoda denenecek tek somut değişiklik."]
    return "\n".join(lines)


# ---------------- arka plan çalıştırıcı + saklama ----------------

def get(conn: sqlite3.Connection, key: str) -> dict:
    r = conn.execute("SELECT * FROM video_analysis WHERE key = ?", (key,)).fetchone()
    if r is None:
        return {"key": key, "status": "none"}
    d = {"key": key, "status": r["status"], "error": r["error"], "updated_at": r["updated_at"]}
    if r["status"] == "done" and r["result"]:
        d["result"] = json.loads(r["result"])
    return d


def _set(conn: sqlite3.Connection, key: str, status: str, error: str = "", result: dict | None = None) -> None:
    conn.execute("INSERT INTO video_analysis (key, status, error, result) VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                 "status = excluded.status, error = excluded.error, result = excluded.result, updated_at = datetime('now')",
                 (key, status, error[:300], json.dumps(result) if result else ""))
    conn.commit()


def download_for_analysis(url: str, dest: str, cookies_file: str | None = None) -> str:
    """Herkese açık videoyu analiz için küçük çözünürlükte indirir (yt-dlp)."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True, "socket_timeout": 25, "outtmpl": str(Path(dest) / "v.%(ext)s"),
            "format": "bv*[height<=480]+ba/b[height<=480]/b", "merge_output_format": "mp4"}
    if cookies_file:
        opts["cookiefile"] = cookies_file
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([url])
    files = sorted(Path(dest).glob("v.*"))
    if not files:
        raise AnalysisError("Video indirilemedi")
    return str(files[0])


class Runner:
    """Tek iş parçacığıyla sırayla analiz eder. Anahtarlar: 'post:<id>' (herkese açık video) ya da 'rv:<sürüm id>' (kendi videomuz)."""

    def __init__(self, db_path: str, connect: Callable, cookies_file: str = "",
                 analyze: Callable[[str], dict] = analyze_file, fetch: Callable[[str, str], str] | None = None):
        self.db_path, self.connect, self.cookies = db_path, connect, cookies_file
        self.analyze = analyze
        self.fetch = fetch or (lambda url, dest: download_for_analysis(url, dest, self.cookies or None))
        self.q: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        c = connect(db_path)
        try:  # yeniden başlamada takılı kalan işleri serbest bırak
            c.execute("UPDATE video_analysis SET status = 'error', error = 'Uygulama yeniden başladı; tekrar dene' WHERE status IN ('queued', 'running')")
            c.commit()
        finally:
            c.close()

    def submit(self, conn: sqlite3.Connection, key: str) -> bool:
        with self.lock:
            cur = get(conn, key)["status"]
            if cur in ("queued", "running"):
                return False
            _set(conn, key, "queued")
            self.q.put(key)
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._loop, daemon=True, name="video-analiz")
                self.thread.start()
            return True

    def _loop(self) -> None:
        while True:
            try:
                key = self.q.get(timeout=30)
            except queue.Empty:
                return
            conn = self.connect(self.db_path)
            try:
                self._run(conn, key)
            finally:
                conn.close()

    def _run(self, conn: sqlite3.Connection, key: str) -> None:
        _set(conn, key, "running")
        tmp = None
        try:
            kind, _, ref = key.partition(":")
            if kind == "post":
                row = conn.execute("SELECT url FROM posts WHERE id = ?", (int(ref),)).fetchone()
                if row is None:
                    raise AnalysisError("Video kaydı yok")
                tmp = tempfile.mkdtemp(prefix="vanaliz-")
                path = self.fetch(row["url"], tmp)
            elif kind == "rv":
                row = conn.execute("SELECT path FROM rv_versions WHERE id = ?", (int(ref),)).fetchone()
                if row is None or not Path(row["path"]).is_file():
                    raise AnalysisError("Video dosyası bulunamadı")
                path = row["path"]
            else:
                raise AnalysisError("Bilinmeyen anahtar")
            _set(conn, key, "done", result=self.analyze(path))
        except Exception as e:  # tek video hatası uygulamayı etkilemesin
            _set(conn, key, "error", str(e)[:280] or e.__class__.__name__)
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
