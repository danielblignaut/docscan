"""Synthetic executables/media only: rebuilds must not change a running referee."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import evaluate
import artifacts
import active_replay
import pad_sample
import temporal_replay
from test_active_replay import trial


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.binary = self.root / 'face'
        self.binary.write_bytes(b'original executable')
        self.models = self.root / 'models'
        self.models.mkdir()
        self.model = self.models / 'synthetic.onnx'
        self.model.write_bytes(b'model')

    def test_source_copy_race_and_corrupt_copy_reject_before_use(self):
        copyfile = artifacts.shutil.copyfile
        for mode in ('replace', 'rewrite', 'corrupt-copy'):
            with self.subTest(mode=mode):
                def racing_copy(source, dest):
                    copyfile(source, dest)
                    if mode == 'replace':
                        other = self.root / 'replacement'
                        other.write_bytes(source.read_bytes())
                        other.replace(source)  # Even identical bytes changed identity.
                    elif mode == 'rewrite':
                        source.write_bytes(b'rebuilt executable')
                    else:
                        dest.write_bytes(b'corrupted copy')

                with patch.object(artifacts.shutil, 'copyfile', side_effect=racing_copy):
                    with self.assertRaisesRegex(ValueError, 'source changed'):
                        with artifacts.pinned_run(self.binary, self.models):
                            self.fail('Racing/corrupt acquisition was used')

    def test_snapshot_corruption_rejects_and_cleans_up(self):
        with self.assertRaisesRegex(ValueError, 'snapshot corrupted'):
            with artifacts.pinned_run(self.binary, self.models) as run:
                run.binary.chmod(0o700)
                run.binary.write_bytes(b'corruption')
                run.verify()
        self.assertFalse(run.binary.exists())

    def test_model_changes_never_publish_cache(self):
        for mode in ('rewrite', 'replace-identical', 'add', 'remove'):
            with self.subTest(mode=mode):
                self.model.write_bytes(b'model')
                (self.models / 'added.onnx').unlink(missing_ok=True)
                out = self.root / 'scores.json'
                with self.assertRaises((ValueError, FileNotFoundError)):
                    with artifacts.pinned_run(self.binary, self.models) as run:
                        with run.staged_output(out) as pending:
                            pending.write_text('[]')
                            if mode == 'rewrite':
                                self.model.write_bytes(b'changed')
                            elif mode == 'replace-identical':
                                replacement = self.root / 'replacement'
                                replacement.write_bytes(b'model')
                                replacement.replace(self.model)
                            elif mode == 'add':
                                (self.models / 'added.onnx').write_bytes(b'extra')
                            else:
                                self.model.unlink()
                self.assertFalse(out.exists())
                self.assertEqual(list(self.root.glob('.pending-*')), [])

    def test_interrupted_native_output_never_becomes_a_cache_hit(self):
        out = self.root / 'scores.json'
        with artifacts.pinned_run(self.binary, self.models) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                with run.staged_output(out) as pending:
                    pending.write_text('partial')
                    raise subprocess.CalledProcessError(1, 'synthetic')
            self.assertFalse(out.exists())


def executable(path, vector):
    path.write_text(f'''#!{sys.executable}
import json, pathlib, struct, sys
args = sys.argv
start = args.index('embed')
rows = pathlib.Path(args[start + 1]).read_text().splitlines()
out = pathlib.Path(args[start + 2])
i, jobs = map(int, args[args.index('--shard') + 1].split('/'))
n = len(rows) * (i + 1) // jobs - len(rows) * i // jobs
out.write_bytes(struct.pack('<2f', *{vector!r}) * n)
pathlib.Path(str(out) + '.json').write_text(json.dumps({{'dim': 2, 'items': [{{'found': True, 'quality': 1.}}] * n}}))
''')
    path.chmod(0o700)


class RunnerProvenanceTests(unittest.TestCase):
    def test_replay_runners_pin_launches_and_report_across_rebuilds(self):
        for module in (active_replay, temporal_replay, pad_sample):
            with self.subTest(runner=module.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                binary = root / 'face'
                binary.write_bytes(b'original')
                original_hash = artifacts.digest(binary)
                models = root / 'models/face'
                models.mkdir(parents=True)
                (models / 'minifasnet.onnx').write_bytes(b'model')
                source = root / 'docscan/src/face'
                source.mkdir(parents=True)
                (source / 'liveness.rs').write_text('synthetic')
                (source / 'antispoof.rs').write_text('pub const RAW_THRESHOLD: f32 = 0.59;\npub const SESSION_RAW_THRESHOLD: f32 = 0.78;')
                attacks = []
                for i in range(5):
                    media = root / f'{i}.synthetic'
                    media.write_bytes(b'synthetic')
                    attacks.append({'path': media.name, 'class': 'replay', 'sha256': artifacts.digest(media)})
                (root / 'manifest.json').write_text(json.dumps({'revision': module.REVISION, 'files': attacks}))
                rows = [{'path': 'synthetic', 'media': i, 'class': kind} for i, kind in enumerate(('genuine', 'replay'))]
                (root / 'protocol-v2.json').write_text(json.dumps(rows))
                launched = []

                def run(cmd, **kwargs):
                    launched.append(Path(cmd[0]))
                    self.assertEqual(artifacts.digest(Path(cmd[0])), original_hash)
                    replacement = root / 'replacement'
                    replacement.write_bytes(b'rebuilt')
                    replacement.replace(binary)
                    if module is active_replay:
                        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(trial()))
                    count = len(Path(cmd[-2]).read_text().splitlines())
                    Path(cmd[-1]).write_text(json.dumps([{'found': True, 'raw_real': .1}] * count))
                    return subprocess.CompletedProcess(cmd, 0)

                def clip(source, dest):
                    dest.write_bytes(b'synthetic clip')
                    return {'source_duration_s': 1., 'sampled_frames': 1}

                def video(source):
                    from unittest.mock import Mock
                    capture = Mock()
                    capture.get.side_effect = lambda key: 30. if key == temporal_replay.cv2.CAP_PROP_FPS else 3
                    capture.read.side_effect = [(True, np.zeros((4, 4, 3), dtype=np.uint8))] * 3 + [(False, None)]
                    return capture

                report = root / 'report.json'
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch.object(module, 'ROOT', root))
                    stack.enter_context(patch.object(module, 'DATA', root))
                    stack.enter_context(patch.object(module.subprocess, 'run', side_effect=run))
                    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    if module is active_replay:
                        stack.enter_context(patch.object(module, 'write_clip', side_effect=clip))
                    elif module is temporal_replay:
                        stack.enter_context(patch.object(module.cv2, 'VideoCapture', side_effect=video))
                    else:
                        stack.enter_context(patch.object(module, 'prepare', return_value=rows))
                    module.evaluate(binary, report)
                self.assertEqual(len(launched), 1 if module is pad_sample else 5)
                self.assertEqual(len(set(launched)), 1)
                self.assertNotEqual(launched[0], binary)
                self.assertEqual(json.loads(report.read_text())['binary_sha256'], original_hash)
                self.assertFalse(launched[0].exists())

    def test_production_pair_pins_binary_across_shards_passes_cache_and_report(self):
        parent = Path('/tmp/docscan-public-data')
        parent.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            root = Path(tmp)
            binary = root / 'face'
            executable(binary, [1., 0.])
            original_hash = evaluate.digest(binary)
            models = root / 'models/face'
            models.mkdir(parents=True)
            (models / 'synthetic.onnx').write_bytes(b'model')
            model_hashes = {'synthetic.onnx': evaluate.digest(models / 'synthetic.onnx')}
            (root / 'manifest.json').write_text('{"revision":"synthetic"}')
            (root / 'protocol-v1.json').write_text('[]')
            rows = [{'path': 'synthetic', 'split': 'validation', 'pose': pose,
                     'condition': 'original'} for pose in ('neutral', 'smile')]
            report = root / 'report.json'
            launched = []
            native_run = subprocess.run

            def run(cmd, **kwargs):
                launched.append(Path(cmd[0]))
                result = native_run(cmd, **kwargs)
                replacement = root / ('replacement-' + cmd[cmd.index('--shard') + 1].replace('/', '-'))
                executable(replacement, [0., 1.])
                replacement.replace(binary)
                return result

            scored = []

            def score(rows, vec, found):
                scored.append(vec.copy())
                return {}

            argv = ['evaluate', '--data', str(root), '--binary', str(binary),
                    '--variant', 'production-pair', '--jobs', '2', '--report', str(report)]
            with patch.object(sys, 'argv', argv), patch.object(evaluate, 'ROOT', root), \
                    patch.object(evaluate, 'prepare', return_value=rows), \
                    patch.object(evaluate, 'score', side_effect=score), \
                    patch.object(evaluate.subprocess, 'run', side_effect=run), \
                    contextlib.redirect_stdout(io.StringIO()):
                evaluate.main()
            result = json.loads(report.read_text())
            self.assertEqual(result['binary_sha256'], original_hash)
            self.assertEqual(len(launched), 4)
            self.assertEqual(len(set(launched)), 1)
            self.assertNotEqual(launched[0], binary)
            np.testing.assert_array_equal(scored[0], [[1., 0.], [1., 0.]])
            for name, variant in [('unflipped_live', 'iris'), ('flip_averaged_photo', 'flip')]:
                self.assertEqual(result['run'][name]['cache_key'],
                                 evaluate.cache_key(original_hash, model_hashes, rows, variant, 2))


if __name__ == '__main__':
    unittest.main()
