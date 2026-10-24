import unittest
import numpy as np
from optics import linear, encode, preprocess, diagnostic, degrade
from run import aggregate, idscore


class OpticsTests(unittest.TestCase):
    def test_srgb_roundtrip_all_code_values(self):
        pixels = np.tile(np.arange(256, dtype=np.uint8)[:, None, None], (1, 2, 3))
        np.testing.assert_array_equal(encode(linear(pixels)), pixels)

    def test_clean_text_unchanged(self):
        page = np.full((240, 320, 3), 255, np.uint8)
        page[50:55, 40:200] = 20
        for arm in ('global_exposure', 'local_illumination'):
            out, meta = preprocess(page, arm)
            np.testing.assert_array_equal(out, page)
            self.assertFalse(meta['changed'])

    def test_gain_bounded_and_black_stays_black(self):
        page = np.full((240, 320, 3), 60, np.uint8)
        page[50:55, 40:200] = 0
        for arm in ('global_exposure', 'local_illumination'):
            out, _ = preprocess(page, arm)
            self.assertEqual(out.shape, page.shape)
            self.assertEqual(out.dtype, np.uint8)
            self.assertTrue(np.all(out[50:55, 40:200] == 0))
            self.assertLessEqual(float(linear(out).max()), float(linear(page).max())*4+.005)

    def test_white_paper_not_glare(self):
        self.assertEqual(diagnostic(np.full((320, 240, 3), 255, np.uint8))['glare_suspect_fraction'], 0)

    def test_bright_island_is_only_diagnostic(self):
        page = np.full((320, 240, 3), 150, np.uint8)
        page[110:140, 90:120] = 255
        before = page.copy()
        self.assertGreater(diagnostic(page)['glare_suspect_fraction'], 0)
        np.testing.assert_array_equal(page, before)

    def test_motion_loses_high_frequency_contrast(self):
        page = np.tile((np.arange(320) % 2 * 255).astype(np.uint8)[None, :, None], (240, 1, 3))
        blurred = degrade(page, 'motion_blur', 1)
        self.assertLess(np.std(linear(blurred)), np.std(linear(page)))

    def test_degradations_deterministic(self):
        page = np.full((120, 160, 3), 180, np.uint8)
        for condition in ('dark', 'shadow', 'glare', 'motion_blur'):
            a = degrade(page, condition, 12)
            b = degrade(page, condition, 12)
            np.testing.assert_array_equal(a, b)
            self.assertEqual(a.shape, page.shape)

    def test_failure_keeps_document_denominator(self):
        samples = [{'source': 'bankstatemently', 'text': 'ALPHA 7'}]
        entries = [{'index': 0, 'condition': 'dark', 'arm': a, 'key': a, 'preprocess': {'changed': a != 'baseline'}}
                   for a in ('baseline', 'global_exposure')]
        outputs = {'baseline': {'output': {'text': 'ALPHA 7'}, 'failure': None},
                   'global_exposure': {'output': {'text': ''}, 'failure': 'TimeoutExpired'}}
        result = aggregate(entries, samples, outputs)['bankstatemently/dark/global_exposure']
        self.assertEqual(result['truth_tokens'], 2)
        self.assertEqual(result['failures'], 1)
        self.assertEqual(result['exact_regions_lost'], 1)
        self.assertEqual(result['empty_readings'], 1)
        self.assertEqual(result['token_recall'], 0)

    def test_missing_camera_item_is_not_silently_skipped(self):
        with self.assertRaises(ValueError):
            idscore.score({'items': [], 'input': 'frame'}, [{'id': 'one'}])


if __name__ == '__main__':
    unittest.main()
