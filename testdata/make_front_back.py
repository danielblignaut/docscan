"""The two-step smart ID clip: the card's front, then its back, in one 1280x720
video, for the front-then-back browser test.

Run after make_videos.py's HD set:
    .venv/bin/python make_videos.py --size 1280x720 --seconds 4.8 --hold 2.2 --only za_smart_id_back multi_barcode --outdir video/hd
    .venv/bin/python make_front_back.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HD = ROOT / "video" / "hd"
FRONT_DIR = ROOT / "video" / "hd-front"


def frames(path: Path):
    """The header line and the raw frames (each with its FRAME line) of a .y4m."""
    data = path.read_bytes()
    header, _, body = data.partition(b"\n")
    return header, body


def main() -> None:
    subprocess.run(
        [sys.executable, ROOT / "make_videos.py", "--size", "1280x720", "--seconds", "4.8", "--hold", "2.2",
         "--only", "za_smart_id_front", "--outdir", "video/hd-front"],
        check=True,
    )
    front_header, front = frames(FRONT_DIR / "za_smart_id_front.y4m")
    back_header, back = frames(HD / "za_smart_id_back.y4m")
    if front_header != back_header:
        raise SystemExit(f"clips differ in format: {front_header!r} vs {back_header!r}")
    out = HD / "smart-id-front-back.y4m"
    out.write_bytes(front_header + b"\n" + front + back)
    for f in FRONT_DIR.iterdir():
        f.unlink()
    FRONT_DIR.rmdir()
    print(f"wrote {out} ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
