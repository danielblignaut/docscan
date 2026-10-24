"""Freeze then score private invented DEV probes with unchanged native/C1/C2."""
import argparse
from collections import Counter
import copy
import datetime
import json
import os
from pathlib import Path

from candidates import classify, keyword_type
from run import HERE, native, page_text, sha, summarize, type_row, write


def provenance(root, build):
    paths = [Path(__file__), HERE / 'candidates.py', HERE / 'protocol.json',
             HERE / 'candidate-freeze.json', HERE / 'run.py',
             root / 'stress_cases.json', root / 'stress_make_cases.py',
             build / 'build-source.json', build / 'source/models/poa-tagger.onnx',
             build / 'target/release/examples/poa_fields']
    original = json.loads((HERE / 'candidate-freeze.json').read_text())
    for name, digest in original['files'].items():
        assert sha(HERE / name) == digest
    prior = json.loads((build / 'run-02/freeze.json').read_text())
    assert sha(paths[-1]) == prior['binaries']['poa_fields']
    assert sha(paths[-2]) == prior['model_sha256']
    return {str(p.resolve()): sha(p) for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'run'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--build', type=Path, default=Path('/tmp/docscan-research-poa-v1'))
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root.resolve()
    assert root.is_relative_to('/tmp') and root.stat().st_mode & 0o077 == 0
    pins = provenance(root, args.build)
    rows = json.loads((root / 'stress_cases.json').read_text())
    assert len(rows) == 71 and len({r['id'] for r in rows}) == len(rows)
    assert {r['split'] for r in rows} == {'invented_DEV'}
    freeze_path = root / 'stress_freeze.json'
    if args.action == 'freeze':
        assert not freeze_path.exists()
        write(freeze_path, {
            'frozen_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'files': pins, 'count': len(rows),
            'groups': dict(Counter(r['group'] for r in rows)),
            'classes': dict(Counter(r['truth'] for r in rows)),
            'policy': 'Author-defined intent; coequal conflicting titles and unsupported documents are other. '
                      'No inference used to author probes. Baseline is original native rules type; '
                      'tagger agreement and Python port parity are audited. C1/C2 imported unchanged. '
                      'Single-page type only, no voting, no candidate tuning or original rescoring.',
            'metrics': 'Unchanged type_row/summarize exact, recovered/regressed and false-bank accounting. '
                       'Every row retained; missing native output fails and yields null, not other credit. '
                       'Report every prediction, class/group totals, confusion matrices, non-type invariants. '
                       'Separate designed counterexamples, never pooled with previous DEV scores.',
            'integration_gate': 'Any new regression, non-other unsupported/ambiguous outcome, or failure '
                                'on a supported class blocks integration recommendation. Passing would '
                                'still not establish real-world/OCR/security generalization.',
        })
        print(json.dumps({'frozen': sha(freeze_path), 'items': len(rows)}))
        return
    freeze = json.loads(freeze_path.read_text())
    assert pins == freeze['files'], 'Frozen inputs or implementation changed'
    assert not (root / 'stress_report.json').exists()
    # Only these two fields plus opaque id enter inference; never labels/groups.
    payload = [{k: r[k] for k in ('id', 'words', 'page_size')} for r in rows]
    output, error = native(args.build / 'target/release/examples/poa_fields',
                           args.build / 'source/models/poa-tagger.onnx', payload)
    write(root / 'stress_native_raw.json', {'output': output, 'error': error})
    configs = json.loads((HERE / 'protocol.json').read_text())['candidates']
    report = {'freeze': freeze, 'error': error, 'items': [], 'candidates': {}}
    invariants = []
    for row in rows:
        result = output.get(row['id'], {})
        fields = result.get('rules', {}).get('fields')
        base = fields.get('document_type') if fields else None
        valid = base is not None and error is None
        item = {k: row[k] for k in ('id', 'group', 'truth')}
        item.update(baseline=base, valid=valid,
                    native_tagger_agrees=valid and result.get('tagger', {}).get('fields', {}).get('document_type') == base,
                    port_agrees=valid and keyword_type(page_text(row['words'])) == base,
                    predictions={})
        for cfg in configs:
            prediction = classify(row['words'], row['page_size'], base, cfg) if valid else None
            item['predictions'][cfg['id']] = prediction
            if valid:
                modified = copy.deepcopy(result)
                for method in ('rules', 'tagger'):
                    modified[method]['fields']['document_type'] = prediction
                    modified[method]['fields']['document_type'] = result[method]['fields']['document_type']
                invariants.append(modified == result)
        report['items'].append(item)
    for cfg in configs:
        paired = [dict(type_row(r['id'], r['truth'], r['baseline'], r['predictions'][cfg['id']]),
                       group=r['group']) for r in report['items']]
        report['candidates'][cfg['id']] = summarize(paired)
        report['candidates'][cfg['id']]['by_group'] = {
            g: {k: v for k, v in summarize([r for r in paired if r['group'] == g]).items() if k != 'items'}
            for g in sorted({r['group'] for r in paired})}
        report['candidates'][cfg['id']]['by_class'] = {
            g: {k: v for k, v in summarize([r for r in paired if r['truth'] == g]).items() if k != 'items'}
            for g in sorted({r['truth'] for r in paired})}
        report['candidates'][cfg['id']]['confusion'] = dict(Counter(
            f"{r['truth']}->{r['candidate']}" for r in paired))
    report['baseline_confusion'] = dict(Counter(f"{r['truth']}->{r['baseline']}" for r in report['items']))
    report['audit'] = {k: sum(r[k] for r in report['items']) for k in ('valid', 'port_agrees', 'native_tagger_agrees')}
    report['audit'].update(denominator=len(rows), non_type_invariants_equal=sum(invariants),
                           non_type_invariants_checked=len(invariants))
    assert all(invariants)
    assert provenance(root, args.build) == pins
    report['completed_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write(root / 'stress_report.json', report)
    print(json.dumps({'audit': report['audit'], 'candidates': {
        k: {a: b for a, b in v.items() if a not in ('items', 'by_group', 'by_class', 'confusion')}
        for k, v in report['candidates'].items()}}, indent=2))


if __name__ == '__main__':
    main()
