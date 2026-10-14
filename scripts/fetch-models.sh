#!/usr/bin/env sh
# Downloads the ocrs text detection and recognition models (https://github.com/robertknight/ocrs-models)
# into models/ and copies them where the demo serves them from.
set -eu
cd "$(dirname "$0")/.."
mkdir -p models demo/public/models
for m in text-detection text-recognition; do
  [ -f "models/$m.rten" ] || curl -fL -o "models/$m.rten" "https://ocrs-models.s3-accelerate.amazonaws.com/$m.rten"
  cp "models/$m.rten" demo/public/models/
done
ls -l models
