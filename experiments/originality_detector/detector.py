"""Independent CPU research detector. Positive copy evidence or unknown, never original.

Features consume RGB uint8 and an optional four-corner document polygon in pixel
coordinates. JSON linear models are exportable; their scores are NOT probabilities.
No pretrained code or weights. See README and the model's scope before use.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import cv2
import numpy as np

cv2.setNumThreads(1)
VERSION = 'optics-features-v1'
METRICS = ('luma_std', 'chroma_std', 'luma_grad', 'chroma_grad',
           'luma_hp1', 'chroma_hp1', 'luma_hp3', 'chroma_hp3',
           'chroma_spectral_peak', 'luma_spectral_peak', 'saturation', 'dark')
FEATURES = [f'{region}_{metric}' for region in ('frame', 'document', 'outside') for metric in METRICS]
FEATURES += ['outside_document_chroma_hp_ratio', 'outside_document_peak_min', 'inside_outside_spectrum_cosine']
FEATURES += ['native_document_'+metric for metric in METRICS]


def _spectrum(a):
    a = cv2.resize(a, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float64)
    a = (a-a.mean()) * np.outer(np.hanning(64), np.hanning(64))
    power = abs(np.fft.fftshift(np.fft.fft2(a)))**2
    power[28:37, 28:37] = 0
    flat = power.ravel()
    return flat / max(float(flat.sum()), 1e-12)


def _stats(rgb, mask):
    # Mask must be sampled on a full bounding rectangle for FFT: zeroing would
    # manufacture edge spectra. Spatial statistics use only selected pixels.
    g = rgb.mean(axis=2)
    chroma = rgb[:, :, 0] - rgb[:, :, 1]
    use = mask > 0
    if use.sum() < 64:
        raise ValueError('insufficient region')
    values = [g[use].std(), chroma[use].std()]
    for a in (g, chroma):
        dx = cv2.Sobel(a, cv2.CV_32F, 1, 0, ksize=3)/8
        dy = cv2.Sobel(a, cv2.CV_32F, 0, 1, ksize=3)/8
        values.append(np.sqrt(dx*dx+dy*dy)[use].mean())
    for sigma in (1., 3.):
        for a in (g, chroma):
            high = a - cv2.GaussianBlur(a, (0, 0), sigma)
            values.append(np.sqrt(np.mean(high[use]**2)))
    # Largest all-inside rectangular tile, searched over fixed 8x8 grid.
    patches = []
    for y in range(8):
        for x in range(8):
            ys = slice(y*rgb.shape[0]//8, (y+1)*rgb.shape[0]//8)
            xs = slice(x*rgb.shape[1]//8, (x+1)*rgb.shape[1]//8)
            if use[ys, xs].all():
                patches.append((ys, xs))
    specs, lspecs = [], []
    for ys, xs in patches:
        specs.append(_spectrum(chroma[ys, xs]))
        lspecs.append(_spectrum(g[ys, xs]))
    # No tile is an explicit zero/absence, not fabricated spectral evidence.
    spec = np.mean(specs, axis=0) if specs else np.zeros(4096)
    lspec = np.mean(lspecs, axis=0) if lspecs else np.zeros(4096)
    values += [np.sort(spec)[-16:].sum(), np.sort(lspec)[-16:].sum(),
               (rgb.max(axis=2)[use] > .98).mean(), (g[use] < .06).mean()]
    return np.array(values), spec


def extract(rgb, quad=None):
    if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('expected opaque RGB uint8')
    h, w = rgb.shape[:2]
    if min(h, w) < 96 or max(h, w) > 16384 or h*w > 32_000_000:
        raise ValueError('unsupported dimensions')
    small = cv2.resize(rgb, (192, 128), interpolation=cv2.INTER_AREA).astype(np.float32)/255
    full = np.ones((128, 192), np.uint8)
    if quad is None:
        # Global models do not require a document mask. Context features are
        # unavailable and never selected by those models.
        doc = full
        inside, si = _stats(small, full)
        outside, so = inside.copy(), si.copy()
    else:
        q = np.asarray(quad, dtype=np.float64)
        if q.shape != (4, 2) or not np.isfinite(q).all() or (q < 0).any() or (q >= [w, h]).any():
            raise ValueError('invalid document quad')
        q = np.round(q * [192/w, 128/h]).astype(np.int32)
        if not cv2.isContourConvex(q):
            raise ValueError('nonconvex document quad')
        doc = np.zeros_like(full)
        cv2.fillConvexPoly(doc, q, 1)
        if not .15 <= doc.mean() <= .90:
            raise ValueError('document context unavailable')
        # Ignore the edge itself; the signal must exist on both sides.
        inside, si = _stats(small, cv2.erode(doc, np.ones((5, 5), np.uint8)))
        outside, so = _stats(small, 1-cv2.dilate(doc, np.ones((5, 5), np.uint8)))
    frame, _ = _stats(small, full)
    ratio = outside[5]/max(inside[5], 1e-4)
    cosine = float(si @ so)/max(float(np.linalg.norm(si)*np.linalg.norm(so)), 1e-12)
    native = frame
    if quad is not None:
        # Native-resolution patches preserve camera/screen frequency artifacts.
        # Axis-aligned, entirely inside the polygon; never rectify/resample them.
        native_patches = []
        centre = np.asarray(quad).mean(axis=0)
        for point in [centre]+[(centre+np.asarray(corner))/2 for corner in quad]:
            side = min(192, int(min(h, w)*.20))
            if side < 32:
                continue
            x0, y0 = np.round(point-side/2).astype(int)
            corners = [(x0, y0), (x0+side, y0), (x0+side, y0+side), (x0, y0+side)]
            contour = np.asarray(quad, dtype=np.float32)
            if all(cv2.pointPolygonTest(contour, (float(x), float(y)), False)>=0 for x,y in corners):
                patch = rgb[y0:y0+side, x0:x0+side].astype(np.float32)/255
                values, _ = _stats(patch, np.ones(patch.shape[:2], np.uint8))
                native_patches.append(values)
        if not native_patches:
            raise ValueError('no native document patch')
        native = np.median(native_patches, axis=0)
    return np.r_[frame, inside, outside, ratio, min(inside[8], outside[8]), cosine, native].astype(np.float64)


def extract_patch(rgb, centre):
    """Native 224-square at the supplied document centre; no geometric warp.

    Real study centres are author annotations. For live use the caller must
    supply a separately validated localizer, which this experiment lacks.
    """
    c = np.asarray(centre, dtype=np.float64)
    if c.shape != (2,) or not np.isfinite(c).all():
        raise ValueError('invalid patch centre')
    x, y = np.round(c).astype(int)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('expected opaque RGB uint8')
    if x-112 < 0 or y-112 < 0 or x+112 > rgb.shape[1] or y+112 > rgb.shape[0]:
        raise ValueError('native patch outside image')
    patch = rgb[y-112:y+112, x-112:x+112]
    values = extract(patch)
    native, _ = _stats(patch.astype(np.float32)/255, np.ones((224,224), np.uint8))
    values[39:] = native
    return values


def assess_patch(model, rgb, centre, *, allow_experimental=False):
    try:
        if model.get('input_protocol') != 'author_center_224':
            raise ValueError('model is not a native-centre-patch model')
        return decide(model, score(model, extract_patch(rgb, centre)), allow_experimental=allow_experimental)
    except (ValueError, KeyError, TypeError, IndexError, cv2.error) as exc:
        return {'status':'unknown', 'is_copy':None, 'confidence':None,
                'reason':'invalid_or_unsupported_input', 'detail':str(exc)}


def indices(candidate):
    if candidate == 'chroma_frequency':
        return [1, 3, 5, 7, 8]
    if candidate == 'texture_color':
        return list(range(12))
    if candidate == 'boundary_context':
        return list(range(39))
    if candidate == 'native_patch_texture':
        return list(range(39, len(FEATURES)))
    raise ValueError('unknown candidate')


def score(model, features):
    if model['feature_version'] != VERSION or model['feature_names'] != FEATURES:
        raise ValueError('feature schema mismatch')
    ids = model['indices']
    z = (features[ids] - np.asarray(model['mean']))/np.asarray(model['scale'])
    scores = z @ np.asarray(model['weights']).T + np.asarray(model['bias'])
    if not np.isfinite(scores).all():
        raise ValueError('nonfinite model score')
    return scores


def decide(model, scores, *, allow_experimental=False):
    result = {'status': 'unknown', 'is_copy': None, 'confidence': None,
              'scope': model['scope'], 'reason': 'below_copy_evidence_threshold',
              'scores': dict(zip(('screen', 'print'), map(float, scores)))}
    if model.get('deployment_validated') is not True and not allow_experimental:
        result['reason'] = 'research_model_not_validated_for_deployment'
        return result
    passing = [i for i in range(2) if float(scores[i]) > model['thresholds'][i]]
    if passing:
        result.update(status='copy_indicated', is_copy=True, reason='experimental_copy_evidence',
                      copy_kind='screen_or_print' if len(passing) == 2 else ('screen', 'print')[passing[0]])
    return result


def assess(model, rgb, quad=None, *, allow_experimental=False):
    try:
        if model.get('input_protocol') == 'author_center_224':
            raise ValueError('use assess_patch with document centre')
        if model['candidate'] in ('boundary_context', 'native_patch_texture') and quad is None:
            raise ValueError('document quad required')
        features = extract(rgb, quad if model['candidate'] in ('boundary_context', 'native_patch_texture') else None)
        return decide(model, score(model, features), allow_experimental=allow_experimental)
    except (ValueError, KeyError, TypeError, IndexError, cv2.error) as exc:
        return {'status': 'unknown', 'is_copy': None, 'confidence': None,
                'reason': 'invalid_or_unsupported_input', 'detail': str(exc)}


if __name__ == '__main__':
    from PIL import Image
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', type=Path)
    parser.add_argument('image', type=Path)
    parser.add_argument('--centre', help='JSON [x,y] for a native-centre-patch model')
    parser.add_argument('--quad', help='JSON four-corner pixel coordinates in boundary order')
    parser.add_argument('--allow-experimental', action='store_true')
    args = parser.parse_args()
    model = json.loads(args.model.read_text())
    try:
        with Image.open(args.image) as image:
            if 'A' in image.getbands() and np.any(np.asarray(image.getchannel('A')) != 255):
                raise ValueError('nonopaque input')
            if 'transparency' in image.info:
                raise ValueError('transparency unsupported')
            if image.width*image.height > 32_000_000:
                raise ValueError('image too large')
            pixels = np.asarray(image.convert('RGB'))
        result = (assess_patch(model, pixels, json.loads(args.centre), allow_experimental=args.allow_experimental)
                  if args.centre else assess(model, pixels, json.loads(args.quad) if args.quad else None,
                                            allow_experimental=args.allow_experimental))
    except (OSError, ValueError) as exc:
        result = {'status': 'unknown', 'is_copy': None, 'confidence': None, 'reason': str(exc)}
    print(json.dumps(result, allow_nan=False))
