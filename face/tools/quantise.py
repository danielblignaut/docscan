"""Prepares a recognition ONNX for rten: removes Dropout nodes (inference
no-ops that rten only runs with its `random` feature) and, unless --fp32,
stores the Conv/Gemm/MatMul weights as int8 with a per-output-channel scale,
dequantised in the graph (`DequantizeLinear` on the constant weight): the
download shrinks about 4x while the arithmetic stays float32.

Why weight-only: onnxruntime's `quantize_dynamic` output (DynamicQuantizeLinear
+ ConvInteger/MatMulInteger) runs on rten 0.26 but its results diverge from
onnxruntime's on these networks (cosine 0.09-0.97 to float32 with uint8
weights, 0.92-0.99 with int8 weights, against 0.99+ in onnxruntime; measured
in face/RESULTS.md), so the integer kernels are not used.

Usage: python quantise.py IN.onnx OUT.onnx [--fp32]
"""
import sys

import numpy as np
import onnx
from onnx import helper, numpy_helper

src, dst = sys.argv[1], sys.argv[2]
m = onnx.load(src)
g = m.graph
alias = {n.output[0]: n.input[0] for n in g.node if n.op_type == "Dropout"}
outputs = {o.name for o in g.output}
keep = []
for n in g.node:
    if n.op_type == "Dropout":
        continue
    for i, x in enumerate(n.input):
        while x in alias:
            x = alias[x]
        n.input[i] = x
    keep.append(n)
for out_name, src_name in alias.items():
    if out_name in outputs:
        for n in keep:
            for i, x in enumerate(n.output):
                if x == src_name:
                    n.output[i] = out_name
del g.node[:]
g.node.extend(keep)

if "--fp32" not in sys.argv:
    inits = {t.name: t for t in g.initializer}
    # Initialisers listed as graph inputs (old exporters) must stop being inputs.
    graph_inputs = {i.name for i in g.input}
    new_nodes = []
    for n in g.node:
        w_idx = 1 if n.op_type in ("Conv", "Gemm", "MatMul") else None
        if w_idx is not None and len(n.input) > w_idx and n.input[w_idx] in inits:
            name = n.input[w_idx]
            w = numpy_helper.to_array(inits[name]).astype(np.float32)
            if w.size >= 1024:
                # Per output channel: axis 0 for Conv weights [out, in, kh, kw]
                # and Gemm with transB; axis 1 for MatMul/Gemm [in, out].
                trans_b = any(a.name == "transB" and a.i == 1 for a in n.attribute)
                axis = 0 if n.op_type == "Conv" or (n.op_type == "Gemm" and trans_b) else 1
                red = tuple(i for i in range(w.ndim) if i != axis)
                scale = np.maximum(np.abs(w).max(axis=red), 1e-12) / 127.0
                shape = [1] * w.ndim
                shape[axis] = -1
                q = np.clip(np.round(w / scale.reshape(shape)), -127, 127).astype(np.int8)
                g.initializer.remove(inits[name])
                if name in graph_inputs:
                    for i in list(g.input):
                        if i.name == name:
                            g.input.remove(i)
                g.initializer.extend([
                    numpy_helper.from_array(q, name + "_q"),
                    numpy_helper.from_array(scale.astype(np.float32), name + "_scale"),
                    numpy_helper.from_array(np.zeros_like(scale, dtype=np.int8), name + "_zp"),
                ])
                new_nodes.append(helper.make_node("DequantizeLinear", [name + "_q", name + "_scale", name + "_zp"], [name], axis=axis, name=name + "_dq"))
        new_nodes.append(n)
    del g.node[:]
    g.node.extend(new_nodes)
    if m.opset_import[0].version < 13:
        m.opset_import[0].version = 13
onnx.checker.check_model(m)
onnx.save(m, dst)
print(dst)
