"""Exports facenet-pytorch's InceptionResnetV1 (VGGFace2 weights) to ONNX.

Code: https://github.com/timesler/facenet-pytorch (MIT). Weights: ported from
David Sandberg's facenet (MIT) trained on VGGFace2. Input 1x3xHxW RGB,
(x - 127.5) / 128; output a 512-d embedding (L2-normalised by the model).
Usage: python export_facenet.py out.onnx
"""
import sys

import torch
from facenet_pytorch import InceptionResnetV1

m = InceptionResnetV1(pretrained="vggface2").eval()
x = torch.zeros(1, 3, 112, 112)
torch.onnx.export(m, x, sys.argv[1], input_names=["input"], output_names=["embedding"], opset_version=17, dynamo=False,
                  dynamic_axes={"input": {2: "h", 3: "w"}})
print(sys.argv[1])
