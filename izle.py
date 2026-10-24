"""Kısayol: herhangi bir klasörden `python <bu klasör>/izle.py ekle video.mp4 --baslik "..."` çalışır."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Göreli yolları review.main, klasör değişmeden önceki çağıran klasöre göre çözer
os.environ["IZLE_CWD"] = os.getcwd()
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.review import main  # noqa: E402

sys.exit(main(sys.argv[1:]))
