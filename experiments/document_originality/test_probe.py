import unittest

import numpy as np

from probe import evaluate, fixtures, periodicity


class PeriodicityTests(unittest.TestCase):
    def test_flat_colour_has_no_periodic_energy(self):
        concentration, std = periodicity(np.full((32, 32, 3), 128, dtype=np.uint8))
        self.assertEqual((concentration, std), (0.0, 0.0))

    def test_exact_chromatic_sinusoid_is_measurable_not_a_probability(self):
        y, x = np.mgrid[:32, :32]
        wave = 20 * np.cos(2 * np.pi * x / 8)
        rgb = np.stack((128 + wave, np.full_like(wave, 128), 128 - wave), axis=2)
        concentration, std = periodicity(rgb)
        self.assertAlmostEqual(concentration, 1.0)
        self.assertGreater(std, 4)

    def test_real_attack_claims_are_not_supported_by_fixture_labels(self):
        rows = list(fixtures())
        self.assertEqual(len(rows), 48)
        self.assertEqual(len({(c, i) for c, i, _ in rows}), 48)
        self.assertFalse(any(c == "real_attack" for c, _, _ in rows))

    def test_security_linework_falsifies_generic_copy_warning(self):
        result = evaluate()
        self.assertGreater(result["counts"]["benign_security_texture"]["warnings"], 0)
        self.assertEqual(result["decision"], "reject_generic_warning")


if __name__ == "__main__":
    unittest.main()
