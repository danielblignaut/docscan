"""Exports Minivision's two released MiniFASNet anti-spoofing models as one ONNX.

Silent-Face-Anti-Spoofing (https://github.com/minivision-ai/Silent-Face-Anti-Spoofing,
Apache-2.0, weights in `resources/anti_spoof_models`) runs two models on two
crops of the face box: MiniFASNetV2 on a 2.7x crop and MiniFASNetV1SE on a 4.0x
crop, each 80 x 80 BGR with 0-255 values, and adds their softmaxes. The
exported graph takes both crops (`crop27`, `crop40`) and returns the mean of
the two softmaxes (`probs`: [spoof (print), real, spoof (replay)]).

Usage: python export_minifasnet.py /path/to/Silent-Face-Anti-Spoofing out.onnx
"""
import sys
from collections import OrderedDict

import torch

repo, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, repo)
from src.model_lib.MiniFASNet import MiniFASNetV1SE, MiniFASNetV2  # noqa: E402


def load(cls, path):
    m = cls(conv6_kernel=(5, 5))
    sd = torch.load(path, map_location="cpu")
    sd = OrderedDict((k[7:] if k.startswith("module.") else k, v) for k, v in sd.items())
    m.load_state_dict(sd)
    return m.eval()


class Both(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.v2 = load(MiniFASNetV2, f"{repo}/resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth")
        self.v1se = load(MiniFASNetV1SE, f"{repo}/resources/anti_spoof_models/4_0_0_80x80_MiniFASNetV1SE.pth")

    def forward(self, crop27, crop40):
        return (torch.softmax(self.v2(crop27), 1) + torch.softmax(self.v1se(crop40), 1)) / 2


m = Both().eval()
x = torch.rand(1, 3, 80, 80) * 255
torch.onnx.export(m, (x, x), out, input_names=["crop27", "crop40"], output_names=["probs"], opset_version=17, dynamo=False)
print(out, m(x, x))
