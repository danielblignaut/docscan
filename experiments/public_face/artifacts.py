"""Pin one executable per top-level run; guard models without copying weights.

Concurrent rebuilds may replace the original executable after acquisition. They
must never affect shards, later passes, cache keys, or report provenance. Model
changes abort instead: check bytes and file identity before/after inference and
before publishing caches/reports. This is a change detector, not a filesystem
lock against a malicious writer.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import tempfile


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def fingerprint(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def model_state(directory):
    paths = sorted(directory.glob('*.onnx'))
    if not paths:
        raise ValueError('No ONNX models found')
    before = {p.name: fingerprint(p) for p in paths}
    hashes = {p.name: digest(p) for p in paths}
    after = {p.name: fingerprint(p) for p in sorted(directory.glob('*.onnx'))}
    if before != after:
        raise ValueError('Models changed while hashing')
    return hashes, after


@dataclass(frozen=True)
class RunArtifacts:
    binary: Path
    binary_sha256: str
    models_dir: Path
    model_hashes: dict
    model_fingerprints: dict

    def verify(self):
        if digest(self.binary) != self.binary_sha256:
            raise ValueError('Executable snapshot corrupted')
        if model_state(self.models_dir) != (self.model_hashes, self.model_fingerprints):
            raise ValueError('Models changed during evaluation')

    @contextmanager
    def staged_output(self, destination, suffixes=('',)):
        """Failed/changed-input runs must not leave reusable partial caches."""
        self.verify()
        with tempfile.TemporaryDirectory(prefix='.pending-', dir=destination.parent) as tmp:
            output = Path(tmp) / destination.name
            yield output
            self.verify()
            for suffix in suffixes:
                Path(str(output) + suffix).replace(Path(str(destination) + suffix))


@contextmanager
def pinned_run(binary, models):
    """Copy exactly once, reject a source-copy race, and remove the private copy."""
    # Keep the supplied path (including a symlink) so replacement during the
    # copy is visible. A hard link would still share in-place rebuild writes.
    binary, models = Path(binary).absolute(), Path(models).absolute()
    with tempfile.TemporaryDirectory(prefix='public-face-executable-') as tmp:
        snapshot = Path(tmp) / 'face'
        before = fingerprint(binary)
        expected = digest(binary)
        shutil.copyfile(binary, snapshot)
        copied = digest(snapshot)
        after_hash = digest(binary)
        if before != fingerprint(binary) or expected != copied or expected != after_hash:
            raise ValueError('Executable source changed while copying')
        snapshot.chmod(0o500)
        hashes, fingerprints = model_state(models)
        artifacts = RunArtifacts(snapshot, copied, models, hashes, fingerprints)
        artifacts.verify()
        yield artifacts
        artifacts.verify()
