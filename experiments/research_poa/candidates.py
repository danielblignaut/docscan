"""Experimental type-only postprocessors. No truth, customer or filename inputs."""
from collections import defaultdict
import re

VOCAB = [
    ('lease_agreement', ('lease', 'lessee', 'lessor', 'tenant', 'landlord', 'rental agreement'), 2),
    ('bank_statement', ('bank statement', 'opening balance', 'closing balance', 'branch code', 'transaction', 'cheque account', 'savings account', 'current account'), 1),
    ('municipal_account', ('municipal', 'municipality', 'rates', 'refuse', 'sewerage', 'property valuation', 'erf'), 1),
    ('cellphone_account', ('airtime', 'contract', 'data bundle', 'cellphone', 'mobile', 'sms', 'msisdn', 'sim'), 1),
    ('insurance_statement', ('policy', 'policyholder', 'premium', 'insurer', 'cover', 'insured'), 1),
    ('utility_bill', ('electricity', 'kwh', 'water', 'meter', 'prepaid', 'utility', 'consumption', 'units'), 1),
]
TITLES = {
    'bank_statement': ('bank statement', 'account statement', 'statement of account', 'statement of accounts'),
    'lease_agreement': ('lease agreement', 'rental agreement'),
    'municipal_account': ('municipal account', 'municipal statement'),
    'cellphone_account': ('cellphone account', 'mobile account'),
    'insurance_statement': ('insurance statement', 'insurance policy'),
    'utility_bill': ('utility bill', 'electricity bill', 'water bill'),
}


def keyword_type(text):
    """Port the shipped classifier, including substring counting and last tie."""
    text = text.lower()
    scores = [(sum(text.count(w) for w in ws) * weight, i, kind)
              for i, (kind, ws, weight) in enumerate(VOCAB)]
    score, _, kind = max(scores)
    return kind if score else 'other'


def header_lines(words, page_size, config):
    if not page_size or len(page_size) != 2 or page_size[1] <= 0:
        return []
    lines = defaultdict(list)
    for w in words or []:
        if w['h'] > 0 and 0 <= w['y'] + w['h'] / 2 <= config['header_fraction'] * page_size[1]:
            lines[w['line']].append(w)
    out = []
    for line in lines.values():
        text = ' '.join(w['text'] for w in sorted(line, key=lambda x: x['x']))
        if len(text.split()) <= config['max_line_words']:
            out.append((min(w['y'] for w in line), text))
    return [t for _, t in sorted(out)]


def classify(words, page_size, baseline, config):
    lines = header_lines(words, page_size, config)
    if config['mode'] == 'header_keywords':
        found = keyword_type('\n'.join(lines))
        return baseline if found == 'other' else found
    if config['mode'] != 'explicit_title':
        raise ValueError('Unknown candidate')
    found = set()
    for line in lines:
        text = ' ' + ' '.join(re.findall(r'\w+', line.casefold())) + ' '
        for kind, phrases in TITLES.items():
            if any(' ' + p + ' ' in text for p in phrases):
                found.add(kind)
    return next(iter(found)) if len(found) == 1 else baseline
