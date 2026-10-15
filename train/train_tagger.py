"""Train the proof-of-address field tagger and export it to ONNX.

A small transformer encoder over a page's OCR words. Each word is the mean of
its hashed text-feature embeddings (docscan/src/poa/features.rs) concatenated
with its numeric layout features, projected to d_model; self-attention over
every word on the page then tags each word with a BIO class. No vocabulary,
no pretrained weights: ~1.4 M parameters, ~5.5 MB as float32.

  python train_tagger.py --data /tmp/docscan-poa/ds/train_*.jsonl --test-layouts a,b --out /tmp/docscan-poa/model

Writes poa-tagger.onnx (inputs `ids` int32 [1, N, 24] and `feats` float32
[1, N, 32]; output `logits` [1, N, 23]) and metrics.json. Deterministic for a
given --seed on one machine.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

BUCKETS = 16384
MAX_IDS = 24
NUM_FEATURES = 32
ENTITIES = ["HOLDER_NAME", "STREET", "SUBURB", "CITY", "PROVINCE", "POSTAL_CODE", "DOC_DATE", "PERIOD_FROM", "PERIOD_TO", "ISSUER", "ACCOUNT_NO"]
CLASSES = 1 + 2 * len(ENTITIES)


class Attention(nn.Module):
    def __init__(self, d: int, heads: int):
        super().__init__()
        self.h, self.dk = heads, d // heads
        self.qkv = nn.Linear(d, 3 * d)
        self.out = nn.Linear(d, d)

    def forward(self, x, bias=None):
        b, n, d = x.shape
        q, k, v = self.qkv(x).reshape(b, n, 3, self.h, self.dk).permute(2, 0, 3, 1, 4)
        att = (q @ k.transpose(-1, -2)) / math.sqrt(self.dk)
        if bias is not None:
            att = att + bias
        att = att.softmax(-1)
        return self.out((att @ v).transpose(1, 2).reshape(b, n, d))


class Block(nn.Module):
    def __init__(self, d: int, heads: int, ff: int, dropout: float):
        super().__init__()
        self.n1, self.n2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.att = Attention(d, heads)
        self.ff = nn.Sequential(nn.Linear(d, ff), nn.ReLU(), nn.Linear(ff, d))
        self.drop = nn.Dropout(dropout)

    def forward(self, x, bias=None):
        x = x + self.drop(self.att(self.n1(x), bias))
        return x + self.drop(self.ff(self.n2(x)))


class Tagger(nn.Module):
    def __init__(self, d: int = 128, emb: int = 64, layers: int = 3, heads: int = 4, ff: int = 256, dropout: float = 0.1):
        super().__init__()
        self.emb = nn.Embedding(BUCKETS, emb, padding_idx=0)
        self.inp = nn.Sequential(nn.Linear(emb + NUM_FEATURES, d), nn.ReLU(), nn.Linear(d, d))
        # Box geometry gets its own projection too: 2-D position, the layout signal.
        self.pos = nn.Sequential(nn.Linear(6, d), nn.ReLU(), nn.Linear(d, d))
        self.blocks = nn.ModuleList(Block(d, heads, ff, dropout) for _ in range(layers))
        self.norm = nn.LayerNorm(d)
        self.head = nn.Linear(d, CLASSES)

    def forward(self, ids, feats, key_mask=None):
        """ids [B, N, K] int, feats [B, N, F]; key_mask [B, N] true for real words."""
        e = self.emb(ids.long())  # [B, N, K, E]
        m = (ids > 0).to(e.dtype).unsqueeze(-1)
        e = (e * m).sum(2) / m.sum(2).clamp(min=1.0)
        x = self.inp(torch.cat([e, feats], -1)) + self.pos(feats[..., :6])
        bias = None
        if key_mask is not None:
            bias = torch.zeros(key_mask.shape, dtype=x.dtype).masked_fill(~key_mask, -1e9)[:, None, None, :]
        for blk in self.blocks:
            x = blk(x, bias)
        return self.head(self.norm(x))


def load(paths: list[str]) -> list[dict]:
    pages = []
    for p in paths:
        for line in open(p):
            r = json.loads(line)
            if not r.get("ok") or not r.get("words"):
                continue
            pages.append({
                "id": r["id"], "layout": r["layout"], "kind": r["kind"],
                "ids": np.array(r["ids"], np.int32), "num": np.array(r["num"], np.float32), "labels": np.array(r["labels"], np.int64),
            })
    return pages


def batches(pages, size, shuffle, rng):
    order = list(range(len(pages)))
    if shuffle:
        rng.shuffle(order)
    for i in range(0, len(order), size):
        chunk = [pages[j] for j in order[i : i + size]]
        n = max(len(p["labels"]) for p in chunk)
        ids = np.zeros((len(chunk), n, MAX_IDS), np.int32)
        num = np.zeros((len(chunk), n, NUM_FEATURES), np.float32)
        lab = np.full((len(chunk), n), -100, np.int64)
        mask = np.zeros((len(chunk), n), bool)
        for k, p in enumerate(chunk):
            m = len(p["labels"])
            ids[k, :m], num[k, :m], lab[k, :m], mask[k, :m] = p["ids"], p["num"], p["labels"], True
        yield torch.from_numpy(ids), torch.from_numpy(num), torch.from_numpy(lab), torch.from_numpy(mask)


def word_metrics(model, pages) -> dict:
    """Word-level micro precision/recall/F1 over the entity words, per entity."""
    model.eval()
    tp = np.zeros(len(ENTITIES)); fp = np.zeros(len(ENTITIES)); fn = np.zeros(len(ENTITIES))
    with torch.no_grad():
        for ids, num, lab, mask in batches(pages, 16, False, None):
            pred = model(ids, num, mask).argmax(-1)
            for p, t in zip(pred[mask].numpy(), lab[mask].numpy()):
                pe, te = (p - 1) // 2 if p else -1, (t - 1) // 2 if t else -1
                if pe == te and pe >= 0:
                    tp[pe] += 1
                else:
                    if pe >= 0:
                        fp[pe] += 1
                    if te >= 0:
                        fn[te] += 1
    out = {}
    for i, e in enumerate(ENTITIES):
        prec = tp[i] / max(1, tp[i] + fp[i]); rec = tp[i] / max(1, tp[i] + fn[i])
        out[e] = round(2 * prec * rec / max(1e-9, prec + rec), 4)
    t, p_, n_ = tp.sum(), fp.sum(), fn.sum()
    out["micro_f1"] = round(2 * t / max(1, 2 * t + p_ + n_), 4)
    return out


def layout_augment(num: torch.Tensor) -> torch.Tensor:
    """Moves and stretches each page's absolute box coordinates (features 0-5:
    x0, y0, x1, y1, cx, cy) at random, so the tagger cannot learn where on
    the page a layout puts the address and must read the words, their labels
    and their neighbours instead. Relative features are left alone."""
    num = num.clone()
    b = num.shape[0]
    for axis in (0, 1):
        scale = torch.empty(b, 1, 1).uniform_(0.6, 1.25)
        shift = torch.empty(b, 1, 1).uniform_(-0.35, 0.35)
        idx = [axis, axis + 2, axis + 4]
        num[:, :, idx] = num[:, :, idx] * scale + shift
    return num


class Export(nn.Module):
    """The tagger without the padding mask: one page at a time."""

    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, ids, feats):
        return self.m(ids, feats)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--test-layouts", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--d", type=int, default=128)
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--threads", type=int, default=12)
    ap.add_argument("--weights", help="per-file repeat counts, comma-separated, matching the expanded --data files in order (default 1)")
    ap.add_argument("--layout-aug", action=argparse.BooleanOptionalAction, default=True, help="randomise absolute positions in training")
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    rng = random.Random(args.seed)

    paths = [p for pat in args.data for p in sorted(glob.glob(pat))]
    weights = [int(w) for w in args.weights.split(",")] if args.weights else [1] * len(paths)
    assert len(weights) == len(paths), "one --weights entry per data file"
    pages = [p for path, w in zip(paths, weights) for p in load([path]) * w]
    held = set(filter(None, args.test_layouts.split(",")))
    train = [p for p in pages if p["layout"] not in held]
    # A validation slice of the training layouts (whole documents: both renders of a doc stay together).
    ids = sorted({p["id"] for p in train})
    rng.shuffle(ids)
    val_ids = set(ids[: max(1, len(ids) // 12)])
    val = [p for p in train if p["id"] in val_ids]
    train = [p for p in train if p["id"] not in val_ids]
    test = [p for p in pages if p["layout"] in held]
    print(f"train {len(train)} pages, val {len(val)}, held-out layouts {sorted(held)}: {len(test)}")

    model = Tagger(d=args.d, layers=args.layers)
    params = sum(p.numel() for p in model.parameters())
    print(f"{params:,} parameters")
    # O dominates the words; weigh it down so entities are not ignored.
    weight = torch.ones(CLASSES)
    weight[0] = 0.3
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    steps = args.epochs * math.ceil(len(train) / args.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=steps, pct_start=0.1)
    t0 = time.time()
    best, best_state, history = -1.0, None, []
    for epoch in range(args.epochs):
        model.train()
        total = 0.0
        for ids_t, num_t, lab_t, mask_t in batches(train, args.batch, True, rng):
            # Word dropout on the text features: OCR misreads words.
            drop = torch.rand(ids_t.shape[:2]) < 0.05
            ids_t = ids_t.masked_fill(drop.unsqueeze(-1), 0)
            if args.layout_aug:
                num_t = layout_augment(num_t)
            logits = model(ids_t, num_t, mask_t)
            loss = F.cross_entropy(logits.reshape(-1, CLASSES), lab_t.reshape(-1), weight=weight, ignore_index=-100, label_smoothing=0.05)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            total += loss.item()
        vm = word_metrics(model, val)
        history.append({"epoch": epoch + 1, "loss": round(total, 3), "val_micro_f1": vm["micro_f1"], "s": round(time.time() - t0)})
        print(json.dumps(history[-1]), flush=True)
        if vm["micro_f1"] > best:
            best, best_state = vm["micro_f1"], {k: v.clone() for k, v in model.state_dict().items()}
    train_s = time.time() - t0
    model.load_state_dict(best_state)
    model.eval()
    metrics = {"params": params, "train_seconds": round(train_s), "train_pages": len(train), "val": word_metrics(model, val),
               "test_held_out_layouts": word_metrics(model, test) if test else None, "history": history, "args": vars(args)}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "poa-tagger.pt")
    ex = Export(model).eval()
    n = 50
    torch.onnx.export(
        ex, (torch.ones(1, n, MAX_IDS, dtype=torch.int32), torch.zeros(1, n, NUM_FEATURES)), str(out / "poa-tagger.onnx"),
        input_names=["ids", "feats"], output_names=["logits"], dynamic_axes={"ids": {1: "n"}, "feats": {1: "n"}, "logits": {1: "n"}},
        opset_version=17, dynamo=False,
    )
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps({k: metrics[k] for k in ("params", "train_seconds", "val", "test_held_out_layouts")}, indent=1))


if __name__ == "__main__":
    main()
