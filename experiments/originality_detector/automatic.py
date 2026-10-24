"""Full-image, annotation-free 3x3 native-patch screen recapture experiment."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
from detector import extract_patch, score, decide

GRID = dict(version='native-grid-v1', rows=3, columns=3, patch_side=224,
            centres='linspace(112, dimension-112, 3)', aggregate='featurewise_quantile',
            quantile=.75, interpolation='linear', minimum_dimension=224)


def features(rgb):
    if not isinstance(rgb,np.ndarray) or rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3:
        raise ValueError('expected opaque RGB uint8')
    h,w=rgb.shape[:2]
    if min(h,w)<224 or h*w>32_000_000:
        raise ValueError('unsupported dimensions')
    # No label, identity, annotation, text recognition or human-selected ROI.
    xs=np.linspace(112,w-112,3);ys=np.linspace(112,h-112,3)
    patches=[extract_patch(rgb,[x,y]) for y in ys for x in xs]
    return np.quantile(np.array(patches),.75,axis=0,method='linear')


def assess(model,rgb,*,allow_experimental=False):
    try:
        if model.get('input_protocol')!='rgb_grid_3x3_native224_q75' or model.get('grid')!=GRID:
            raise ValueError('automatic-grid model schema mismatch')
        result=decide(model,score(model,features(rgb)),allow_experimental=allow_experimental)
        result['method']='automatic_native_grid'
        return result
    except (ValueError,KeyError,TypeError,IndexError) as exc:
        return dict(status='unknown',is_copy=None,confidence=None,reason='invalid_or_unsupported_input',detail=str(exc))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',type=Path);p.add_argument('image',type=Path)
    p.add_argument('--allow-experimental',action='store_true');a=p.parse_args()
    model=json.loads(a.model.read_text())
    try:
        with Image.open(a.image) as im:
            if im.width*im.height>32_000_000 or 'transparency' in im.info:
                raise ValueError('unsupported image')
            if 'A' in im.getbands() and np.any(np.asarray(im.getchannel('A'))!=255):
                raise ValueError('nonopaque input')
            rgb=np.asarray(im.convert('RGB'))
        result=assess(model,rgb,allow_experimental=a.allow_experimental)
    except (OSError,ValueError) as exc:result=dict(status='unknown',is_copy=None,confidence=None,reason=str(exc))
    print(json.dumps(result,allow_nan=False))
