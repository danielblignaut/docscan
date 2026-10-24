#!/usr/bin/env python3
"""Reproducible invented bright/dark browser fixtures; Pillow + NumPy + OpenCV.

Run from the repository root with the research optics environment:
  /tmp/docscan-ppocr-v6/venv/bin/python demo/e2e/generate-exposure-fixtures.py
No native OCR or private document input is needed.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import hashlib
import numpy as np
from PIL import Image
ROOT = Path(__file__).resolve().parents[2]
def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path('/tmp/docscan-exposure-browser'))
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    corpus=load('exposure_text_fixture',ROOT/'eval/text_eval.py')
    optics=load('exposure_optics_fixture',ROOT/'experiments/research_optics/optics.py')
    source_dir=args.out/'source';corpus.generate(source_dir)
    pixels=np.asarray(Image.open(source_dir/'family0-size14-clean.png').convert('RGB'))
    Image.fromarray(pixels).save(args.out/'clean.png')
    Image.fromarray(optics.encode(optics.linear(pixels)*.18)).save(args.out/'dark.png')
    manifest={'source':'eval/text_eval.py:family0-size14-clean','linear_exposure':.18,
      'files':{name:hashlib.sha256((args.out/name).read_bytes()).hexdigest() for name in ['clean.png','dark.png']},
      'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.out/'fixtures.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Generated two fictional exposure fixtures at',args.out)
if __name__=='__main__':main()
