//! The trained field tagger: a small transformer encoder over a page's OCR
//! words (`train/train_tagger.py`) that tags each word with a BIO label.
//! It runs on rten, the runtime ocrs already brings, so it ships inside the
//! same wasm.

use anyhow::Context;
use rten::Model;
use rten_tensor::prelude::*;
use rten_tensor::{NdTensor, NdTensorView};
use serde::Serialize;

use super::features::{self, MAX_IDS, NUM_FEATURES, Word};

/// The entities, in the order of the model's classes (`B-x` is `1 + 2i`,
/// `I-x` is `2 + 2i`, and class 0 is `O`).
pub const ENTITIES: [&str; 11] = [
    "HOLDER_NAME",
    "STREET",
    "SUBURB",
    "CITY",
    "PROVINCE",
    "POSTAL_CODE",
    "DOC_DATE",
    "PERIOD_FROM",
    "PERIOD_TO",
    "ISSUER",
    "ACCOUNT_NO",
];
pub const CLASSES: usize = 1 + 2 * ENTITIES.len();

pub struct Tagger {
    model: Model,
}

/// A run of words tagged as one entity.
#[derive(Debug, Clone, Serialize)]
pub struct Span {
    pub entity: &'static str,
    /// Word indices, in reading order.
    pub words: Vec<usize>,
    pub text: String,
    /// The mean probability of the entity (B or I) over the span's words.
    pub score: f32,
}

impl Tagger {
    pub fn load(bytes: Vec<u8>) -> anyhow::Result<Tagger> {
        Ok(Tagger { model: Model::load(bytes).context("loading the tagger model")? })
    }

    /// Per-word class probabilities, `[words][CLASSES]`.
    pub fn probabilities(&self, words: &[Word], width: f32, height: f32) -> anyhow::Result<Vec<[f32; CLASSES]>> {
        if words.is_empty() {
            return Ok(Vec::new());
        }
        let (ids, num) = features::features(words, width, height);
        let n = words.len();
        let ids: Vec<i32> = ids.iter().flatten().copied().collect();
        let num: Vec<f32> = num.iter().flatten().copied().collect();
        let ids = NdTensor::from_data([1, n, MAX_IDS], ids);
        let num = NdTensor::from_data([1, n, NUM_FEATURES], num);
        let ids_node = self.model.node_id("ids")?;
        let feats_node = self.model.node_id("feats")?;
        let out_node = self.model.node_id("logits")?;
        let [logits] = self.model.run_n(vec![(ids_node, ids.into()), (feats_node, num.into())], [out_node], None)?;
        let logits: NdTensor<f32, 3> = logits.try_into()?;
        let logits: NdTensorView<f32, 3> = logits.view();
        let mut out = Vec::with_capacity(n);
        for i in 0..n {
            let row: Vec<f32> = (0..CLASSES).map(|c| logits[[0, i, c]]).collect();
            let max = row.iter().copied().fold(f32::MIN, f32::max);
            let exp: Vec<f32> = row.iter().map(|v| (v - max).exp()).collect();
            let sum: f32 = exp.iter().sum();
            let mut p = [0f32; CLASSES];
            for c in 0..CLASSES {
                p[c] = exp[c] / sum;
            }
            out.push(p);
        }
        Ok(out)
    }
}

/// Whether word `b` continues a span ending at word `a`: next on the same
/// line, or the start of the line just below, overlapping it.
fn follows(words: &[Word], a: usize, b: usize) -> bool {
    let (wa, wb) = (&words[a], &words[b]);
    let h = wa.h.max(wb.h).max(1.0);
    if wb.line == wa.line {
        return wb.x >= wa.x && wb.x - (wa.x + wa.w) < 2.5 * h;
    }
    let below = wb.y > wa.y + 0.4 * h && wb.y - (wa.y + wa.h) < 1.6 * h;
    // The line below, under the span's end or (text wrapped in a sentence)
    // starting the next line.
    let first_in_line = b == 0 || words[b - 1].line != wb.line;
    below && wb.x < wa.x + wa.w + h && (wb.x + wb.w > wa.x - 12.0 * h || first_in_line)
}

/// Decodes per-word probabilities into spans: each word takes its most
/// likely entity, and joins the open span of that entity it follows on the
/// page (the next word on its line, or the line below), or starts one.
/// Columns interleave in reading order, so a span's words need not be
/// adjacent in it. B and I are not trusted to split spans: a word the model
/// wrongly calls `B-` would otherwise cut a name in two.
pub fn spans(words: &[Word], probs: &[[f32; CLASSES]]) -> Vec<Span> {
    let mut open: Vec<(usize, Vec<usize>)> = Vec::new();
    for (i, p) in probs.iter().enumerate() {
        let c = (0..CLASSES).max_by(|&a, &b| p[a].total_cmp(&p[b])).unwrap_or(0);
        if c == 0 {
            continue;
        }
        let e = (c - 1) / 2;
        let joins = open.iter_mut().rev().find(|(oe, ix)| *oe == e && follows(words, *ix.last().unwrap(), i));
        match joins {
            Some((_, ix)) => ix.push(i),
            None => open.push((e, vec![i])),
        }
    }
    open.into_iter()
        .map(|(e, ix)| {
            let score = ix.iter().map(|&i| probs[i][1 + 2 * e] + probs[i][2 + 2 * e]).sum::<f32>() / ix.len() as f32;
            let text = ix.iter().map(|&i| words[i].text.as_str()).collect::<Vec<_>>().join(" ");
            Span { entity: ENTITIES[e], words: ix, text, score }
        })
        .collect()
}
