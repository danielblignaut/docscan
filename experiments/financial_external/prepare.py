#!/usr/bin/env python3
"""Build and freeze the private gold set for financial-external-v1, before any inference.

Verifies every source against existing pins, writes owner-private gold and an input list under
DATA/financial-external-v1, snapshots the baseline extractor, and writes freeze.json (hashes, ids and
counts only) beside this file. Refuses to overwrite an existing freeze.
"""
from __future__ import annotations
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = Path(os.environ.get('DOCSCAN_PUBLIC_DATA', '/tmp/docscan-public-data'))
ROOT = DATA / 'financial-external-v1'
POA = DATA / 'poa-synthesized-v1'
BANK = DATA / 'bankstatemently'
FATURA = DATA / 'fatura'
TRANSCRIPTIONS = ROOT / 'gold-transcription'
SYNTH_RENDERS = {  # pinned here, before inference; renders were made by experiments/public_poa (PyMuPDF 150 dpi)
    'clean': 'baf86f309009c6c9195c3e0cbb26655ff89c017f04b58751139931712932e6c9',
    'scanned': '9976a8b5c0a12117ff35bdb578ff18c80b9fb4386c4ff51a9cb1b60a67abd08a',
    'fax': 'd1bc055f6b9e26628ea9517c1ff734169b6def6cb32d5f79cbdd16ee8d218597',
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def money(value) -> str:
    # Publisher JSON uses floats; repr is the shortest exact round-trip, then two decimals.
    return str(Decimal(repr(value)).quantize(Decimal('0.01')))


def need(path: Path, sha: str) -> Path:
    if digest(path) != sha:
        raise ValueError(f'{path.name} differs from its pin')
    return path


def synthesized():
    pins = json.loads((REPO / 'experiments/public_poa/source-pins.json').read_text())
    truth = json.loads(need(POA / 'truth.json', pins['truth.json']['sha256']).read_text())
    if truth['_meta']['synthetic'] is not True:
        raise ValueError('Synthesized truth is not marked synthetic')
    for name in ('clean', 'scanned', 'fax'):
        need(POA / f'{name}.pdf', pins[f'{name}.pdf']['sha256'])
        need(POA / f'{name}.png', SYNTH_RENDERS[name])
    tx, balances = truth['transactions'], truth['running_balances']
    if len(tx) != len(balances):
        raise ValueError('Transactions and running balances differ in length')
    rows = [{'date': t['date'], 'alt_date': t['date'], 'description': [t['description']], 'amount': money(t['amount']),
             'balance': money(b)} for t, b in zip(tx, balances)]
    opening, closing = money(truth['opening_balance']), money(truth['closing_balance'])
    running = Decimal(opening)
    for row in rows:  # Gold self-consistency, from the annotation alone.
        running += Decimal(row['amount'])
        if running != Decimal(row['balance']):
            raise ValueError('Synthesized running balances do not close')
    if running != Decimal(closing):
        raise ValueError('Synthesized closing does not close')
    table = {'kind': 'bank', 'rows': rows, 'has_balance': True,
             'summary': {'opening': opening, 'closing': closing, 'total_credits': money(truth['total_deposits']),
                         'total_debits': money(truth['total_withdrawals'])}}
    docs = []
    for name in ('clean', 'scanned', 'fax'):
        docs.append({'set': 'synthesized', 'id': f'synth-{name}', 'kind': 'bank', 'tables': [table],
                     'images': [str(POA / f'{name}.png')],
                     'pdf': str(POA / 'clean.pdf') if name == 'clean' else None,
                     'source_sha256': {'truth': digest(POA / 'truth.json'), 'image': SYNTH_RENDERS[name]}})
    return docs


def bankstatemently():
    manifest = json.loads((REPO / 'experiments/public_documents/manifest.json').read_text())
    files = {r['path']: r['sha256'] for r in manifest['bankstatemently']['files']}
    ocr = json.loads((REPO / 'experiments/public_documents/ocr-dev-v1.json').read_text())
    renders = {s['id']: s['image_sha256'] for s in ocr['samples'] if s['source'] == 'bankstatemently'}
    docs = []
    for ident, expected_rows in (('bsb-001', 12), ('bsb-002', 15), ('bsb-003', 22)):
        pdf = need(BANK / f'datasets/basic/{ident}/{ident}-statement.pdf', files[f'datasets/basic/{ident}/{ident}-statement.pdf'])
        info = json.loads(need(BANK / f'datasets/basic/{ident}/statement-info.json', files[f'datasets/basic/{ident}/statement-info.json']).read_text())
        pages = sorted((p for p in renders if p.startswith(ident + '-p')), key=lambda p: int(p.split('-p')[1]))
        images = [str(need(BANK / 'rendered-dev-v1' / f'{p}.png', renders[p])) for p in pages]
        transcription = TRANSCRIPTIONS / f'{ident}.json'
        gold = json.loads(transcription.read_text())
        table = gold['tables'][0]
        rows = table['rows']
        if len(rows) != info['transactionCount'] or len(rows) != expected_rows:
            raise ValueError(f'{ident} transcription row count differs from publisher transactionCount')
        out = [{'date': r['date'], 'alt_date': r.get('alt_date', r['date']), 'description': r['description'],
                'amount': r['amount'], **({'balance': r['balance']} if 'balance' in r else {})} for r in rows]
        summary = {}
        if ident == 'bsb-002':  # Credit card: balances owed are printed positive; not mapped to account balances.
            closing = Decimal(table['opening']['balance_owed']) - sum(Decimal(r['amount']) for r in out)
            if closing != Decimal(table['closing']['balance_owed']):
                raise ValueError('bsb-002 transcription does not close')
        else:
            opening, closing = table['opening']['balance'], table['closing']['balance']
            if Decimal(opening) + sum(Decimal(r['amount']) for r in out) != Decimal(closing):
                raise ValueError(f'{ident} transcription does not close')
            running = Decimal(opening)
            for r in out:
                running += Decimal(r['amount'])
                if 'balance' in r and running != Decimal(r['balance']):
                    raise ValueError(f'{ident} running balance does not close')
            summary = {'opening': opening, 'closing': closing, 'total_debits': table['closing']['total_debits'],
                       'total_credits': table['closing']['total_credits']}
        docs.append({'set': 'bankstatemently', 'id': ident, 'kind': 'bank',
                     'tables': [{'kind': table['kind'], 'rows': out, 'has_balance': all('balance' in r for r in out), 'summary': summary}],
                     'images': images, 'pdf': str(pdf),
                     'source_sha256': {'pdf': digest(pdf), 'transcription': digest(transcription), 'images': [digest(Path(i)) for i in images]}})
    return docs


NUMBER = re.compile(r'\d+(?:\.\d+)?')


def fatura(split: str):
    manifest = json.loads((REPO / 'experiments/public_documents/manifest.json').read_text())
    docs = []
    for row in manifest['fatura']['documents']:
        if row['split'] != split:
            continue
        image = need(FATURA / split / f"{row['id']}.jpg", row['image_sha256'])
        annotation = FATURA / split / f"{row['id']}.json"
        fields = json.loads(annotation.read_text())['fields']
        gold = {'subtotal': [], 'tax_total': [], 'discount': [], 'invoice_total': [], 'amount_due': []}
        for field in fields:
            label = field['label']
            key = ('subtotal' if label == 'SUB_TOTAL' else 'tax_total' if label == 'TAX' or label.startswith('GST(')
                   else 'discount' if label == 'DISCOUNT' else 'invoice_total' if label == 'TOTAL'
                   else 'amount_due' if label == 'AMOUNT_DUE' else None)
            if key:
                numbers = NUMBER.findall(field['text'])
                if not numbers:
                    raise ValueError(f"{row['id']} {label} has no number")
                gold[key].append(numbers[-1])
        if not gold['invoice_total'] and gold['amount_due']:
            gold['invoice_total'] = gold['amount_due'][:1]
        gold.pop('amount_due')
        arithmetic = None
        if len(gold['subtotal']) == 1 and len(gold['invoice_total']) == 1:
            expected = (Decimal(gold['subtotal'][0]) - sum(Decimal(v) for v in gold['discount'])
                        + sum(Decimal(v) for v in gold['tax_total']))
            arithmetic = 'consistent' if expected == Decimal(gold['invoice_total'][0]) else 'inconsistent'
        docs.append({'set': f'fatura_{split}', 'id': row['id'], 'kind': 'invoice', 'template': row['template'],
                     'invoice': {'summary': {k: v for k, v in gold.items() if v}, 'total_arithmetic': arithmetic},
                     'images': [str(image)], 'pdf': None,
                     'source_sha256': {'image': row['image_sha256'], 'annotation': digest(annotation)}})
    return docs


def snapshot_engine(dest: Path) -> str:
    src = REPO / 'demo/src/financial-tables'
    if dest.exists():
        raise ValueError('Baseline snapshot already exists')
    shutil.copytree(src, dest)
    return engine_digest(dest)


def engine_digest(folder: Path) -> str:
    # Same recipe as experiments/financial_tables/benchmark.mjs engineSha.
    parts = [f"{p.name}\n{p.read_text()}" for p in sorted(folder.glob('*.ts'))]
    return text_digest('\n'.join(parts))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.parse_args()
    os.umask(0o077)
    freeze_path = HERE / 'freeze.json'
    if freeze_path.exists():
        raise ValueError('Refusing to overwrite freeze.json; version a new protocol instead')
    docs = synthesized() + bankstatemently() + fatura('dev') + fatura('train')
    gold_path = ROOT / 'gold.json'
    gold_path.write_text(json.dumps({'protocol': 'financial-external-v1', 'documents': docs}, indent=1, ensure_ascii=False) + '\n')
    engine = snapshot_engine(ROOT / 'engines' / 'baseline')
    counts = {}
    for d in docs:
        c = counts.setdefault(d['set'], {'documents': 0, 'pages': 0, 'gold_rows': 0, 'summary_opportunities': 0})
        c['documents'] += 1
        c['pages'] += len(d['images'])
        if d['kind'] == 'bank':
            c['gold_rows'] += sum(len(t['rows']) for t in d['tables'])
            c['summary_opportunities'] += sum(len(t['summary']) for t in d['tables'])
        else:
            c['summary_opportunities'] += sum(len(v) for v in d['invoice']['summary'].values())
    fatura_arith = {s: {k: sum(1 for d in docs if d['set'] == s and d['invoice']['total_arithmetic'] == k)
                        for k in ('consistent', 'inconsistent', None)} for s in ('fatura_dev', 'fatura_train')}
    freeze = {
        'protocol': 'financial-external-v1',
        'protocol_sha256': digest(HERE / 'protocol.json'),
        'prepare_sha256': digest(Path(__file__)),
        'repository_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
        'gold_sha256': digest(gold_path),
        'baseline_engine_sha256': engine,
        'baseline_engine_source': 'demo/src/financial-tables at 0526c5d (copied to private snapshot)',
        'counts': counts,
        'fatura_gold_total_arithmetic': {s: {str(k): v for k, v in c.items()} for s, c in fatura_arith.items()},
        'documents': [{'set': d['set'], 'id': d['id'], 'pages': len(d['images']), 'source_sha256': d['source_sha256']} for d in docs],
    }
    freeze_path.write_text(json.dumps(freeze, indent=1) + '\n')
    print(json.dumps({'counts': counts, 'fatura_arith': freeze['fatura_gold_total_arithmetic'], 'engine': engine[:12]}, indent=1))


if __name__ == '__main__':
    main()
