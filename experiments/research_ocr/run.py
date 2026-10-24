#!/usr/bin/env python3
"""Research-only detector/recognizer capacity and sliced-inference ablations."""
import argparse
from collections import defaultdict
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = Path('/tmp/docscan-research-ocr')
MODELS = Path('/tmp/docscan-ppocr-v6')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


ref = module('reference_ocr', REPO/'experiments/ppocr_v6/evaluate.py')
score = module('frozen_document_scorer', REPO/'experiments/public_documents/evaluate.py')
PROTOCOL = json.loads((HERE/'protocol.json').read_text())


class MixedPipeline(ref.Pipeline):
    def __init__(self, detector, recognizer):
        tiers = {'det':detector, 'rec':recognizer}
        self.configs = {task:ref.yaml.safe_load((MODELS/f'{tier}_{task}/inference.yml').read_text()) for task,tier in tiers.items()}
        options = ref.ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.sessions = {task:ref.ort.InferenceSession(str(MODELS/f'{tier}_{task}/inference.onnx'), options, providers=['CPUExecutionProvider']) for task,tier in tiers.items()}
        self.characters = ['blank'] + self.configs['rec']['PostProcess']['character_dict'] + [' ']
        self.inputs = {}


def starts(height, size, overlap):
    if height <= size:
        return [0]
    return sorted(set(list(range(0, height-size+1, size-overlap)) + [height-size]))


def ios(a, b):
    alo, ahi, blo, bhi = a.min(axis=0), a.max(axis=0), b.min(axis=0), b.max(axis=0)
    intersection = ref.np.maximum(0, ref.np.minimum(ahi,bhi)-ref.np.maximum(alo,blo)).prod()
    area = min((ahi-alo).prod(), (bhi-blo).prod())
    return float(intersection/max(1.,area))


def boxes_for(pipeline, image, mode):
    base = pipeline.detect(image, mode['max_side'])
    if len(base)>PROTOCOL['max_lines']:
        raise ValueError('bounded line count exceeded')
    if not mode['sliced']:
        return base
    height = image.shape[0]
    candidates = [(1, 0., box) for box in base]
    for y in starts(height, PROTOCOL['slice_height'], PROTOCOL['slice_overlap']):
        end = min(y+PROTOCOL['slice_height'],height)
        for box in pipeline.detect(image[y:end], mode['max_side']):
            margin = min(float(box[:,1].min()), end-y-float(box[:,1].max()))
            shifted = box.copy(); shifted[:,1] += y
            candidates.append((0, margin, shifted))
    accepted = []
    for _, _, box in sorted(candidates, key=lambda row:(-row[0],-row[1])):
        if not any(ios(box, other) >= PROTOCOL['suppression_intersection_over_smaller'] for other in accepted):
            accepted.append(box)
    accepted.sort(key=lambda b:(float(b[0,1]),float(b[0,0])))
    if len(accepted)>PROTOCOL['max_lines']:
        raise ValueError('bounded line count exceeded')
    return accepted


def artifact_state(paths):
    # Detector/recognizer releases both use inference.onnx and inference.yml.
    # Preserve full paths so one role cannot overwrite another in a guard.
    return {str(path.resolve()): score.model_state([path])[path.name] for path in paths}


def run(mode, target):
    if target.exists():
        raise ValueError('Refusing to overwrite an experiment')
    samples, frozen = score.materialize()
    if frozen != json.loads((score.HERE/'ocr-dev-v1.json').read_text()):
        raise ValueError('Frozen DEV inputs changed')
    provenance = json.loads((MODELS/'provenance.json').read_text())
    model_paths=[]
    for task,tier in [('det',mode['detector']),('rec',mode['recognizer'])]:
        for name,entry in provenance[f'{tier}_{task}']['files'].items():
            path=MODELS/f'{tier}_{task}'/name
            if score.digest(path)!=entry['sha256']:
                raise ValueError('Model acquisition hash mismatch')
            model_paths.append(path)
    model_state=artifact_state(model_paths)
    pipeline=MixedPipeline(mode['detector'],mode['recognizer'])
    groups=defaultdict(list); rows=[]
    raw=DATA/mode['id']; raw.mkdir(exist_ok=True)
    started=time.monotonic()
    for sample in samples:
        image=ref.cv2.imread(sample['path'])
        start=time.monotonic()
        try:
            lines=[]
            for box in boxes_for(pipeline,image,mode):
                text=pipeline.recognize(ref.crop(image,box))
                x,y=box.min(axis=0).tolist(); right,bottom=box.max(axis=0).tolist()
                lines.append({'text':text,'x':x,'y':y,'w':right-x,'h':bottom-y})
            output={'text':'\n'.join(l['text'] for l in lines),'lines':lines}
        except Exception as error:
            output={'text':'','lines':[],'error':type(error).__name__}
        (raw/(sample['id']+'.json')).write_text(json.dumps(output,ensure_ascii=False)+'\n')
        scores=[]
        if sample['source']=='bankstatemently':
            scores.append({'label':'full_page',**score.token_score(sample['text'],output['text'])})
        else:
            for field in sample['fields']:
                scores.append({'label':field['label'],**score.token_score(field['text'],score.region_text(output['lines'],field['bbox']))})
        for item in scores:
            groups[sample['source']].append(item)
            groups[sample['source']+'.'+item['label']].append(item)
        rows.append({'id':sample['id'],'source':sample['source'],'failed':'error' in output,'scores':scores})
        print(mode['id'],sample['id'],round(time.monotonic()-start,2),flush=True)
    if artifact_state(model_paths)!=model_state:
        raise ValueError('Models changed during run')
    result={'mode':mode,'summary':{k:score.summary(v) for k,v in sorted(groups.items())},'rows':rows,
            'failed_pages':sum(r['failed'] for r in rows),'wall_seconds_descriptive':time.monotonic()-started,
            'provenance':{'protocol':PROTOCOL,'protocol_sha256':score.digest(HERE/'protocol.json'),
                          'runner_sha256':score.digest(__file__),'reference_sha256':score.digest(ref.__file__),
                          'scorer_sha256':score.digest(score.__file__),'dataset_sha256':score.digest(score.HERE/'ocr-dev-v1.json'),
                          'model_files':{str(p.relative_to(MODELS)):score.digest(p) for p in model_paths},
                          'runtime':{'onnxruntime':ref.ort.__version__,'opencv':ref.cv2.__version__,'numpy':ref.np.__version__}},
            'limits':'DEV only; Python/native reference pipeline, not shipped Rust/browser. No complete-page hallucination score for partial invoice annotations; no speedup or SOTA claim.'}
    target.write_text(json.dumps(result,indent=2)+'\n')
    print(mode['id'],{k:v for k,v in result['summary'].items() if '.' not in k},flush=True)


def main():
    os.umask(0o077); DATA.mkdir(exist_ok=True,mode=0o700)
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode');a=p.parse_args()
    output=HERE/'results';output.mkdir(exist_ok=True)
    modes=PROTOCOL['modes']
    if a.mode:
        mode=next(m for m in modes if m['id']==a.mode)
        run(mode,output/(a.mode+'.json'))
    else:
        for mode in modes:
            target=output/(mode['id']+'.json')
            if target.exists():raise ValueError('Refusing to overwrite an experiment; version it deliberately')
            try:
                subprocess.run([sys.executable,__file__,'--mode',mode['id']],check=True,timeout=PROTOCOL['timeouts_seconds_per_mode'])
            except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as error:
                target.write_text(json.dumps({'mode':mode,'run_failed':type(error).__name__,'pages':60,'failed_pages':60})+'\n')

if __name__=='__main__':main()
