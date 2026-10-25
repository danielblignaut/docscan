"""Unit tests of the label-speed runner's comparison and scoring (no data, no probe)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402


def f(label, value, kind="imei", source="text", check=True):
    return {"label": label, "value": value, "kind": kind, "source": source, "check_digit_valid": check}


class CompareTest(unittest.TestCase):
    def test_lost_gained_and_hidden_fields(self):
        base = [f("IMEI1", "1"), f("SN", "A", "text", check=None), f("IMEI2", "9", check=False)]
        cand = [f("IMEI1", "1", source="both"), f("SN", "B", "text", check=None)]
        c = run.compare(base, cand)
        # A check-digit failure is not shown, so it is neither lost nor kept.
        self.assertEqual((c["base"], c["lost"], c["gained"]), (2, 1, 1))
        self.assertEqual(c["lost_by_kind"], {"text": 1})
        self.assertEqual((c["source_changed"], c["other_to_both"], c["check_changed"]), (1, 1, 0))

    def test_value_normalised(self):
        self.assertEqual(run.compare([f("SN", "ab-1")], [f("SN", "AB 1")])["lost"], 0)


class TruthTest(unittest.TestCase):
    def test_failed_frame_stays_in_denominator(self):
        rows = [{"path": "a", "fields": [{"label": "SN", "value": "X"}], "codes": []},
                {"path": "b", "fields": [{"label": "SN", "value": "Y"}], "codes": []}]
        res = {"a": {"fields": [f("SN", "X", "text", check=None), f(None, "Z", "text", check=None)]}}
        t = run.truth_score(rows, res)
        self.assertEqual((t["truth_fields"], t["label_value_hits"], t["false_fields"]), (2, 1, 1))
        self.assertEqual(t["label_value"], 0.5)


    def test_truth_delta_splits_lost_fields(self):
        rows = [{"path": "a", "fields": [{"label": "IMEI1", "value": "1"}, {"label": "SN", "value": "S"}], "codes": []}]
        full = {"a": {"fields": [f("IMEI1", "1"), f("IMEI2", "7"), f("IMEI1", "S", "text", check=None)]}}
        cand = {"a": {"fields": [f("SN", "S", "text", check=None)]}}
        d = run.truth_delta(rows, full, cand)
        self.assertEqual(d["label_value_lost"], {"IMEI1": 1})
        self.assertEqual(d["label_value_gained"], {"SN": 1})
        self.assertEqual(d["lost_split"], {"correct": 1, "wrong_label": 1, "false": 1, "false_imei_luhn": 1})
        self.assertEqual(run.false_by_kind(rows, full), {"imei_check_valid": 1})


if __name__ == "__main__":
    unittest.main()
