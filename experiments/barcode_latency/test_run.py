"""Unit tests for the runner's comparison and scoring (made-up values only).

    python3 -m unittest discover -s experiments/barcode_latency -p test_run.py -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import compare, shown, sums, truth_score  # noqa: E402


def f(label, value, kind="text", source="text", check=None):
    return {"label": label, "value": value, "kind": kind, "source": source, "check": check}


class CompareTest(unittest.TestCase):
    def test_lost_gained_and_provenance(self):
        base = [f("IMEI1", "A1", "imei", "text", True), f(None, "G1", "gtin", "both", True), f("SN", "S1")]
        cand = [f("IMEI1", "a 1", "imei", "text", True), f(None, "G1", "gtin", "barcode", True), f("SN", "S2")]
        c = compare(base, cand)
        self.assertEqual((c["lost"], c["gained"], c["both_to_barcode"], c["source_changed"]), (1, 1, 1, 1))
        self.assertEqual(c["lost_by_kind"], {"text": 1})

    def test_a_label_change_is_a_loss(self):
        c = compare([f("IMEI1", "A1", "imei")], [f("IMEI2", "A1", "imei")])
        self.assertEqual((c["lost"], c["gained"]), (1, 1))

    def test_failed_check_digits_are_not_shown(self):
        self.assertEqual(len(shown([f("IMEI1", "A1", check=False), f("SN", "S1")])), 1)
        c = compare([f("IMEI1", "A1", check=False)], [])
        self.assertEqual(c["lost"], 0)

    def test_sums_merge_kinds(self):
        s = sums([compare([f("SN", "S1")], []), compare([f("SN", "S2"), f(None, "G", "gtin")], [])])
        self.assertEqual((s["lost"], s["lost_by_kind"]), (3, {"text": 2, "gtin": 1}))


class TruthTest(unittest.TestCase):
    def test_values_labels_and_false_outputs(self):
        rows = [{"path": "p", "fields": [{"label": "SN", "value": "S1"}, {"label": None, "value": "G1"}], "codes": [{"text": "G1"}]}]
        res = {"p": {"fields": [f("SN", "S1"), f("EAN", "G1"), f("SN", "X9"), f("SN", "S0", check=False)]}}
        t = truth_score(rows, res)
        self.assertEqual((t["value_hits"], t["label_value_hits"], t["false_fields"]), (2, 1, 1))


if __name__ == "__main__":
    unittest.main()
