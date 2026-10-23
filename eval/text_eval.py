#!/usr/bin/env python3
"""General OCR development smoke corpus, generated without personal documents.

Runs both legacy text OCR and page OCR in the same native binary. This is a
small synthetic DEV comparison, not a real-document or frontier benchmark.
Usage: /tmp/docscan-bench/venv/bin/python eval/text_eval.py --binary docscan/target/release/examples/text
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        nxt = [i]
        for j, y in enumerate(b, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = nxt
    return row[-1]


def normalized(s):
    return ' '.join(re.findall(r'[a-z0-9]+', s.lower()))


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    samples = []
    # Fictional prose, invoices, and compact numeric rows: unlike the ID and
    # address suites, this scores all text without document-specific rules.
    paragraphs = [
        ['DOCUMENT CAPTURE DEVELOPMENT SAMPLE', 'Please retain this page for your records.',
         'The delivery contains four blue folders and twelve pencils.',
         'Read the printed instructions before opening the package.',
         'Keep paper dry and store at room temperature.',
         'Questions can be answered at the reception desk.'],
        ['SAMPLE INVOICE', 'Reference INV-2048', 'Description Quantity Amount',
         'Paper notebooks 12 360.00', 'Blue folders 4 120.00',
         'Delivery charge 1 45.00', 'Total 525.00', 'Payment due 28 October 2026'],
    ]
    for family, lines in enumerate(paragraphs):
        for size in (14, 20, 28):
            for shaded in (False, True):
                name = f'family{family}-size{size}-{"shade" if shaded else "clean"}'
                image = Image.new('RGB', (1240, 1754), 'white')
                draw = ImageDraw.Draw(image)
                if shaded:
                    for y in range(image.height):
                        value = 180 + round(65 * y / image.height)
                        draw.line((0, y, image.width, y), fill=(value, value, value))
                font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', size)
                for i, line in enumerate(lines):
                    draw.text((95, 160 + i * (size + 18)), line, font=font, fill=(25, 25, 25))
                path = directory / f'{name}.png'
                image.save(path)
                samples.append((name, path, '\n'.join(lines)))
    return samples


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--out', type=Path, default=Path('/tmp/docscan-text-dev'))
    args = p.parse_args()
    samples = generate(args.out)
    rows = []
    for mode in ('legacy', 'page'):
        run = subprocess.run([str(args.binary.resolve()), f'--{mode}', *[str(s[1]) for s in samples]],
                             check=True, text=True, capture_output=True, timeout=900)
        outputs = [json.loads(line) for line in run.stdout.splitlines()]
        assert len(outputs) == len(samples)
        for (name, path, truth), output in zip(samples, outputs):
            expected, actual = normalized(truth), normalized(output['text'])
            a, b = Counter(expected.split()), Counter(actual.split())
            rows.append({'sample': name, 'mode': mode, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'characters': len(expected), 'edits': distance(expected, actual),
                         'words': sum(a.values()), 'correct_words': sum((a & b).values()),
                         'extra_words': sum((b - a).values()), 'ms': output['ms']})
    report = {'protocol': 'general-text-dev-v1', 'synthetic_only': True,
              'git': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(), 'rows': rows, 'summary': {}}
    for mode in ('legacy', 'page'):
        rs = [r for r in rows if r['mode'] == mode]
        report['summary'][mode] = {
            'cer': sum(r['edits'] for r in rs) / sum(r['characters'] for r in rs),
            'word_recall': sum(r['correct_words'] for r in rs) / sum(r['words'] for r in rs),
            'extra_words': sum(r['extra_words'] for r in rs),
            'mean_ms': sum(r['ms'] for r in rs) / len(rs)}
    (args.out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    main()
