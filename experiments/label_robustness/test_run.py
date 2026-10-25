"""Unit tests of the runner's scoring (no probe, no data)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402


def f(label, value, kind="text", check=None, source="text"):
    return {"label": label, "value": value, "kind": kind, "check_digit_valid": check, "source": source}


ROW = {"path": "p", "specimen": 0, "codes": [{"text": "CODE1"}],
       "fields": [{"label": "SN", "value": "AB12CD34"}, {"label": "IMEI1", "value": "990000123456784"}]}


class Scoring(unittest.TestCase):
    def test_failed_frame_stays_in_denominator(self):
        s = run.score([ROW], {})
        self.assertEqual((s["truth_fields"], s["label_value_hits"], s["serial_errors"]), (2, 0, 1))

    def test_false_serial_counts_twice_in_serial_errors(self):
        res = {"p": {"fields": [f("SN", "AB12CD35"), f("IMEI1", "990000123456784", "imei", True)]}}
        s = run.score([ROW], res)
        self.assertEqual((s["label_value_hits"], s["false_fields"], s["sn_false"], s["serial_errors"]), (1, 1, 1, 2))

    def test_check_failed_fields_are_not_shown(self):
        res = {"p": {"fields": [f("IMEI1", "990000123456785", "imei", False)]}}
        self.assertEqual(run.score([ROW], res)["false_fields"], 0)

    def test_delta_and_specimens(self):
        base = {"p": {"fields": [f("SN", "AB12CD35")]}}
        cand = {"p": {"fields": [f("SN", "AB12CD34")]}}
        d = run.delta([ROW], base, cand)
        self.assertEqual((d["truth_gained_total"], d["truth_lost_total"], d["shown_lost"]["false"], d["shown_gained"]["correct"]), (1, 0, 1, 1))
        self.assertEqual(run.specimens([ROW], base, cand)["improved"], 1)
        self.assertEqual(run.delta([ROW], base, base)["frames_identical"], 1)


if __name__ == "__main__":
    unittest.main()
