# Face models: what ships, what was only benchmarked, and their licences

This may become a commercial product (a South African retailer), so every
model below is listed with three separate licences: its code, its weights,
and its training data where that is known. **A permissive licence on code or
weights does not make the training data's terms go away**, and most face
recognition weights are trained on scraped celebrity datasets whose terms are
non-commercial.

## Shipped in the demo (`models/face/`, served from `demo/public/models/face/`)

| Role | Model | File | Size | Code | Weights | Training data |
|---|---|---|---|---|---|---|
| Face detection | MediaPipe BlazeFace short-range (128 × 128) | `face_detector.onnx` | 0.4 MB | Apache-2.0 | **Apache-2.0** ([model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20(Short%20Range).pdf)) | Google's own, not published |
| 478 landmarks (irises included) | MediaPipe Face Mesh V2 (the Face Landmarker's landmark model, 256 × 256) | `face_landmarks_detector.onnx` | 4.9 MB | Apache-2.0 | **Apache-2.0** ([model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf)) | Google's own; z from synthetic data |
| Passive anti-spoofing | Minivision MiniFASNetV2 (2.7 × crop) + MiniFASNetV1SE (4.0 × crop), 80 × 80, exported as one graph | `minifasnet.onnx` | 3.5 MB | Apache-2.0 ([repo](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing)) | **Apache-2.0** (in the same repository, `resources/anti_spoof_models`) | Minivision's own, not published |
| Face templates | OpenCV Zoo SFace (MobileFaceNet-style, 128-d), Dropout removed, weights stored as int8 here (float32 arithmetic) | `sface_int8.onnx` | 9.9 MB (38.7 MB fp32) | Apache-2.0 | **Apache-2.0** ([LICENSE](https://github.com/opencv/opencv_zoo/blob/main/models/face_recognition_sface/LICENSE)) | **Not documented** for the shipped weights. The SFace paper (arXiv 2205.12010) trains on CASIA-WebFace, VGGFace2 and MS1MV2, all research-only. Commercial users have asked OpenCV which data trained the release ([opencv_zoo#313](https://github.com/opencv/opencv_zoo/issues/313), no maintainer answer as of 2026-10-20). |

Also used, not a model: MediaPipe's canonical face mesh (468 vertices, 898
triangles, UVs; `mediapipe/modules/face_geometry/data/canonical_face_model.obj`,
Apache-2.0), embedded as `docscan/src/face/canonical.rs` by
`face/tools/gen_canonical.py`, for head pose and for the synthetic test heads.

`face/tools/convert_models.sh` rebuilds every shipped file from the upstream
release: `tf2onnx` for the two MediaPipe `.tflite` files (float16 weights,
converted to float32 ONNX; every op is one rten runs), `export_minifasnet.py`
for the MiniFASNet pair, `quantise.py` for SFace (Dropout nodes removed: rten
runs Dropout only with its `random` feature; then each Conv/Gemm weight stored
as int8 with a per-output-channel scale and a `DequantizeLinear` in the graph,
so the download is a quarter and the arithmetic stays float32: cosine 0.9993+
to the float32 model, LFW unchanged). onnxruntime's `quantize_dynamic`
(`ConvInteger`/`MatMulInteger`) was tried first: rten 0.26 runs it, but its
outputs diverge from onnxruntime's on these networks (LFW 65% for SFace, 50%
for MobileFaceNet), so integer kernels are not used.

### Is the shipped recogniser commercially safe?

**Not provably.** SFace's weights carry Apache-2.0, which on its face permits
commercial use, but OpenCV does not say what it was trained on, and every
public dataset SFace's own paper uses is research-only. It is the best
*available* option with a permissive weights licence, which is why the demo
uses it, but a lawyer should treat its provenance as an open question. No
face-recognition weights were found whose code, weights **and** training data
are all cleared for commercial use (see `face/RESEARCH.md`). The path to a
clean model:

1. **Buy a licence**: InsightFace sells commercial licences for its packs
   (buffalo_s's MobileFaceNet `w600k_mbf` is the best compact model measured
   here); or a vendor SDK.
2. **Train our own** on data we have rights to. The architectures are free
   (MobileFaceNet in InsightFace's MIT code; EdgeFace's code is BSD-3-Clause).
   The data is the problem: DigiFace-1M (Microsoft, synthetic) is under
   R-UDA, whose §2.1 forbids using "the Data or any Results in any commercial
   offering" and whose §5.5 counts trained models as Results, so it is **not**
   a commercial route. Options: a consented, licensed collection of our own
   (POPIA s.26/27 consent for biometric data), a purchased dataset with a
   commercial training licence, or synthetic identities from a generator
   whose own training data is clean (none was found that is).
3. Whatever the model, calibrate its threshold on our own population and
   check error rates per demographic group: quantisation and training-data
   imbalance both hurt some groups more than others (arXiv 2308.11840).

## Benchmarked, not shipped

Fetched locally into `/tmp/face-models/` for evaluation only; never
committed and never served by the demo.

| Model | Size (ONNX) | Code | Weights | Training data | Why not shipped |
|---|---|---|---|---|---|
| InsightFace `w600k_mbf` (MobileFaceNet, buffalo_s) | 13.6 MB fp32, 3.5 MB int8 weights | MIT | **non-commercial research only** (commercial licence sold) | WebFace600K (from WebFace260M: research-only, signed agreement) | weights licence |
| InsightFace `w600k_r50` (IResNet-50, buffalo_l) | 174 MB | MIT | **non-commercial research only** | WebFace600K | weights licence; size |
| EdgeFace-XS (γ = 0.6) and -S (γ = 0.5) (Idiap, arXiv 2307.01838) | 7.3 MB / 14.8 MB (ONNX from yakhyo/edgeface-onnx) | BSD-3-Clause | **CC BY-NC-SA 4.0** | WebFace260M subsets | weights licence |
| FaceNet InceptionResnetV1 (facenet-pytorch, VGGFace2 weights) | 94 MB | MIT | no separate licence (ported from D. Sandberg's MIT facenet) | VGGFace2 (originally CC BY-SA 4.0, since withdrawn by its authors; scraped images) | accuracy (below SFace) and size; provenance unclear |
| SCRFD-500M (buffalo_s detector), 2d106det, 1k3d68 | 2.5 MB / 5 MB / 144 MB | MIT | **non-commercial research only** | WIDER FACE and others | weights licence (not needed: BlazeFace is used) |
| YuNet (OpenCV Zoo) | 0.2 MB | MIT | MIT | WIDER FACE (research dataset) | not needed; runs on rten if wanted |

The `face/eval/recognition.py` table names map to these: `w600k_mbf`,
`w600k_r50`, `edgeface_xs`, `edgeface_s`, `sface`, `facenet`, and the `_int8`
variants quantised by `face/tools/quantise.py`.
