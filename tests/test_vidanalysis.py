import shutil
import subprocess
import time
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import analytics, db, vidanalysis as va
from app.config import Config, parse_categories
from app.web import create_app

CATS = parse_categories({"categories": [{"name": "diy", "subcategories": ["hook"]}]})
needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg yok")


def _seg(path, video, audio, secs):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", video, "-f", "lavfi", "-i", audio, "-t", str(secs),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)


@pytest.fixture(scope="module")
def bad_video(tmp_path_factory):
    """4 sn durağan+sessiz açılış, 6 sn hareketli+sesli, 8 sn durağan+sessiz (ölü orta), 3 sn hızlı+sesli."""
    d = tmp_path_factory.mktemp("v")
    parts = [("color=c=gray:s=320x568:d=4:r=25", "anullsrc=r=44100:cl=mono", 4), ("testsrc2=s=320x568:d=6:r=25", "sine=f=440:d=6", 6),
             ("color=c=white:s=320x568:d=8:r=25", "anullsrc=r=44100:cl=mono", 8), ("testsrc2=s=320x568:d=3:r=25,hue=s=2", "sine=f=880:d=3", 3)]
    files = []
    for i, (v, a, s) in enumerate(parts):
        f = d / f"s{i}.mp4"
        _seg(f, v, a, s)
        files.append(f)
    (d / "l.txt").write_text("".join(f"file {f.name}\n" for f in files))
    out = d / "bad.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-i", str(d / "l.txt"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)
    return out


def test_ayristirma_fonksiyonlari_ffmpeg_gerektirmez():
    scene = va.parse_scene("frame:0 pts:0 pts_time:0\nlavfi.scene_score=0.000000\nframe:1 pts:1 pts_time:0.25\nlavfi.scene_score=0.510000\n")
    assert scene == [(0.0, 0.0), (0.25, 0.51)]
    err = ("[Parsed_ebur128_0 @ 1] t: 0.1   TARGET:-23 LUFS    M:-163.2 S:-120.7     I: -70.0 LUFS\n"
           "[Parsed_ebur128_0 @ 1] t: 1.5   TARGET:-23 LUFS    M: -21.8 S: -29.8     I: -23.6 LUFS\n"
           "[silencedetect @ 2] silence_start: 0\n[silencedetect @ 2] silence_end: 1.2 | silence_duration: 1.2\n"
           "[silencedetect @ 2] silence_start: 8.0\n[Parsed_ebur128_0 @ 1] Summary:\n\n  Integrated loudness:\n    I:         -21.8 LUFS\n")
    a = va.parse_audio(err, 10.0)
    assert a["loud"] == [(1.5, -21.8)] and a["silences"] == [(0.0, 1.2), (8.0, 10.0)] and a["integrated"] == -21.8


def test_brief_kurallari_sentetik_ozelliklerle():
    f = {"duration": 21, "width": 320, "height": 568, "fps": 25, "has_audio": True, "cut_count": 3, "first_cut": 4.0, "avg_shot": 5.25,
         "cuts_per_10s": 1.4, "hook_motion_ratio": 0.2, "low_zones": [{"start": 10, "end": 18}], "low_seconds": 8, "avg_energy": 0.3,
         "integrated_lufs": -22.0, "audio_start": 4, "loud_mean": -22, "hook_loud": -40, "silence_ratio": 0.57, "end_ratio": 0.4}
    b = va.make_briefs(f)
    by = {(x["section"], x["level"]) for x in b}
    assert ("hook", "sorun") in by and ("orta", "sorun") in by and ("ses", "dikkat") in by and ("bitis", "dikkat") in by
    assert any("0:10–0:18" in x["text"] for x in b) and all(x["fix"] for x in b if x["level"] == "sorun")
    sc = va.scores(f, b)
    assert sc["hook"] < 50 and sc["orta"] < 80
    good = dict(f, first_cut=0.8, hook_motion_ratio=1.2, low_zones=[], low_seconds=0, audio_start=0, hook_loud=-20, silence_ratio=0.05,
                integrated_lufs=-14, end_ratio=1.0, avg_shot=2.0)
    gb = va.make_briefs(good)
    assert all(x["level"] == "iyi" for x in gb) and va.scores(good, gb)["hook"] == 100


@needs_ffmpeg
def test_gercek_video_analizi_duragan_acilis_ve_olu_orta(bad_video):
    r = va.analyze_file(str(bad_video))
    f = r["features"]
    assert 20 <= f["duration"] <= 22 and f["has_audio"] and f["cut_count"] >= 2
    assert f["first_cut"] is not None and 3.5 <= f["first_cut"] <= 4.5          # ilk kesme 4. saniyede
    assert f["audio_start"] is not None and 3 <= f["audio_start"] <= 5          # ses 4. saniyeye kadar yok
    assert any(z["start"] >= 9 and z["end"] <= 19 for z in f["low_zones"])       # 10-18 sn ölü orta
    assert ("hook", "sorun") in {(b["section"], b["level"]) for b in r["briefs"]}
    assert ("orta", "sorun") in {(b["section"], b["level"]) for b in r["briefs"]}
    assert len(r["timeline"]["energy"]) == r["timeline"]["seconds"] and r["scores"]["hook"] < 60
    assert "Otomatik bulgular" in va.claude_prompt("Deneme", r)


@needs_ffmpeg
def test_bozuk_dosya_acik_hata_verir(tmp_path):
    bad = tmp_path / "x.mp4"
    bad.write_bytes(b"degil bir video")
    with pytest.raises(va.AnalysisError):
        va.analyze_file(str(bad))


def test_runner_sirayla_calisir_hata_yakalar_ve_takili_isleri_birakir(tmp_path):
    path = tmp_path / "r.db"
    with closing(db.connect(path)) as c:
        aid = analytics.add_account(c, "M", "youtube", "abc")
        pid = analytics.upsert_post(c, aid, ext_id="v1", url="https://youtube.com/watch?v=1", title="Video")
        c.execute("INSERT INTO video_analysis (key, status) VALUES ('post:99', 'running')")
        c.commit()
    calls = []

    def fake_analyze(p):
        calls.append(p)
        if "bozuk" in p:
            raise va.AnalysisError("Bozuk")
        return {"features": {}, "timeline": {}, "briefs": [], "scores": {}}

    runner = va.Runner(str(path), db.connect, analyze=fake_analyze, fetch=lambda url, dest: dest + "/ok.mp4")
    with closing(db.connect(path)) as c:
        assert va.get(c, "post:99")["status"] == "error"  # önceki oturumdan kalan 'running' serbest bırakıldı
        assert runner.submit(c, f"post:{pid}")
        for _ in range(100):
            if va.get(c, f"post:{pid}")["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        assert va.get(c, f"post:{pid}")["status"] == "done" and calls
        assert va.get(c, "post:12345")["status"] == "none"
        runner.fetch = lambda url, dest: dest + "/bozuk.mp4"
        assert runner.submit(c, f"post:{pid}")
        for _ in range(100):
            if va.get(c, f"post:{pid}")["status"] not in ("queued", "running"):
                break
            time.sleep(0.05)
        rec = va.get(c, f"post:{pid}")
        assert rec["status"] == "error" and "Bozuk" in rec["error"]


def test_web_analiz_uclari(tmp_path):
    cfg = Config(db_path=str(tmp_path / "w.db"), allowed_hosts=["testserver"])
    with closing(db.connect(cfg.db_path)) as c:
        aid = analytics.add_account(c, "M", "youtube", "abc")
        pid = analytics.upsert_post(c, aid, ext_id="v1", url="https://youtube.com/watch?v=1", title="Video")
    fake = {"features": {"duration": 10, "width": 1, "height": 1, "cut_count": 1, "avg_shot": 2, "first_cut": 1},
            "timeline": {"energy": [0.5]}, "briefs": [], "scores": {"hook": 90}}
    runner = va.Runner(cfg.db_path, db.connect, analyze=lambda p: fake, fetch=lambda url, dest: dest + "/v.mp4")
    cl = TestClient(create_app(cfg, CATS, analyzer=runner))
    assert cl.get(f"/api/analysis/post/{pid}").json()["status"] == "none"
    assert cl.get("/api/analysis/zzz/1").status_code == 404
    assert cl.post("/api/analysis/post/999").status_code == 404
    assert cl.get(f"/api/analysis/post/{pid}/prompt").status_code == 409
    assert cl.post(f"/api/analysis/post/{pid}").status_code == 200
    for _ in range(100):
        if cl.get(f"/api/analysis/post/{pid}").json()["status"] == "done":
            break
        time.sleep(0.05)
    assert cl.get(f"/api/analysis/post/{pid}").json()["result"]["scores"]["hook"] == 90
    assert "Video analizi" in cl.get(f"/api/analysis/post/{pid}/prompt").text
    assert cl.post("/api/analysis/rv/999").status_code == 404
