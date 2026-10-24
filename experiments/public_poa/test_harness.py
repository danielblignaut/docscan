"""Referee integrity tests, using invented fixtures rather than publisher text."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness as h


def fixture():
    fields = {'holder_name': 'Example Person', 'address': {'street': '12 Test Road, Unit B',
              'city': 'Sampletown', 'postal_code': '01234'}, 'issuer': 'Fixture Bank',
              'account_number': 'XXXX 0000', 'document_type': 'bank_statement',
              'statement_period': {'from': '2026-01-01', 'to': '2026-01-31'}}
    truth = {name: h.at(fields, name) for name in h.FIELDS}
    return fields, truth


class RefereeTests(unittest.TestCase):
    def test_missing_fields_fail_all_fixed_opportunities(self):
        _, truth = fixture()
        for failed in ({}, {'error': 'timeout'}, {'rules': {'fields': None}}):
            read, scores = h.field_scores(failed, 'rules', truth)
            self.assertFalse(read)
            self.assertEqual(len(scores), 9)
            self.assertFalse(any(scores.values()))

    def test_no_read_does_not_earn_negative_rejection(self):
        _, truth = fixture()
        rows = [{'page': {'error': 'timeout'}, 'verification': {}} for _ in range(3)]
        result = h.aggregate_rows(rows, truth)
        self.assertEqual(result['tagger']['field_opportunities'], 27)
        for case in result['customer_verification'].values():
            self.assertEqual(case['denominator'], 3)
            self.assertEqual(case['rejected'], 0)
            self.assertEqual(case['failed_or_no_decision'], 3)

    def test_exact_preserves_house_unit_zip_and_mask(self):
        fields, truth = fixture()
        for key, value in [('address.street', '12 Test Road'), ('address.postal_code', '1234'),
                           ('account_number', '0000'), ('holder_name', 'Another Person')]:
            changed = copy.deepcopy(fields)
            target = changed
            parts = key.split('.')
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
            _, scores = h.field_scores({'rules': {'fields': changed}}, 'rules', truth)
            self.assertFalse(scores[key])
            self.assertEqual(sum(scores.values()), 8)

    def test_normalisation_does_not_expand_or_fuzz(self):
        self.assertEqual(h.norm(' ÉXAMPLE,  Person '), h.norm('éxample person'))
        self.assertNotEqual(h.norm('Road'), h.norm('Rd'))
        self.assertNotEqual(h.norm('01234'), h.norm('1234'))

    def test_reject_all_not_discriminative(self):
        fields, truth = fixture()
        checks = {case: {'capture': {'verify': {'accepted': False}}}
                  for case in ('matching', 'wrong_person', 'wrong_address', 'old')}
        result = h.aggregate_rows([{'page': {'tagger': {'fields': fields}}, 'verification': checks}], truth)
        self.assertEqual(result['tagger']['field_exact_total'], 9)
        self.assertEqual(result['customer_verification']['old']['rejected'], 1)
        self.assertEqual(result['customer_verification']['old']['paired_matching_accept_and_reject'], 0)
        self.assertEqual(result['customer_verification']['old']['old_date_evidence'], 0)

    def test_subprocess_failure_modes(self):
        self.assertEqual(h.run_json([sys.executable, '-c', 'print("bad")'])['error'], 'malformed_output')
        self.assertEqual(h.run_json([sys.executable, '-c', 'raise SystemExit(2)'])['error'], 'process_failure')
        self.assertEqual(h.run_json([sys.executable, '-c', 'import time; time.sleep(2)'], timeout=.02)['error'], 'timeout')
        self.assertEqual(h.run_json(['/does-not-exist'])['error'], 'launch_error')

    def test_truth_maps_masked_account_not_tail(self):
        truth = {'_meta': {'synthetic': True, 'licence': 'CC-BY-4.0'}, 'account_holder': 'Fixture',
                 'address': {'street': '12 Test Road', 'city': 'Sampletown', 'zip': '01234'},
                 'bank_name': 'Fixture Bank', 'document_type': 'bank_statement',
                 'personal_data': [{'type': 'ACCOUNT_NUMBER_MASKED', 'value': 'XXXX 0000'}],
                 'period': ['2026-01-01', '2026-01-31']}
        mapped = h.truth_fields(truth)
        self.assertEqual(mapped['account_number'], 'XXXX 0000')
        self.assertNotIn('document_date', mapped)
        self.assertNotIn('address.province', mapped)
        self.assertNotEqual(h.customer(truth, 'wrong_address')['address']['street'], truth['address']['street'])

    def test_repo_data_root_refused(self):
        with self.assertRaises(ValueError):
            h.private_root(h.HERE / 'raw-data')


if __name__ == '__main__':
    unittest.main()
