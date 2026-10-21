#!/usr/bin/env sh
# Rebuilds models/face/ from the upstream releases (needs a Python with
# tensorflow-cpu, tf2onnx, torch, onnx and onnxruntime; see face/MODELS.md):
#   face_detector.onnx            MediaPipe BlazeFace short-range (Apache-2.0), tflite -> ONNX
#   face_landmarks_detector.onnx  MediaPipe Face Mesh V2 from the Face Landmarker bundle (Apache-2.0)
#   minifasnet.onnx               Minivision MiniFASNetV2 + V1SE (Apache-2.0), see export_minifasnet.py
#   sface_int8.onnx               OpenCV Zoo SFace (Apache-2.0), Dropout removed, dynamic int8
# Usage: PY=/path/to/python face/tools/convert_models.sh
set -eu
PY="${PY:-python3}"
cd "$(dirname "$0")/../.."
W="${TMPDIR:-/tmp}/docscan-face-convert"
mkdir -p "$W" models/face
curl -fsSL -o "$W/face_landmarker.task" https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task
(cd "$W" && unzip -o -q face_landmarker.task)
for m in face_detector face_landmarks_detector; do
  "$PY" -m tf2onnx.convert --tflite "$W/$m.tflite" --output "models/face/$m.onnx" --opset 17
done
[ -d "$W/silentface" ] || git clone -q --depth 1 https://github.com/minivision-ai/Silent-Face-Anti-Spoofing.git "$W/silentface"
"$PY" face/tools/export_minifasnet.py "$W/silentface" models/face/minifasnet.onnx
curl -fsSL -o "$W/sface.onnx" https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx
"$PY" face/tools/quantise.py "$W/sface.onnx" models/face/sface_int8.onnx
ls -l models/face
