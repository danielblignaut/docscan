"""Frozen DEV-only falsification of a generic chromatic-periodicity warning.

This is an independently written cheap hypothesis, not a reproduction of the
boundary-aware Kunina et al. method. Fixtures demonstrate ambiguity; they do not
estimate attack detection accuracy. No external image input is accepted.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def periodicity(rgb):
    """Return descriptive spectrum concentration and chromatic std, not probability."""
    rgb = rgb.astype(np.float64)
    chroma = np.stack((rgb[:, :, 0] - rgb[:, :, 1], rgb[:, :, 2] - rgb[:, :, 1]))
    chroma -= chroma.mean(axis=(1, 2), keepdims=True)
    std = float(np.sqrt(np.mean(chroma**2)))
    if std < 1e-9:
        return 0.0, std
    spectrum = np.abs(np.fft.fft2(chroma)) ** 2
    power = spectrum.sum(axis=0)
    power[0, 0] = 0
    fy = np.fft.fftfreq(rgb.shape[0])[:, None]
    fx = np.fft.fftfreq(rgb.shape[1])[None, :]
    radius = np.sqrt(fx**2 + fy**2)
    eligible = (radius >= 1 / 32) & (radius <= 1 / 4)
    # The eligible band excludes the self-conjugate Nyquist frequencies.
    concentration = float(2 * power[eligible].max() / power.sum())
    return min(1.0, concentration), std


def fixtures():
    """48 procedurally generated, fictional DEV graphics; no document text."""
    y, x = np.mgrid[:256, :256]
    for period in (8, 16, 32):
        for amplitude in (8, 24):
            for axis, coordinate, cross in (("horizontal", y, x), ("vertical", x, y)):
                name = f"p{period}-a{amplitude}-{axis}"
                for cohort in ("moire_surrogate", "benign_security_texture"):
                    phase = 2 * np.pi * coordinate / period
                    if cohort == "benign_security_texture":
                        # Gently curved coloured security-like linework confined
                        # to the paper interior, not a screen/camera simulation.
                        phase = phase + 0.4 * np.sin(2 * np.pi * cross / 64)
                    wave = amplitude * np.sin(phase)
                    if cohort == "benign_security_texture":
                        wave = wave * ((x >= 24) & (x < 232) & (y >= 24) & (y < 232))
                    rgb = np.stack((190 + wave, np.full_like(wave, 190), 190 - wave), axis=2)
                    # Same achromatic pseudo-print on both: grey blocks rather
                    # than OCR strings or identities.
                    ink = (x > 48) & (x < 180) & (y % 29 < 3)
                    rgb[ink] = 40
                    yield cohort, name, np.rint(rgb).clip(0, 255).astype(np.uint8)
    for i in range(12):
        paper = np.full((256, 256, 3), 245, dtype=np.uint8)
        ink = (x > 32) & (x < 200 - i) & ((y + i) % (12 + i) < 2)
        paper[ink] = 32
        yield "benign_grey_statement", f"layout-{i}", paper
        gradient = np.stack((120 + (x / 255) * (60 + i), 140 + (y / 255) * 40,
                             180 + ((x + y) / 510) * 30), axis=2)
        yield "benign_colour_gradient", f"gradient-{i}", gradient.astype(np.uint8)


def evaluate():
    rows = []
    for cohort, fixture_id, rgb in fixtures():
        concentration, std = periodicity(rgb)
        rows.append({
            "cohort": cohort, "fixture_id": fixture_id,
            "rgb_sha256": hashlib.sha256(rgb.tobytes()).hexdigest(),
            "chromatic_std_byte_levels": std,
            "spectral_concentration": concentration,
            "candidate_warning": std >= 4 and concentration >= 0.35,
        })
    counts = {
        cohort: {"total": sum(r["cohort"] == cohort for r in rows),
                 "warnings": sum(r["cohort"] == cohort and r["candidate_warning"] for r in rows)}
        for cohort in sorted({r["cohort"] for r in rows})
    }
    return {"counts": counts, "rows": rows,
            "decision": "reject_generic_warning" if any(
                r["cohort"].startswith("benign_") and r["candidate_warning"] for r in rows
            ) else "unvalidated_no_real_recapture_evaluation"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    receipt = args.output.with_suffix(args.output.suffix + ".freeze.json")
    protocol = json.loads((HERE / "protocol.json").read_text())
    hashes = {name: digest(HERE / name) for name in ("protocol.json", "probe.py")}
    freeze = {"frozen_at": datetime.now(timezone.utc).isoformat(), "sha256": hashes,
              "numpy_version": np.__version__, "protocol": protocol}
    # Create both paths exclusively before measurement; crashes leave a visible
    # incomplete report plus the freeze receipt, never overwrite earlier trials.
    with args.output.open("x") as report:
        with receipt.open("x") as handle:
            json.dump(freeze, handle, indent=2)
            handle.write("\n")
        result = evaluate()
        assert hashes == {name: digest(HERE / name) for name in hashes}
        result.update({"frozen_at": freeze["frozen_at"], "sha256": hashes,
                       "split": "dev_synthetic_only", "real_attacks_evaluated": 0})
        json.dump(result, report, indent=2)
        report.write("\n")
    print(json.dumps({"counts": result["counts"], "decision": result["decision"]}))


if __name__ == "__main__":
    main()
