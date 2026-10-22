"""Builds models/text-detection-page.onnx: ocrs's text detection model with its
input size freed, so proof-of-address pages can be detected in strips the
width of the page instead of nine overlapping 600 x 800 tiles
(docscan/src/lib.rs, Scanner::detect_page).

The model is ocrs-models' `text-detection.onnx` (Robert Knight, CC BY-SA 4.0,
https://github.com/robertknight/ocrs-models), the same network and weights as
the `text-detection.rten` the rest of the scanner uses. Only the graph is
edited:
- the input and output height and width become symbolic (`h`, `w`);
- each skip connection's `Slice` (which crops the upsampled features to the
  size they had for an 800 x 600 input) takes its ends from the shape of the
  tensor it is concatenated with, instead of constants.
On an 800 x 600 input the edited model's output equals the original's exactly
(checked below with onnxruntime when it is installed). The result is a modified
version of a CC BY-SA 4.0 model and is licensed CC BY-SA 4.0 (NOTICE).

  uv run --with onnx --with onnxruntime --with numpy scripts/make-page-detector.py
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

import numpy as np
import onnx
from onnx import helper, numpy_helper

URL = "https://ocrs-models.s3-accelerate.amazonaws.com/text-detection.onnx"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "models" / "text-detection-page.onnx"


def main() -> None:
    src = Path("/tmp/text-detection.onnx")
    if not src.exists():
        urllib.request.urlretrieve(URL, src)
    print("source sha256", hashlib.sha256(src.read_bytes()).hexdigest())
    m = onnx.load(str(src))
    g = m.graph
    for v in (g.input[0], g.output[0]):
        dims = v.type.tensor_type.shape.dim
        dims[2].dim_param, dims[3].dim_param = "h", "w"
    consumers: dict[str, list] = {}
    for n in g.node:
        for i in n.input:
            consumers.setdefault(i, []).append(n)
    producer = {o: n for n in g.node for o in n.output}
    inits = {i.name: i for i in g.initializer}

    def const(name: str) -> int:
        if name in inits:
            return int(numpy_helper.to_array(inits[name]).reshape(-1)[0])
        return int(numpy_helper.to_array(producer[name].attribute[0].t).reshape(-1)[0])

    added = []
    for k, n in enumerate([n for n in g.node if n.op_type == "Slice"]):
        out, cur = n.output[0], n
        while consumers[out][0].op_type == "Slice":
            cur = consumers[out][0]
            out = cur.output[0]
        cat = consumers[out][0]
        assert cat.op_type == "Concat", cat.op_type
        skip = next(i for i in cat.input if i != out)
        axis = const(n.input[3])
        shape, ax, end = f"page_shape_{k}", f"page_axis_{k}", f"page_end_{k}"
        added += [helper.make_node("Shape", [skip], [shape]),
                  helper.make_node("Constant", [], [ax], value=numpy_helper.from_array(np.array([axis], dtype=np.int64))),
                  helper.make_node("Gather", [shape, ax], [end], axis=0)]
        n.input[2] = end
    nodes = added + list(g.node)
    # Topological order (the new nodes read tensors produced further down).
    avail = {i.name for i in g.input} | set(inits)
    order, pending = [], nodes
    while pending:
        rest = []
        for n in pending:
            if all(not i or i in avail for i in n.input):
                order.append(n)
                avail.update(n.output)
            else:
                rest.append(n)
        assert len(rest) < len(pending)
        pending = rest
    del g.node[:]
    g.node.extend(order)
    used = {i for n in g.node for i in n.input}
    keep = [i for i in g.initializer if i.name in used]
    del g.initializer[:]
    g.initializer.extend(keep)
    del g.value_info[:]
    m.doc_string = ("ocrs text detection (Robert Knight, CC BY-SA 4.0, github.com/robertknight/ocrs-models) with its input size "
                    "freed by docscan's scripts/make-page-detector.py; weights unchanged. Licensed CC BY-SA 4.0.")
    onnx.checker.check_model(m)
    onnx.save(m, str(OUT))
    print("wrote", OUT, OUT.stat().st_size, "bytes, sha256", hashlib.sha256(OUT.read_bytes()).hexdigest())
    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime not installed: equality not checked", file=sys.stderr)
        return
    a, b = ort.InferenceSession(str(src)), ort.InferenceSession(str(OUT))
    x = np.random.default_rng(0).random((1, 1, 800, 600), dtype=np.float32) - 0.5
    d = np.abs(a.run(None, {"input.1": x})[0] - b.run(None, {"input.1": x})[0]).max()
    print("max difference from the original at 800 x 600:", d)
    assert d < 1e-5
    print("runs at 384 x 1248:", b.run(None, {"input.1": np.zeros((1, 1, 384, 1248), np.float32)})[0].shape)


if __name__ == "__main__":
    main()
