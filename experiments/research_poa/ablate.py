"""Freeze then run attribution diagnostics on immutable round-one outputs."""
import argparse
from collections import Counter
import copy
import datetime
import json
import os
from pathlib import Path
import sys
from candidates import keyword_type
from run import sha, summarize, type_row, write

HERE = Path(__file__).resolve().parent


def page_text(words):
    out = ''; last = None
    for word in words:
        if last is not None:
            out += '\n' if last != word['line'] else ' '
        out += word['text']; last = word['line']
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['freeze', 'run'])
    p.add_argument('--build-root', type=Path, required=True)
    p.add_argument('--first-run', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    os.umask(0o077)
    if args.out.resolve().is_relative_to(HERE.parents[1]):
        raise ValueError('Use private output outside repo')
    if args.action == 'freeze':
        args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
        record = {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'script_sha256': sha(__file__), 'inputs': {p.name: sha(p) for p in
            [args.first_run / 'report.json', *args.first_run.glob('*-raw.json')]},
            'hypotheses': ['header_keywords using only shipped first picked frame',
                'explicit_title using only shipped first picked frame',
                'majority voting alone on unchanged baseline frame types'],
            'no_retuning': 'Original header_fraction, max_line_words, vocabulary and title list unchanged.',
            'diagnostics': ['Parity using shipped line separators, not space-concatenated text',
                'All non-type fields, picked frames and verifier outputs equal baseline',
                'Every native result complete; no failed process earns rejection credit']}
        write(args.out / 'freeze.json', record)
        return
    record = json.loads((args.out / 'freeze.json').read_text())
    assert record['script_sha256'] == sha(__file__)
    for name, digest in record['inputs'].items(): assert sha(args.first_run / name) == digest
    if (args.out / 'report.json').exists(): raise ValueError('Never overwrite a completed round')
    sys.path.insert(0, str(args.build_root / 'source/eval'))
    import poa_extraction_dev as dev
    _, caps, truths, pages = dev.load_frozen_dev()
    first = json.loads((args.first_run / 'report.json').read_text())
    raw = json.loads((args.first_run / 'synthetic-baseline-raw.json').read_text())
    assert raw['error'] is None
    baseline = raw['outputs']; assert len(baseline) == 200
    parity = []; complete_capture = []; complete_frame = []
    for cap in caps:
        b = baseline[cap['id']]
        assert len(b['frames']) == 4
        complete_capture.append(isinstance(b['capture'].get('verify', {}).get('accepted'), bool))
        for i, f in enumerate(cap['frames']):
            result = b['frames'][i]
            complete_frame.append(isinstance(result.get('verify', {}).get('accepted'), bool))
            parity.append(keyword_type(page_text(pages[f['path']]['words'])) == result['fields']['document_type'])
    assert all(complete_capture + complete_frame)
    report = {'freeze': record, 'keyword_port_exact_parity': {'matched': sum(parity), 'denominator': len(parity)},
        'native_validity': {'captures': sum(complete_capture), 'capture_denominator':200,
                            'frames':sum(complete_frame),'frame_denominator':800}, 'candidates': {}}
    for kind in ['header_keywords', 'explicit_title', 'voting_only']:
        actual = baseline if kind == 'voting_only' else json.loads((args.first_run / (kind+'-raw.json')).read_text())['synthetic']
        rows = []; invariant = []
        for cap in caps:
            cid = cap['id']; b = baseline[cid]; a = actual[cid]
            wanted = truths[cid]['fields']['document_type']; picked = b['capture']['picked']
            btype = b['capture']['fields']['document_type']
            if kind == 'voting_only':
                votes = Counter(b['frames'][i]['fields']['document_type'] for i in picked)
                top, n = votes.most_common(1)[0]
                ctype = top if n > len(picked) / 2 else btype
            else:
                ctype = a['frames'][picked[0]]['fields']['document_type']
                unchanged = copy.deepcopy(a)
                unchanged['capture']['fields']['document_type'] = btype
                for i in range(4): unchanged['frames'][i]['fields']['document_type'] = b['frames'][i]['fields']['document_type']
                invariant.append(unchanged == b)
            rows.append(type_row(cid, wanted, btype, ctype))
        assert all(invariant)
        report['candidates'][kind + ('_first_picked' if kind != 'voting_only' else '')] = {
            **summarize(rows), 'non_type_invariants_checked':len(invariant), 'non_type_invariants_equal':sum(invariant)}
    write(args.out / 'report.json', report)
    print(json.dumps({k:{a:b for a,b in v.items() if a!='items'} for k,v in report['candidates'].items()},indent=2))

if __name__ == '__main__': main()
