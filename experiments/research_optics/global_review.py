#!/usr/bin/env python3
"""Post-run, requested paired analysis of frozen global exposure; no inference.

Exports counts/opaque public specimen IDs only, never OCR or reference strings.
Cluster bootstrap resamples entire statements/layouts, not individual fields.
With only 3/5 groups, intervals are exploratory and not a population guarantee.
"""
from collections import defaultdict
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path

import numpy as np

from run import HERE, sha, write, load_documents, fields_for, score


def counts(fields):
    summary = score.summary(fields)
    summary['unmatched_predictions'] = summary['predicted_tokens']-summary['matched_tokens']
    return summary


def bootstrap(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['group']].append(row)
    names = sorted(groups)
    arrays = {}
    for arm in ('baseline', 'global'):
        arrays[arm] = np.array([[sum(r[arm][k] for r in groups[name]) for k in
                                ('matched_tokens', 'truth_tokens', 'predicted_tokens', 'exact', 'items')]
                               for name in names], dtype=np.float64)
    rng = np.random.default_rng(236)
    draws = rng.integers(0, len(names), (10000, len(names)))
    a, b = (arrays[arm][draws].sum(axis=1) for arm in ('baseline', 'global'))
    result = {'clusters': len(names), 'draws': 10000, 'unit': 'whole statement or invoice layout'}
    for name, numerator, denominator in (('recall', 0, 1), ('precision', 0, 2), ('exact', 3, 4)):
        deltas = 100*(b[:, numerator]/np.maximum(b[:, denominator], 1)-a[:, numerator]/np.maximum(a[:, denominator], 1))
        before = arrays['baseline'].sum(axis=0)
        after = arrays['global'].sum(axis=0)
        result[name] = {'delta_percentage_points': float(100*(after[numerator]/max(after[denominator], 1)-before[numerator]/max(before[denominator], 1))),
                        'cluster_bootstrap_95_ci_pp': [float(x) for x in np.percentile(deltas, [2.5, 97.5])]}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', type=Path, default=HERE/'results-v1.json')
    p.add_argument('--output', type=Path, default=HERE/'global-review-v1.json')
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('refusing overwrite')
    report = json.loads(args.results.read_text())
    root = Path(report['private_run'])
    assert sha(root/'freeze.json') == report['freeze_sha256']
    frozen = json.loads((root/'freeze.json').read_text())
    samples = load_documents()
    entries = {(e['index'], e['condition'], e['arm']): e for e in frozen['documents']}
    outputs = {}
    for e in entries.values():
        if e['arm'] in ('baseline', 'global_exposure') and e['key'] not in outputs:
            path = root/'predictions'/f"{e['key']}.json"
            assert sha(path) == report['raw_hashes'][e['key']]
            outputs[e['key']] = json.loads(path.read_text())
    rows = []
    for index, sample in enumerate(samples):
        for condition in ('clean', 'dark', 'shadow', 'glare', 'motion_blur'):
            pair = [entries[index, condition, arm] for arm in ('baseline', 'global_exposure')]
            predictions = [outputs[e['key']] for e in pair]
            fields = [fields_for(sample, pred['output']) for pred in predictions]
            before, after = (counts(f) for f in fields)
            labels = [f['label'] for f in sample['fields']] if sample['source'] == 'fatura' else ['full_page']
            lost = [{'region_index': i, 'label': labels[i]} for i, (a, b) in enumerate(zip(*fields)) if a['exact'] and not b['exact']]
            gained = [{'region_index': i, 'label': labels[i]} for i, (a, b) in enumerate(zip(*fields)) if not a['exact'] and b['exact']]
            rows.append({'sample_id': sample['id'], 'group': sample['group'], 'source': sample['source'], 'condition': condition,
                         'baseline': before, 'global': after, 'exact_regions_lost': lost, 'exact_regions_gained': gained,
                         'matched_token_delta': after['matched_tokens']-before['matched_tokens'],
                         'unmatched_prediction_delta': after['unmatched_predictions']-before['unmatched_predictions'],
                         'precision_delta_pp': 100*(after['token_precision']-before['token_precision']),
                         'pixel_identical': pair[0]['key'] == pair[1]['key'],
                         'baseline_failure': bool(predictions[0]['failure']), 'global_failure': bool(predictions[1]['failure'])})
    dark = [r for r in rows if r['condition'] == 'dark']
    assert len(dark) == 60
    assert all(r['pixel_identical'] for r in rows if r['condition'] != 'dark')
    for source in ('fatura', 'bankstatemently'):
        for condition in ('clean', 'dark', 'shadow', 'glare', 'motion_blur'):
            part = [r for r in rows if r['source'] == source and r['condition'] == condition]
            for arm, original in (('baseline', 'baseline'), ('global', 'global_exposure')):
                expected = report['documents'][f'{source}/{condition}/{original}']
                for key in ('truth_tokens', 'matched_tokens', 'predicted_tokens', 'exact', 'items'):
                    assert sum(r[arm][key] for r in part) == expected[key]
    uncertainty = {s: bootstrap([r for r in dark if r['source'] == s]) for s in ('bankstatemently', 'fatura')}
    regressions = {s: {'pages': sum(r['source'] == s for r in dark),
        'lost_any_exact_region_pages': sum(bool(r['exact_regions_lost']) for r in dark if r['source'] == s),
        'lost_matched_token_pages': sum(r['matched_token_delta'] < 0 for r in dark if r['source'] == s),
        'more_unmatched_prediction_pages': sum(r['unmatched_prediction_delta'] > 0 for r in dark if r['source'] == s),
        'lower_precision_pages': sum(r['precision_delta_pp'] < 0 for r in dark if r['source'] == s),
        'any_of_these_regressions_pages': sum(bool(r['exact_regions_lost']) or r['matched_token_delta'] < 0 or r['unmatched_prediction_delta'] > 0 or r['precision_delta_pp'] < 0 for r in dark if r['source'] == s)}
        for s in ('bankstatemently', 'fatura')}
    result = {'analysis_utc': datetime.now(timezone.utc).isoformat(), 'source_sha256': sha(__file__),
        'accuracy_report_sha256': sha(args.results), 'posthoc_analysis_requested_by_user': True,
        'new_inference': False, 'thresholds_or_gates_changed': False,
        'uncertainty_dark': uncertainty, 'dark_paired_regression_counts': regressions,
        'unchanged_other_conditions': {'pages_per_condition': 60, 'conditions': ['clean', 'shadow', 'glare', 'motion_blur'], 'pixel_identical': True},
        'dark_pages': dark,
        'limits': 'Only 3 bank statements and 5 invoice layouts. Cluster intervals are descriptive, discrete and unstable; no independent significance or population/device claim. Exact loss can coexist with a net page gain. False-token counts are only over supplied reference regions.'}
    write(args.output, result)
    print(json.dumps({'uncertainty_dark': uncertainty, 'regressions': regressions}), flush=True)


if __name__ == '__main__':
    main()
