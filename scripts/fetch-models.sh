#!/usr/bin/env sh
# Downloads the ocrs text detection and recognition models (https://github.com/robertknight/ocrs-models)
# into models/ and copies them, with the proof-of-address tagger (models/poa-tagger.onnx, trained
# here on synthetic data only: see the README), to where the demo serves them from. The demo then
# fetches every model from its own origin and nothing else.
set -eu
cd "$(dirname "$0")/.."
mkdir -p models demo/public/models
for m in text-detection text-recognition; do
  [ -f "models/$m.rten" ] || curl -fL -o "models/$m.rten" "https://ocrs-models.s3-accelerate.amazonaws.com/$m.rten"
  cp "models/$m.rten" demo/public/models/
done
[ -f models/poa-tagger.onnx ] && cp models/poa-tagger.onnx demo/public/models/
ls -l models
