#!/usr/bin/env python3
"""Post-baseline failure localisation; exports counts only, never source text."""
import argparse
from pathlib import Path
import json

import harness as h

LEXICAL_FIELDS = h.FIELDS[:6]


def diagnose(root):
    h.check_freeze(root)
    truth = h.truth_fields(json.loads((root / 'truth.json').read_text()))
    result = {}
    for variant in (*h.VARIANTS, 'text-layer'):
        row = json.loads((root / 'baseline' / (variant + '.json')).read_text())
        page = row['page']
        text = h.norm(page.get('text', ''))
        # Literal presence is a diagnostic, not a correctness metric: the issuer
        # could be elsewhere on the page and reading order can break phrases.
        present = {key: bool(text and h.norm(truth[key]) in text) for key in LEXICAL_FIELDS}
        methods = {}
        for method in h.METHODS:
            _, scores = h.field_scores(page, method, truth)
            fields = h.at(page, method + '.fields')
            start = h.at(fields, 'statement_period.from')
            end = h.at(fields, 'statement_period.to')
            methods[method] = {
                'missing_fields': [key for key in h.FIELDS if h.at(fields, key) is None],
                'nonempty_wrong_fields': [key for key in h.FIELDS if h.at(fields, key) is not None and not scores[key]],
                'period_order_reversed': bool(start and end and start > end),
                'blind_verification_accepted': h.at(page, method + '.verification.accepted'),
                'literal_present_but_field_wrong': [key for key in LEXICAL_FIELDS if present[key] and not scores[key]],
                'literal_missing_and_field_wrong': [key for key in LEXICAL_FIELDS if not present[key] and not scores[key]],
            }
        checks = {}
        for case, raw in row['verification'].items():
            check = h.verification_score(raw)
            address = check.get('address') or {}
            date = check.get('date') or {}
            name = check.get('name') or {}
            checks[case] = {'valid': check['valid'], 'accepted': check['accepted'],
                            'name_score': name.get('score'), 'address_score': address.get('score'),
                            'holder_linked': address.get('holder_linked'),
                            'date_present': bool(date), 'date_recent': date.get('recent')}
        result[variant] = {'error': page.get('error'), 'lexical_truth_fields_present': present,
                           'methods': methods, 'checks': checks}
    return {'scope': 'Post-baseline descriptive diagnostics; no scoring changes or independent samples added.',
            'freeze_sha256': h.sha(root / 'freeze.json'), 'inputs': result}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=h.DEFAULT_ROOT)
    args = parser.parse_args()
    root = h.private_root(args.data_root)
    h.write(root / 'evidence.json', diagnose(root))
    print(root / 'evidence.json')
