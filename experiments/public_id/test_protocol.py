import unittest
from score_id import score

class TrialAccountingTests(unittest.TestCase):
    def test_duplicate_result_does_not_increase_denominator(self):
        truth = [{'id':'first', 'fields':{}}, {'id':'second', 'fields':{}}]
        rows = [{'id':'first', 'output':{}}, {'id':'second', 'output':{}}]
        self.assertEqual(score({'items': rows, 'input':'frame'}, truth)['summary']['negative_frames'], 2)
        with self.assertRaisesRegex(ValueError, 'exactly'):
            score({'items': rows + [rows[0]], 'input':'frame'}, truth)

    def test_duplicate_truth_cannot_hide_missing_trial(self):
        truth = [{'id':'first', 'fields':{}}, {'id':'first', 'fields':{}}]
        with self.assertRaisesRegex(ValueError, 'exactly'):
            score({'items': [{'id':'first', 'output':{}}], 'input':'frame'}, truth)

if __name__ == '__main__':
    unittest.main()
