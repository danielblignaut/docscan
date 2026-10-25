#!/usr/bin/env python3
"""Independent checks on the frozen gold and on scorer-v2 outputs. Writes aggregate counts only.

1. Gold text and sums: Bankstatemently transcriptions against publisher transactionCount, exact-decimal closure and
   line presence in the publisher text layer; Synthesized closure; FATURA annotation parse and total arithmetic.
2. No output outside gold: every emitted summary value of a mapped key that equals no gold value of its document.
3. FATURA TRAIN breakdown: each missed gold summary value classed by the shape of the OCR line carrying it.

Run with a Python that has pypdfium2 (experiments/public_documents/requirements.txt):
  /tmp/docscan-public-data/venv/bin/python -I experiments/financial_external/verify.py
"""
from __future__ import annotations
from collections import Counter
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DOCSCAN_PUBLIC_DATA', '/tmp/docscan-public-data'))
ROOT = DATA / 'financial-external-v1'
MAPPED = {'subtotal': ['subtotal'], 'tax_total': ['tax_total'], 'discount': ['discount'], 'invoice_total': ['invoice_total'],
          'opening': ['opening_balance', 'brought_forward'], 'closing': ['closing_balance', 'carried_forward'],
          'total_debits': ['total_debits'], 'total_credits': ['total_credits']}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def same(a, b) -> bool:
    try:
        return abs(Decimal(str(a))) == abs(Decimal(str(b)))
    except Exception:
        return False


def gold_checks(docs):
    import pypdfium2 as pdfium
    out = {}
    for d in docs:
        if d['set'] == 'bankstatemently':
            t = d['tables'][0]
            info = json.loads((DATA / 'bankstatemently/datasets/basic' / d['id'] / 'statement-info.json').read_text())
            with pdfium.PdfDocument(d['pdf']) as pdf:
                text = norm(' '.join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf))))
            lines = [x for r in t['rows'] for x in r['description'] + r.get('counterparty', [])]
            total = sum(Decimal(r['amount']) for r in t['rows'])
            s = t['summary']
            closes = (Decimal(s['opening']) + total == Decimal(s['closing'])) if s else None
            out[d['id']] = {'rows': len(t['rows']), 'publisher_transaction_count': info['transactionCount'],
                            'lines_checked': len(lines), 'lines_in_text_layer': sum(norm(x) in text for x in lines),
                            'opening_plus_movements_equals_closing': closes,
                            'debits_total_matches': (s and -sum(Decimal(r['amount']) for r in t['rows'] if Decimal(r['amount']) < 0) == Decimal(s['total_debits'])) or None,
                            'credits_total_matches': (s and sum(Decimal(r['amount']) for r in t['rows'] if Decimal(r['amount']) > 0) == Decimal(s['total_credits'])) or None}
        elif d['set'] == 'synthesized' and d['id'] == 'synth-clean':
            t = d['tables'][0]
            run, ok = Decimal(t['summary']['opening']), True
            for r in t['rows']:
                run += Decimal(r['amount'])
                ok &= run == Decimal(r['balance'])
            out['synthesized'] = {'rows': len(t['rows']), 'running_balances_close': ok, 'closing_matches': run == Decimal(t['summary']['closing'])}
    for split in ('fatura_dev', 'fatura_train'):
        fd = [d for d in docs if d['set'] == split]
        out[split] = {'documents': len(fd), 'opportunities': dict(Counter(k for d in fd for k, v in d['invoice']['summary'].items() for _ in v)),
                      'total_arithmetic': dict(Counter(str(d['invoice']['total_arithmetic']) for d in fd))}
    return out


def outside_gold(score_file: Path, gold):
    counts = Counter()
    for entry in json.loads(score_file.read_text()):
        g = gold[entry['id']]
        summary = g['invoice']['summary'] if g['kind'] == 'invoice' else g['tables'][0]['summary']
        values = [v for vs in summary.values() for v in ([vs] if isinstance(vs, str) else vs)]
        for f in entry['report']['summaryFields']:
            key = next((k for k, keys in MAPPED.items() if f['key'] in keys), None)
            if key is None or not f.get('value') or f['value'].get('status') != 'parsed':
                continue
            counts[g['set'] + '.emitted'] += 1
            if not any(same(f['value']['value'], v) for v in values):
                counts[g['set'] + '.outside_gold'] += 1
    return dict(counts)


def train_breakdown(score_file: Path, gold, ocr_dir: Path):
    cats = Counter()
    for entry in json.loads(score_file.read_text()):
        g = gold[entry['id']]
        if g['set'] != 'fatura_train':
            continue
        lines = [l['text'] for l in json.loads((ocr_dir / f"{g['id']}.p0.json").read_text())['lines']]
        for key, values in g['invoice']['summary'].items():
            for v in values:
                if any(f['key'] == key and f.get('value') and f['value'].get('status') == 'parsed' and same(f['value']['value'], v)
                       for f in entry['report']['summaryFields']):
                    cats['found'] += 1
                    continue
                esc = re.escape(v)
                line = next((l for l in lines if re.search(r'(^|[^\d.])' + esc + r'(?!\d)', l)), None)
                if line is None:
                    c = 'value_not_in_ocr'
                elif re.search(r'[A-Za-z)%]:' + esc, line):
                    c = 'glued_colon'
                elif re.search(r'[A-Za-z)%]: ' + esc, line):
                    c = 'colon_space'
                else:
                    c = 'other'
                if line and 'SUB_TOTAL' in line:
                    c += '+underscore'
                cats[f'{key}:{c}'] += 1
    return dict(sorted(cats.items()))


def main():
    freeze = json.loads((HERE / 'freeze.json').read_text())
    if digest(ROOT / 'gold.json') != freeze['gold_sha256']:
        raise ValueError('gold.json differs from freeze')
    docs = json.loads((ROOT / 'gold.json').read_text())['documents']
    gold = {d['id']: d for d in docs}
    ocr_dir = next((ROOT / 'ocr').iterdir())
    report = {'gold': gold_checks(docs), 'outside_gold': {}, 'fatura_train_breakdown': {}}
    for f in sorted((ROOT / 'scores-v2').glob('*.json')):
        report['outside_gold'][f.stem] = outside_gold(f, gold)
        if '-ocr-' in f.stem:
            report['fatura_train_breakdown'][f.stem] = train_breakdown(f, gold, ocr_dir)
    report['verify_sha256'] = digest(Path(__file__))
    (HERE / 'results/v2').mkdir(parents=True, exist_ok=True)
    (HERE / 'results/v2/verify.json').write_text(json.dumps(report, indent=1) + '\n')
    print(json.dumps(report['gold'], indent=1))
    print(json.dumps(report['outside_gold'], indent=1))


if __name__ == '__main__':
    main()
