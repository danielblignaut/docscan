import unittest

from temporal_replay import frame_scores, summarize


class TemporalTests(unittest.TestCase):
    def test_transient_crossing_is_visible_when_median_rejects(self):
        clip = {'frames': 3, 'scores': [{'found': True, 'raw_real': v} for v in (.1, .9, .1)]}
        report = summarize([clip], {'passive': .59})
        m = report['metrics']['passive']
        self.assertEqual(m['accepted_frames'], 1)
        self.assertEqual(m['clips_with_any_accepted_frame'], 1)
        self.assertEqual(m['clips_with_accepted_median'], 0)
        self.assertIsNone(report['bpcer'])

    def test_invalid_frame_rejects_and_stays_in_denominator(self):
        clip = {'frames': 3, 'scores': [{'found': False, 'raw_real': 1.}, {'found': True, 'raw_real': float('nan')}, {'found': True, 'raw_real': .9}]}
        report = summarize([clip], {'passive': .59})
        self.assertEqual(report['missing_frames'], 1)
        self.assertEqual(report['invalid_frames'], 1)
        self.assertEqual(report['metrics']['passive']['frame_acceptance_fraction_descriptive'], 1/3)

    def test_truncated_native_output_aborts(self):
        with self.assertRaises(ValueError):
            frame_scores([{'found': False}], 2)


if __name__ == '__main__':
    unittest.main()
