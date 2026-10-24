"""Synthetic unit checks only; never opens benchmark corpora or private runs."""
import unittest

import numpy as np

from stroke_consistency import aggregate, predict, render


CFG = {"minimum_contrast": 24, "threshold": 0.12}


class StrokeTests(unittest.TestCase):
    def setUp(self):
        self.image = np.asarray(render(list(range(10)), 2.5, 0), dtype=float)

    def test_identical_is_clear(self):
        for candidate in (False, True):
            self.assertEqual(predict(self.image, self.image, CFG, candidate)["decision"], "clear")

    def test_affine_illumination_invariance(self):
        changed = self.image * 0.6 + 12
        self.assertEqual(predict(self.image, changed, CFG, False)["decision"], "flag")
        self.assertEqual(predict(self.image, changed, CFG, True)["decision"], "clear")

    def test_low_contrast_is_abstention_not_clear(self):
        changed = 220 + self.image * 0.03
        for candidate in (False, True):
            self.assertEqual(predict(self.image, changed, CFG, candidate)["decision"], "abstain")

    def test_nonfinite_and_bad_geometry_fail(self):
        image = self.image.copy()
        image[0, 0] = float("nan")
        with self.assertRaises(ValueError):
            predict(image, self.image, CFG, True)
        with self.assertRaises(ValueError):
            predict(self.image[:, :-1], self.image, CFG, True)

    def test_failures_keep_denominator_and_no_detection_credit(self):
        rows = [{"attack": attack, "baseline": {"decision": decision},
                 "candidate": {"decision": "error"}}
                for attack, decision in ((True, "flag"), (False, "clear"),
                                         (True, "abstain"), (False, "abstain"))]
        result = aggregate(rows)
        self.assertEqual(result["pairs"], 4)
        self.assertEqual(result["attacks"], 2)
        self.assertEqual(result["candidate"]["correct"], 0)
        self.assertEqual(result["candidate"]["attack_non_detections"], 2)
        self.assertEqual(result["candidate"]["errors"], 4)
        self.assertEqual(result["regressed"], 2)

    def test_attack_regression_and_benign_false_flags_count_separately(self):
        rows = [{"attack": True, "baseline": {"decision": "flag"}, "candidate": {"decision": "clear"}},
                {"attack": False, "baseline": {"decision": "clear"}, "candidate": {"decision": "flag"}}]
        result = aggregate(rows)
        self.assertEqual(result["new_clear_attacks"], 1)
        self.assertEqual(result["new_false_flags"], 1)
        self.assertEqual(result["regressed"], 2)


if __name__ == "__main__":
    unittest.main()
