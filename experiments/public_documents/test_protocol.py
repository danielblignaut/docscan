import unittest
from evaluate import region_text, summary, token_score


class RefereeTests(unittest.TestCase):
    def test_repetition_and_hallucination_cost_precision(self):
        result = token_score('10.00 10.00', '10.00 20.00 invented')
        self.assertEqual(result['matched_tokens'], 1)
        self.assertEqual(result['truth_tokens'], 2)
        self.assertEqual(result['predicted_tokens'], 3)
        self.assertEqual(summary([result])['token_precision'], 1/3)

    def test_wrong_amount_is_not_normalized_away(self):
        self.assertEqual(token_score('1,000.00', '1000.00')['matched_tokens'], 0)

    def test_failed_page_stays_in_denominator(self):
        result = summary([token_score('a b', 'a b'), token_score('a b', '')])
        self.assertEqual(result['token_recall'], .5)
        self.assertEqual(result['items'], 2)

    def test_region_excludes_nearby_issuer(self):
        lines = [{'text':'issuer', 'x':0, 'y':0, 'w':10, 'h':10},
                 {'text':'customer', 'x':100, 'y':100, 'w':10, 'h':10}]
        self.assertEqual(region_text(lines, [99,99,111,111]), 'customer')


if __name__ == '__main__':
    unittest.main()
