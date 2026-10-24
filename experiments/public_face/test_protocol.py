"""Small referee regressions: ties cannot inflate FAR; identity media stay grouped."""
import unittest
import json
import tempfile
from pathlib import Path
import numpy as np
from evaluate import cache_key, rates, read_embeddings, scores, threshold_at_far
from pad_sample import exact_interval, media_scores, run_key


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
        self.assertEqual(values[labels].tolist(), [-np.inf])
        self.assertFalse((values[labels] >= -1).any())

    def test_all_missing_calibration_does_not_accept_missing_pairs(self):
        values = np.full((2, 2), -np.inf, dtype=np.float32)
        truth = np.eye(2, dtype=bool)
        threshold = threshold_at_far(values, truth, .001)
        self.assertTrue(np.isfinite(threshold))
        self.assertEqual(rates(values, truth, threshold)['tar'], 0)
        self.assertEqual(rates(values, truth, threshold)['far'], 0)

    def test_caches_include_partition_models_and_media(self):
        args = ('binary', {'mesh': 'a'}, [{'path': 'synthetic', 'sha256': 'b'}])
        self.assertNotEqual(cache_key(*args, 'iris', 1), cache_key(*args, 'iris', 2))
        self.assertNotEqual(cache_key(*args, 'iris', 1), cache_key(*args, 'flip', 1))
        self.assertNotEqual(run_key(*args), run_key('binary', {'mesh': 'changed'}, args[2]))
        self.assertNotEqual(run_key(*args), run_key(*args[:2], [{'path': 'synthetic', 'sha256': 'changed'}]))

    def test_bad_embedding_rows_reject_and_bad_shape_aborts(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'synthetic.f32'
            np.array([[1., 0.], [1., 0.], [np.nan, 0.], [0., 0.]], dtype='<f4').tofile(out)
            meta = {'dim': 2, 'items': [{'found': True, 'presence': 1.}, {'found': True, 'presence': .1}, {'found': True}, {'found': True}]}
            Path(str(out) + '.json').write_text(json.dumps(meta))
            vec, found, _ = read_embeddings(out, 4)
            self.assertEqual(found.tolist(), [True, False, False, False])
            self.assertTrue(np.isfinite(vec).all())
            with self.assertRaises(ValueError):
                read_embeddings(out, 3)
            out.write_bytes(out.read_bytes()[:-4])
            with self.assertRaises(ValueError):
                read_embeddings(out, 4)

    def test_pad_count_mismatch_never_silently_drops_frames(self):
        rows = [{'media': 0, 'class': 'genuine'}, {'media': 1, 'class': 'replay'}]
        with self.assertRaises(ValueError):
            media_scores(rows, [{'found': True, 'raw_real': 1.}])
        with self.assertRaises(ValueError):
            media_scores(rows, [{'found': True, 'raw_real': 1.}] * 3)

    def test_pad_invalid_scores_and_missing_detections_reject(self):
        rows = [{'media': 0, 'class': 'genuine'}, {'media': 1, 'class': 'replay'}]
        for value in (None, float('nan'), float('inf'), -0.1, 1.1):
            media = media_scores(rows, [{'found': True, 'raw_real': value}, {'found': False, 'raw_real': 1.}])
            self.assertEqual([m['score'] for m in media], [-1., -1.])
            self.assertEqual(media[0]['invalid_frames'], 1)
            self.assertEqual(media[1]['missing_frames'], 1)

    def test_pad_keeps_media_as_unit_and_preserves_median_rule(self):
        rows = [{'media': 0, 'class': 'genuine'}] + [{'media': 1, 'class': 'replay'}] * 3
        media = media_scores(rows, [{'found': True, 'raw_real': .9}, {'found': False}, {'found': True, 'raw_real': .8}, {'found': True, 'raw_real': .7}])
        self.assertEqual(len(media), 2)
        self.assertEqual(media[1]['score'], .7)
        self.assertEqual(media[1]['missing_frames'], 1)

    def test_five_perfect_trials_still_have_large_uncertainty(self):
        lo, hi = exact_interval(0, 5)
        self.assertEqual(lo, 0.)
        self.assertAlmostEqual(hi, 1 - .025**(1/5))
        self.assertAlmostEqual(exact_interval(5, 5)[0], 1-hi)
        self.assertAlmostEqual(exact_interval(1, 2)[0], .012579117093425)


if __name__ == '__main__':
    unittest.main()
