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
# The face models (models/face/: MediaPipe BlazeFace and Face Mesh V2, MiniFASNet,
# SFace int8; all Apache-2.0, converted by face/tools/convert_models.sh; see face/MODELS.md).
mkdir -p demo/public/models/face
cp models/face/*.onnx demo/public/models/face/
ls -l models models/face
