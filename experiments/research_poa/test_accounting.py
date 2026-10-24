import json
from pathlib import Path
import sys
import unittest

from run import page_text, score_checked, type_row, summarize

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'eval'))
import poa_extraction_dev as dev


class AccountingTests(unittest.TestCase):
    def test_failure_never_earns_negative_rejection_or_null_field_match(self):
        caps = [{'id': 'fixture-negative'}]
        truths = {'fixture-negative': {'case': 'wrong_person', 'expect_accept': False, 'fields': {}}}
        outputs = {'fixture-negative': {'capture': {'fields': None, 'verify': None},
                    'frames': [{'fields': None, 'verify': None}]}}
        scored = score_checked(dev, caps, truths, outputs)
        for metric in scored.values():
            if metric.get('kind') == 'rate' and metric['n']:
                self.assertEqual(metric['k'], 0)
        self.assertEqual(scored['poa.dev.reject_wrong_person']['n'], 1)
        self.assertEqual(scored['poa.dev.single.reject_wrong_person']['n'], 1)

    def test_paired_regression_and_false_bank_are_retained(self):
        rows = [type_row('negative', 'utility_bill', 'utility_bill', 'bank_statement'),
                type_row('missing', 'bank_statement', None, None)]
        s = summarize(rows)
        self.assertEqual((s['denominator'], s['regressed'], s['false_bank_candidate']), (2, 1, 1))
        self.assertEqual(s['candidate_exact'], 0)

    def test_line_boundary_preserves_keywords(self):
        words = [{'text': 'bank', 'line': 1}, {'text': 'statement', 'line': 2}]
        self.assertEqual(page_text(words), 'bank\nstatement')

if __name__ == '__main__': unittest.main()
