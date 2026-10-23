"""Build the standalone probe against the project's already-built RTen rlibs."""
import argparse
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--deps', type=Path, default=root / 'docscan/target/release/deps')
p.add_argument('--out', type=Path, default=Path('/tmp/docscan-ppocr-v6/rten-probe'))
args = p.parse_args()
libs = {}
for crate in ('rten', 'rten_tensor'):
    candidates = list(args.deps.glob(f'lib{crate}-*.rlib'))
    if len(candidates) != 1:
        raise SystemExit(f'Expected one {crate} rlib in {args.deps}; build docscan first or supply a clean --deps directory')
    libs[crate] = candidates[0]
rustc = shutil.which('rustc') or str(Path.home() / '.cargo/bin/rustc')
args.out.parent.mkdir(parents=True, exist_ok=True)
subprocess.run([rustc, '--edition', '2024', str(Path(__file__).with_name('rten_probe.rs')), '-O',
                '-L', f'dependency={args.deps}', '--extern', f'rten={libs["rten"]}',
                '--extern', f'rten_tensor={libs["rten_tensor"]}', '-o', str(args.out)], check=True)
