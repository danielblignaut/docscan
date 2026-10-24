#!/usr/bin/env python3
"""Read-only hash/permission/denominator audit plus paired burst regressions."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import stat

from run import HERE, REPO, sha, write, load_documents, load_camera, fields_for, score, idscore


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results', type=Path, default=HERE/'results-v1.json')
    p.add_argument('--output', type=Path, default=HERE/'audit-v1.json')
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('refusing overwrite')
    report = json.loads(args.results.read_text())
    run = Path(report['private_run'])
    assert sha(run/'freeze.json') == report['freeze_sha256']
    freeze = json.loads((run/'freeze.json').read_text())
    assert datetime.fromisoformat(freeze['frozen_utc']) < datetime.fromisoformat(report['completed_utc'])
    assert freeze['effective_train'] == []
    for relative, digest in freeze['source_hashes'].items():
        assert sha(REPO/relative) == digest
    for asset in freeze['assets'].values():
        assert sha(asset['path']) == asset['sha256']
    # Only enumerate this run's own private tree, never an upstream data tree.
    for path in [run.parent, run, *run.rglob('*')]:
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, str(path)
    outputs = {}
    for key, entry in freeze['unique_inputs'].items():
        assert sha(entry['path']) == entry['sha256']
        path = run/'predictions'/f'{key}.json'
        assert path.stat().st_mtime_ns > (run/'freeze.json').stat().st_mtime_ns
        assert sha(path) == report['raw_hashes'][key]
        outputs[key] = json.loads(path.read_text())
    assert len(outputs) == report['unique_inferences']
    assert len(freeze['documents']) == 60*5*3
    assert len(freeze['camera']) == 18*3
    assert len(freeze['negatives']) == 6*3
    samples, records = load_documents(), load_camera()
    groups = defaultdict(list)
    for e in freeze['documents']:
        s = samples[e['index']]
        groups[(s['source'], e['condition'], e['arm'])].append(e)
    cells = 0
    for key, entries in groups.items():
        assert len({e['index'] for e in entries}) == len(entries)
        assert len(entries) == (10 if key[0] == 'bankstatemently' else 50)
        scored = [f for e in entries for f in fields_for(samples[e['index']], outputs[e['key']]['output'])]
        r = report['documents']['/'.join(key)]
        for field in ('truth_tokens', 'matched_tokens', 'predicted_tokens'):
            assert sum(f[field] for f in scored) == r[field]
        assert sum(f['exact'] for f in scored) == r['exact']
        assert len(scored) == r['items']
        assert sum(bool(outputs[e['key']]['failure']) for e in entries) == r['failures']
        assert r['truth_tokens'] == (2639 if key[0] == 'bankstatemently' else 3196)
        cells += 1
    for arm in ('baseline', 'global_exposure', 'local_illumination'):
        entries = [e for e in freeze['camera'] if e['arm'] == arm]
        assert sorted(e['index'] for e in entries) == list(range(18))
        by_id = {records[e['index']]['id']: outputs[e['key']]['output'] for e in entries}
        positive, exact, wrong, negative_accepts, fields, abstain = 0, 0, 0, 0, 0, 0
        for record in records:
            wanted = idscore.expected(record)
            out = by_id[record['id']]
            accepted = out.get('accepted', False)
            assert isinstance(accepted, bool)
            correct_fields = [out.get('mrz', {}).get(k) == v for k, v in wanted.items()] if wanted and isinstance(out.get('mrz'), dict) else [False]*10 if wanted else []
            correct = bool(wanted) and all(correct_fields) and out.get('kind') == 'other_passport'
            positive += bool(wanted)
            exact += accepted and correct
            wrong += accepted and not correct
            negative_accepts += accepted and wanted is None
            fields += sum(correct_fields)
            abstain += not accepted
        r = report['camera'][arm]
        assert (positive, exact, wrong, negative_accepts, fields, abstain) == (
            r['passport_frames'], r['accepted_correct'], r['accepted_wrong'], r['negative_false_accepts'], r['mrz_fields_correct'], r['abstentions'])
    detail = json.loads((run/'burst-document-private.json').read_text())
    burst = defaultdict(Counter)
    for entry in detail:
        sample = samples[entry['index']]
        before = fields_for(sample, outputs[entry['first']]['output'])
        after = fields_for(sample, outputs[entry['selected']]['output'])
        d = burst[sample['source']]
        d['bursts'] += 1
        d['exact_regions_gained'] += sum(not a['exact'] and b['exact'] for a, b in zip(before, after))
        d['exact_regions_lost'] += sum(a['exact'] and not b['exact'] for a, b in zip(before, after))
        delta = sum(f['matched_tokens'] for f in after)-sum(f['matched_tokens'] for f in before)
        d['token_gain_pages'] += delta > 0
        d['token_loss_pages'] += delta < 0
        d['first_failures'] += bool(outputs[entry['first']]['failure'])
        d['selected_failures'] += bool(outputs[entry['selected']]['failure'])
    before = json.loads((run/'burst-camera-first-private.json').read_text())['items']
    after = json.loads((run/'burst-camera-selected-private.json').read_text())['items']
    assert len(before) == len(after) == 9
    # Score camera transitions by specimen+session, regardless of selected frame.
    record_by_id = {r['id']: r for r in records}
    def session(item):
        r = record_by_id[item['id']]
        return r['layout'], r['condition']
    a, b = {session(i): i for i in before}, {session(i): i for i in after}
    assert set(a) == set(b)
    camera = {'bursts': 9,
        'correct_accepts_gained': sum(not a[k]['accepted_correct'] and b[k]['accepted_correct'] for k in a),
        'correct_accepts_lost': sum(a[k]['accepted_correct'] and not b[k]['accepted_correct'] for k in a),
        'new_wrong_accepts': sum(not a[k]['accepted_wrong'] and b[k]['accepted_wrong'] for k in a),
        'wrong_accepts_removed': sum(a[k]['accepted_wrong'] and not b[k]['accepted_wrong'] for k in a)}
    result = {'passed': True, 'source_sha256': sha(__file__), 'accuracy_report_sha256': sha(args.results),
              'document_cells_checked': cells, 'camera_arms_checked': 3,
              'unique_prediction_hashes_checked': len(outputs), 'private_permissions': True,
              'fixed_document_denominators_per_arm_condition': {'bank_tokens': 2639, 'invoice_tokens': 3196, 'bank_pages': 10, 'invoice_regions': 560},
              'burst_paired_regressions': {'documents': dict(burst), 'camera': camera}}
    write(args.output, result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
