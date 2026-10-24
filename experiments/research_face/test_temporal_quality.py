import json
from pathlib import Path
import unittest
import numpy as np
from temporal_quality import frame_values, fuse

CFG = json.loads(Path(__file__).with_name('protocol-v1.json').read_text())


class ProtocolTests(unittest.TestCase):
    def test_missing_and_invalid_are_kept(self):
        scores, missing, invalid = frame_values([
            {'found': False, 'raw_real': 1}, {'found': True, 'raw_real': float('nan')},
            {'found': True, 'raw_real': 0.8}])
        self.assertEqual(scores.tolist(), [-1., -1., 0.8])
        self.assertEqual((missing, invalid), (1, 1))
        result, blocks = fuse(scores, [0.05, 0.05, 1], [0, 1, 2], CFG)
        self.assertEqual(blocks, [1, 1, 1])
        self.assertEqual(result['block_quality_mean_q10'], -1.)

    def test_partial_block_retained_and_quality_can_favor_attack(self):
        result, blocks = fuse([0., 1., 0.5], [0.05, 1., 1.], [0., 0.1, 1.1], CFG)
        self.assertEqual(blocks, [2, 1])
        self.assertGreater(result['block_quality_mean_q10'], result['block_mean_q10'])

    def test_duplicate_density_does_not_weight_blocks(self):
        first, _ = fuse([0.2, 0.8], [1, 1], [0, 1], CFG)
        second, _ = fuse([0.2, 0.2, 0.2, 0.8], [1]*4, [0, .1, .2, 1], CFG)
        self.assertAlmostEqual(first['block_mean_q10'], second['block_mean_q10'])
        self.assertNotEqual(first['frame_median'], second['frame_median'])

    def test_convex_fusion_cannot_cross_maximum(self):
        rng = np.random.default_rng(20261024)
        for _ in range(100):
            scores, weights = rng.random(51)*0.58, rng.random(51)+0.05
            result, sizes = fuse(scores, weights, np.arange(51)/10, CFG)
            self.assertEqual(sum(sizes), 51)
            self.assertTrue(all(scores.min() <= x <= scores.max() for x in result.values()))

    def test_invalid_temporal_inputs_abort(self):
        for times in ([0, 0], [0, 2], [1, 2]):
            with self.assertRaises(ValueError):
                fuse([0, 1], [1, 1], times, CFG)
        with self.assertRaises(ValueError):
            fuse([0, 1], [0, 1], [0, 1], CFG)
        with self.assertRaises(ValueError):
            frame_values([{'raw_real': .8}])


if __name__ == '__main__':
    unittest.main()
