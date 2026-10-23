"""Small referee regressions: ties cannot inflate FAR; identity media stay grouped."""
import unittest
import numpy as np
from evaluate import rates, scores, threshold_at_far


class ProtocolTests(unittest.TestCase):
    def test_threshold_respects_ties_and_zero_far(self):
        values = np.array([0.9, 0.8, 0.8, 0.2], dtype=np.float32)
        truth = np.array([True, False, False, False])
        for far in (0.0, 0.34):
            threshold = threshold_at_far(values, truth, far)
            self.assertLessEqual(rates(values, truth, threshold)['far'], far)

    def test_missing_reference_stays_in_genuine_denominator(self):
        rows = [{'split': 'validation', 'pose': 'neutral', 'condition': 'original', 'id': 'a'}, {'split': 'validation', 'pose': 'smile', 'condition': 'original', 'id': 'a'}]
        values, labels, counts = scores(rows, np.array([[1., 0.], [1., 0.]]), np.array([True, False]), 'validation', 'original')
        self.assertEqual(counts['genuine_pairs'], 1)
        self.assertEqual(counts['missing_reference'], 1)
        self.assertEqual(values[labels].tolist(), [-1.0])


if __name__ == '__main__':
    unittest.main()
