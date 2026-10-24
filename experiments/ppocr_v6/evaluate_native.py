"""Score the optional Rust/RTen engine against the frozen 12-page synthetic DEV corpus.

Reuses the original generator and scorer, verifies every image hash, and
keeps geometry/text outputs. Does not alter the existing baseline report.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, default=ROOT / 'docscan/target/release/examples/text_v6')
p.add_argument('--scorer', type=Path, default=ROOT / 'eval/text_eval.py')
p.add_argument('--data', type=Path, default=Path('/tmp/docscan-text-dev'))
p.add_argument('--out', type=Path, required=True)
p.add_argument('--jobs', type=int, default=2, choices=[1, 2])
p.add_argument('--detail', action='store_true')
args = p.parse_args()

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

spec = importlib.util.spec_from_file_location('text_dev_scorer', args.scorer)
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)
baseline = json.loads((args.data / 'results.json').read_text())
assert baseline['synthetic_only'] and baseline['protocol'] == 'general-text-dev-v1'
hashes = {r['sample']: r['sha256'] for r in baseline['rows']}
with tempfile.TemporaryDirectory(prefix='ppocr-native-dev-') as folder:
    samples = scorer.generate(Path(folder))
    assert len(samples) == len(hashes) == 12
    for name, image, truth in samples:
        assert digest(image) == hashes[name] == digest(args.data / f'{name}.png'), name
binary = args.binary.resolve()
result = subprocess.run([str(binary), *(['--detail'] if args.detail else []), *[str(args.data / f'{name}.png') for name, _, _ in samples]],
                        capture_output=True, text=True, check=True, timeout=180,
                        env={**os.environ, 'RTEN_NUM_THREADS': str(args.jobs), 'RAYON_NUM_THREADS': str(args.jobs)})
outputs = [json.loads(line) for line in result.stdout.splitlines()]
assert len(outputs) == len(samples)
rows = []
for (name, _, truth), output in zip(samples, outputs):
    assert 'error' not in output, output
    expected, actual = scorer.normalized(truth), scorer.normalized(output['text'])
    a, b = Counter(expected.split()), Counter(actual.split())
    rows.append({'sample': name, 'sha256': hashes[name], 'characters': len(expected),
                 'edits': scorer.distance(expected, actual), 'words': sum(a.values()),
                 'correct_words': sum((a & b).values()), 'extra_words': sum((b - a).values()), 'output': output})
summary = {'cer': sum(r['edits'] for r in rows) / sum(r['characters'] for r in rows),
           'word_recall': sum(r['correct_words'] for r in rows) / sum(r['words'] for r in rows),
           'extra_words': sum(r['extra_words'] for r in rows),
           'mean_ms_unpaired': sum(r['output']['timings_ms']['total'] for r in rows) / len(rows)}
report = {'protocol': 'general-text-dev-v1-ppocr-native', 'synthetic_only': True,
          'runtime': 'RTen0.26 native, Rust preprocessing/DB/CTC; not browser', 'threads': args.jobs,
          'binary_sha256': digest(binary), 'detail': args.detail, 'source_scorer_sha256': digest(args.scorer),
          'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
          'model_manifest': json.loads((ROOT / 'scripts/ppocr-v6-models.json').read_text()),
          'summary': summary, 'rows': rows, 'baseline': baseline,
          'limitations': 'Only twelve synthetic English pages. Single-pass unpaired timings do not establish a speedup or phone latency.'}
args.out.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(summary, indent=2))
