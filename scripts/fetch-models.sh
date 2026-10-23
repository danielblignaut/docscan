#!/usr/bin/env sh
# Downloads the ocrs text detection and recognition models (https://github.com/robertknight/ocrs-models)
# into models/ and copies them, with the proof-of-address tagger (models/poa-tagger.onnx, trained
# here on synthetic data only: see the README) and the face models in models/face/, to where
# the demo serves them from. The demo then
# fetches every model from its own origin and nothing else.
set -eu
cd "$(dirname "$0")/.."
mkdir -p models demo/public/models
for m in text-detection text-recognition; do
  [ -f "models/$m.rten" ] || curl -fL -o "models/$m.rten" "https://ocrs-models.s3-accelerate.amazonaws.com/$m.rten"
  cp "models/$m.rten" demo/public/models/
done
[ -f models/poa-tagger.onnx ] && cp models/poa-tagger.onnx demo/public/models/
# The page detector: ocrs's detection model with its input size freed (committed;
# CC BY-SA 4.0 like the model it is made from; scripts/make-page-detector.py).
[ -f models/text-detection-page.onnx ] && cp models/text-detection-page.onnx demo/public/models/
# The face models (models/face/: MediaPipe BlazeFace and Face Mesh V2, MiniFASNet,
# SFace int8; all Apache-2.0, converted by face/tools/convert_models.sh; see face/MODELS.md).
mkdir -p demo/public/models/face
cp models/face/*.onnx demo/public/models/face/
# Optional PP-OCRv6 tiny: staged at build time, fetched by the browser only on selection.
python3 scripts/fetch-ppocr-v6-models.py
ls -l models models/face
