# Portions adapted from PaddleX inference preprocessing and DB geometry.
# Copyright (c) 2024 PaddlePaddle Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# Modified for this bounded experiment: standalone ONNX Runtime execution,
# simplified DB postprocessing, frozen DEV scoring, and provenance recording.
"""Bounded PP-OCRv6 native CPU feasibility experiment; synthetic DEV only.

Uses official pinned ONNX artifacts and their YAML preprocessing/dictionary.
DB geometry and crop conventions follow PaddleX's Apache-2.0 inference code;
see README.md for source revision and attribution. Does not alter docscan.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import time

import cv2
import numpy as np
import onnxruntime as ort
import pyclipper
import yaml


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rectangle(contour):
    rect = cv2.minAreaRect(np.asarray(contour, dtype=np.float32))
    points = sorted(cv2.boxPoints(rect), key=lambda p: p[0])
    left = sorted(points[:2], key=lambda p: p[1])
    right = sorted(points[2:], key=lambda p: p[1])
    return np.array([left[0], right[0], right[1], left[1]], np.float32), min(rect[1])


def box_score(probability, box):
    x0, y0 = np.maximum(np.floor(box.min(axis=0)).astype(int), 0)
    x1, y1 = np.minimum(np.ceil(box.max(axis=0)).astype(int), [probability.shape[1] - 1, probability.shape[0] - 1])
    mask = np.zeros((y1 - y0 + 1, x1 - x0 + 1), np.uint8)
    cv2.fillPoly(mask, [np.round(box - [x0, y0]).astype(np.int32)], 1)
    return cv2.mean(probability[y0:y1 + 1, x0:x1 + 1], mask)[0]


def crop(image, box):
    width = max(int(np.linalg.norm(box[0] - box[1])), int(np.linalg.norm(box[2] - box[3])), 1)
    height = max(int(np.linalg.norm(box[0] - box[3])), int(np.linalg.norm(box[1] - box[2])), 1)
    destination = np.array([[0, 0], [width, 0], [width, height], [0, height]], np.float32)
    warped = cv2.warpPerspective(image, cv2.getPerspectiveTransform(box, destination), (width, height),
                                 flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return np.rot90(warped) if height / width >= 1.5 else warped


class Pipeline:
    def __init__(self, models, tier, threads):
        self.configs = {task: yaml.safe_load((models / f'{tier}_{task}' / 'inference.yml').read_text()) for task in ('det', 'rec')}
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.sessions = {task: ort.InferenceSession(str(models / f'{tier}_{task}' / 'inference.onnx'), options,
                                                   providers=['CPUExecutionProvider']) for task in ('det', 'rec')}
        self.characters = ['blank'] + self.configs['rec']['PostProcess']['character_dict'] + [' ']
        self.inputs = {}

    def infer(self, task, array):
        array = np.ascontiguousarray(array, dtype=np.float32)
        self.inputs[task] = array
        return self.sessions[task].run(None, {'x': array})[0]

    def detect(self, image, limit):
        h, w = image.shape[:2]
        ratio = min(1.0, limit / max(h, w))
        nh, nw = [max(32, int(round(int(size * ratio) / 32) * 32)) for size in (h, w)]
        resized = cv2.resize(image, (nw, nh)).astype(np.float32)
        norm = next(v['NormalizeImage'] for v in self.configs['det']['PreProcess']['transform_ops'] if 'NormalizeImage' in v)
        data = (resized / 255 - np.array(norm['mean'], np.float32)) / np.array(norm['std'], np.float32)
        probability = self.infer('det', data.transpose(2, 0, 1)[None])[0, 0]
        post = self.configs['det']['PostProcess']
        contours, _ = cv2.findContours((probability > post['thresh']).astype(np.uint8) * 255, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours[:post['max_candidates']]:
            box, side = rectangle(contour)
            if side < 3 or box_score(probability, box) < post['box_thresh']:
                continue
            perimeter = cv2.arcLength(box, True)
            if perimeter <= 0:
                continue
            offset = pyclipper.PyclipperOffset()
            offset.AddPath(box, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
            expanded = offset.Execute(cv2.contourArea(box) * post['unclip_ratio'] / perimeter)
            if len(expanded) != 1:
                continue
            box, side = rectangle(expanded[0])
            if side < 5:
                continue
            box[:, 0] = np.clip(np.round(box[:, 0] * w / probability.shape[1]), 0, w)
            box[:, 1] = np.clip(np.round(box[:, 1] * h / probability.shape[0]), 0, h)
            boxes.append(box)
        boxes.sort(key=lambda b: (b[0, 1], b[0, 0]))
        # The upstream reading-order convention: nearby text on the same row
        # sorts left to right. No corpus truth participates in this decision.
        for i in range(1, len(boxes)):
            j = i
            while j > 0 and abs(boxes[j][0, 1] - boxes[j - 1][0, 1]) < 10 and boxes[j][0, 0] < boxes[j - 1][0, 0]:
                boxes[j], boxes[j - 1] = boxes[j - 1], boxes[j]
                j -= 1
        return boxes

    def recognize(self, patch):
        _, height, width = next(v['RecResizeImg']['image_shape'] for v in self.configs['rec']['PreProcess']['transform_ops'] if 'RecResizeImg' in v)
        ratio = patch.shape[1] / patch.shape[0]
        target = min(3200, int(height * max(width / height, ratio)))
        resized_width = min(target, math.ceil(height * ratio))
        data = cv2.resize(patch, (resized_width, height)).astype(np.float32).transpose(2, 0, 1) / 127.5 - 1
        padded = np.zeros((1, 3, height, target), np.float32)
        padded[0, :, :, :resized_width] = data
        scores = self.infer('rec', padded)[0]
        assert scores.shape[-1] == len(self.characters)
        indices = scores.argmax(axis=-1)
        keep = [i for i, token in enumerate(indices) if token != 0 and (i == 0 or token != indices[i - 1])]
        return ''.join(self.characters[indices[i]] for i in keep)

    def __call__(self, image, limit):
        return '\n'.join(self.recognize(crop(image, b)) for b in self.detect(image, limit))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--models', type=Path, default=Path('/tmp/docscan-ppocr-v6'))
    p.add_argument('--data', type=Path, default=Path('/tmp/docscan-text-dev'))
    p.add_argument('--scorer', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--jobs', type=int, default=2, choices=[1, 2])
    args = p.parse_args()
    spec = importlib.util.spec_from_file_location('frozen_text_dev', args.scorer)
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    baseline = json.loads((args.data / 'results.json').read_text())
    assert baseline['protocol'] == 'general-text-dev-v1' and baseline['synthetic_only']
    hashes = {r['sample']: r['sha256'] for r in baseline['rows']}
    with tempfile.TemporaryDirectory(prefix='ppocr-dev-truth-') as temporary:
        samples = scorer.generate(Path(temporary))
        assert len(samples) == 12
        for name, image, truth in samples:
            assert digest(image) == hashes[name] == digest(args.data / f'{name}.png'), name
        truths = {name: truth for name, _, truth in samples}
    rows = []
    provenance = json.loads((args.models / 'provenance.json').read_text())
    for kind, metadata in provenance.items():
        for name, file in metadata['files'].items():
            assert digest(args.models / kind / name) == file['sha256']
    for tier in ('tiny', 'small'):
        pipeline = Pipeline(args.models, tier, args.jobs)
        for limit in (960, 1754):
            for name in hashes:
                path = args.data / f'{name}.png'
                image = cv2.imread(str(path))
                start = time.perf_counter()
                text = pipeline(image, limit)
                ms = (time.perf_counter() - start) * 1000
                expected, actual = scorer.normalized(truths[name]), scorer.normalized(text)
                a, b = Counter(expected.split()), Counter(actual.split())
                rows.append({'sample': name, 'mode': f'{tier}-max{limit}', 'sha256': hashes[name],
                             'characters': len(expected), 'edits': scorer.distance(expected, actual),
                             'words': sum(a.values()), 'correct_words': sum((a & b).values()),
                             'extra_words': sum((b - a).values()), 'ms': ms, 'text': text})
                print(tier, limit, name, 'CER', round(rows[-1]['edits'] / len(expected), 4), round(ms), flush=True)
            # Keep actual preprocessed tensors for separate RTen parity checks.
            for task, array in pipeline.inputs.items():
                target = args.models / f'{tier}_{task}' / 'real-input'
                array.tofile(str(target) + '.f32')
                target.with_suffix('.json').write_text(json.dumps(list(array.shape)))
    summary = {}
    for mode in sorted(set(r['mode'] for r in rows)):
        rs = [r for r in rows if r['mode'] == mode]
        summary[mode] = {'cer': sum(r['edits'] for r in rs) / sum(r['characters'] for r in rs),
                         'word_recall': sum(r['correct_words'] for r in rs) / sum(r['words'] for r in rs),
                         'extra_words': sum(r['extra_words'] for r in rs),
                         'mean_ms_unpaired': sum(r['ms'] for r in rs) / len(rs)}
    report = {'protocol': 'general-text-dev-v1-ppocr-feasibility', 'synthetic_only': True,
              'runtime': 'ONNX Runtime CPU, native; not browser', 'threads': args.jobs,
              'onnxruntime': ort.__version__, 'opencv': cv2.__version__, 'numpy': np.__version__,
              'source_scorer_sha256': digest(args.scorer), 'source_baseline': baseline,
              'models': provenance, 'rows': rows, 'summary': summary,
              'limitations': 'Only 12 synthetic pages. Latencies are one uncalibrated pass, not paired with baseline; no speed claim.'}
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
