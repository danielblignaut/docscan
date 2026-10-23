"""Version 2 of the DEV-only front/back E2E fixture, with longer held sides.

Keeps every v1 pixel and arrival sequence. Only the already-held 2.2-second
suffix of each side is repeated, giving slow single-thread OCR time for two
consistent reads before the card is turned over. No acceptance rule or test
timeout changes. The original composite and bench's id_clips stay untouched.

Run after make_front_back.py; output is hd/smart-id-front-back-v2.y4m plus
JSON provenance. --source and --output allow a shared existing v1 clip.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SIDE_SECONDS = 4.8
ORIGINAL_HOLD_SECONDS = 2.2


def extend(source: Path, output: Path, *, front_hold: float = 20.0, back_hold: float = 12.0) -> dict:
    if source.resolve() == output.resolve():
        raise ValueError("v2 must not overwrite its v1 source")
    if min(front_hold, back_hold) < ORIGINAL_HOLD_SECONDS:
        raise ValueError("v2 must preserve the whole original held sequence")
    with source.open("rb") as src:
        header = src.readline()
        fields = {part[:1]: part[1:] for part in header.split()[1:]}
        if not header.startswith(b"YUV4MPEG2 ") or not fields.get(b"C", b"420").startswith(b"420"):
            raise ValueError("expected a YUV4MPEG2 4:2:0 source")
        width, height = int(fields[b"W"]), int(fields[b"H"])
        numerator, denominator = map(int, fields[b"F"].split(b":"))
        fps = numerator / denominator
        pixels = width * height + 2 * ((width + 1) // 2) * ((height + 1) // 2)
        stride = len(b"FRAME\n") + pixels
        side_frames = round(SIDE_SECONDS * fps)
        hold_frames = round(ORIGINAL_HOLD_SECONDS * fps)
        if source.stat().st_size != len(header) + 2 * side_frames * stride:
            raise ValueError("expected two 4.8-second v1 sides with plain FRAME markers")
        source_hash = hashlib.sha256(header)
        # Validate all markers before creating output, and record source bytes.
        for _ in range(2 * side_frames):
            frame = src.read(stride)
            if not frame.startswith(b"FRAME\n"):
                raise ValueError("source contains an invalid or extended frame marker")
            source_hash.update(frame)
        output.parent.mkdir(parents=True, exist_ok=True)
        output_hash = hashlib.sha256()
        timeline = []
        count = 0
        with output.open("wb") as dst:
            def write(data: bytes) -> None:
                dst.write(data)
                output_hash.update(data)

            write(header)
            for side, hold in enumerate((front_hold, back_hold)):
                start = count
                src.seek(len(header) + side * side_frames * stride)
                for _ in range(side_frames):
                    write(src.read(stride))
                    count += 1
                extra = round((hold - ORIGINAL_HOLD_SECONDS) * fps)
                # Cycle the original held tail, including its existing tremor
                # and noise. Never freeze one ideal frame or change its quality.
                tail_start = len(header) + ((side + 1) * side_frames - hold_frames) * stride
                for i in range(extra):
                    src.seek(tail_start + (i % hold_frames) * stride)
                    write(src.read(stride))
                    count += 1
                timeline.append({"side": "front" if side == 0 else "back", "starts_s": start / fps,
                                 "held_from_s": start / fps + SIDE_SECONDS - ORIGINAL_HOLD_SECONDS,
                                 "ends_s": count / fps})
    meta = {"fixture_version": 2, "split": "dev", "purpose": "browser E2E only; not bench id_clips",
            "source": source.name, "source_sha256": source_hash.hexdigest(),
            "output": output.name, "sha256": output_hash.hexdigest(), "size": [width, height],
            "fps": fps, "frames": count, "timeline": timeline,
            "change": "repeat each original held tail; preserve all original pixels and arrival frames"}
    output.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "video/hd/smart-id-front-back.y4m")
    parser.add_argument("--output", type=Path, default=ROOT / "video/hd/smart-id-front-back-v2.y4m")
    args = parser.parse_args()
    print(json.dumps(extend(args.source, args.output), indent=2))


if __name__ == "__main__":
    main()
