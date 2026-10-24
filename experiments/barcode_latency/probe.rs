//! Private latency probe (DEV only): `prepare.py` copies it into the snapshot
//! as `examples/latency_probe.rs`. Never committed into the crate.
//!
//! `latency_probe --models=DIR --mode=raw|full|roi [--margins=a,b,c,d,e]
//!  [--repeat=N] [--parity] <image>...` prints one JSON line per image and
//! iteration with stage timings, the OCR plan, and the labelled fields. The
//! fields hold values: the runner reads them in memory and writes aggregates.
#[path = "../src/label_regions.rs"]
mod label_regions;

use std::time::Instant;

use docscan::{Scanner, barcode, labels, quality};
use label_regions::Margins;

const TILE_W: usize = 600;
const TILE_H: usize = 800;

/// The tiles `Scanner::tiled` would run for a `w` × `h` crop (dense spacing).
fn tiles(w: usize, h: usize) -> usize {
    let n = |len: usize, tile: usize| if len <= tile { 1 } else { len.div_ceil(tile * 3 / 4) };
    n(w, TILE_W) * n(h, TILE_H)
}

fn ms(t: Instant) -> f64 {
    t.elapsed().as_secs_f64() * 1000.0
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let opt = |k: &str| args.iter().find_map(|a| a.strip_prefix(k)).map(str::to_owned);
    let mode = opt("--mode=").unwrap_or_else(|| "full".into());
    let repeat: usize = opt("--repeat=").and_then(|v| v.parse().ok()).unwrap_or(1);
    let parity = args.iter().any(|a| a == "--parity");
    // `direct`: a crop within one tile is read as it is (ocrs pads it),
    // not enlarged towards the tile size as `ocr_tiled` does.
    let direct = opt("--crop-ocr=").is_some_and(|v| v == "direct");
    let margins = match opt("--margins=") {
        Some(s) => {
            let v: Vec<f32> = s.split(',').map(|x| x.parse().expect("margin")).collect();
            Margins { vertical_across: v[0], vertical_along: v[1], horizontal_across: v[2], horizontal_along: v[3], min_px: v[4] }
        }
        None => label_regions::MARGINS,
    };
    let mut scanner = Scanner::new();
    let t_models = Instant::now();
    if mode != "raw" {
        let models = opt("--models=").expect("--models=DIR");
        scanner.load_ocr_models(std::fs::read(format!("{models}/text-detection.rten"))?, std::fs::read(format!("{models}/text-recognition.rten"))?)?;
    }
    let models_ms = ms(t_models);
    for path in args.iter().filter(|a| !a.starts_with("--")) {
        let t_load = Instant::now();
        let img = image::open(path)?;
        let rgba = img.to_rgba8();
        let (w, h) = rgba.dimensions();
        let rgba = rgba.into_raw();
        let load_ms = ms(t_load);
        for iteration in 0..repeat {
            let t0 = Instant::now();
            let luma = quality::rgba_to_luma(&rgba);
            let luma_ms = ms(t0);
            let t = Instant::now();
            let codes = barcode::read_all(&luma, w, h, None);
            let read_all_ms = ms(t);
            if mode == "raw" {
                println!(
                    "{}",
                    serde_json::json!({"path": path, "mode": mode, "iteration": iteration, "w": w, "h": h, "load_ms": load_ms,
                        "stages": {"luma": luma_ms, "read_all": read_all_ms}, "total_ms": ms(t0),
                        "barcodes": codes.iter().map(|b| serde_json::json!({"format": b.format, "text": b.text})).collect::<Vec<_>>()})
                );
                continue;
            }
            let t = Instant::now();
            let regions: Vec<[f32; 4]> = barcode::oriented_regions(&luma, w as usize, h as usize).iter().map(|r| r.bounds()).collect();
            let regions_ms = ms(t);
            // OCR at most 1280 wide, as labelled_native does.
            let t = Instant::now();
            let k = (Scanner::LABEL_OCR_WIDTH_PX as f32 / w as f32).min(1.0);
            let (small, sw, sh) = if k < 1.0 { quality::scale_rgba(&rgba, w as usize, h as usize, k) } else { (rgba.clone(), w as usize, h as usize) };
            let scale_ms = ms(t);
            let t = Instant::now();
            let plan = if mode == "roi" || mode == "mosaic" {
                let sr: Vec<[f32; 4]> = regions.iter().map(|r| r.map(|v| v * k)).collect();
                let sc: Vec<Vec<[f32; 2]>> = codes.iter().map(|b| b.points.iter().map(|p| [p[0] * k, p[1] * k]).collect()).collect();
                label_regions::plan(sw as u32, sh as u32, &sr, &sc, margins)
            } else {
                label_regions::Plan { rects: vec![[0, 0, sw as u32, sh as u32]], whole_frame: None }
            };
            let plan_ms = ms(t);
            let t = Instant::now();
            let mut lines = Vec::new();
            let mut rect_ms = Vec::new();
            let mut canvases = 0usize;
            let mut gutter_lines = 0usize;
            let tiled_rects: Vec<[u32; 4]> = if mode == "mosaic" && plan.whole_frame.is_none() {
                let (placed, apart) = label_regions::pack(&plan.rects);
                canvases = placed.iter().map(|p| p.canvas + 1).max().unwrap_or(0);
                for c in 0..canvases {
                    let tr = Instant::now();
                    let canvas = label_regions::compose(&small, sw as u32, &placed, c);
                    let [cw, ch] = label_regions::CANVAS;
                    let ocr = scanner.ocr_lines(&canvas, cw, ch)?;
                    let skew = ocr.skew;
                    for mut l in ocr.lines {
                        if skew.abs() >= 1.0 {
                            let q = [[l.x, l.y], [l.x + l.w, l.y], [l.x, l.y + l.h], [l.x + l.w, l.y + l.h]]
                                .map(|p| docscan::geometry::rotated_to_source(p, cw as usize, ch as usize, skew));
                            let (x0, x1) = q.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[0]), b.max(p[0])));
                            let (y0, y1) = q.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[1]), b.max(p[1])));
                            (l.x, l.y, l.w, l.h) = (x0, y0, x1 - x0, y1 - y0);
                        }
                        match label_regions::canvas_to_frame(&placed, c, [l.x, l.y, l.w, l.h]) {
                            Some([x, y, w, h]) => {
                                (l.x, l.y, l.w, l.h) = (x / k, y / k, w / k, h / k);
                                lines.push(l);
                            }
                            None => gutter_lines += 1,
                        }
                    }
                    rect_ms.push(ms(tr));
                }
                apart
            } else {
                plan.rects.clone()
            };
            for &rect in &tiled_rects {
                let tr = Instant::now();
                let [rx, ry, rw, rh] = rect;
                let crop = if rect == [0, 0, sw as u32, sh as u32] { small.clone() } else { label_regions::crop_rgba(&small, sw as u32, rect) };
                let read = if direct && rw as usize <= TILE_W && rh as usize <= TILE_H {
                    // As `Scanner::tiled` does: lines of a levelled crop back to its pixels.
                    let ocr = scanner.ocr_lines(&crop, rw, rh)?;
                    let skew = ocr.skew;
                    ocr.lines
                        .into_iter()
                        .map(|mut l| {
                            if skew.abs() >= 1.0 {
                                let c = [[l.x, l.y], [l.x + l.w, l.y], [l.x, l.y + l.h], [l.x + l.w, l.y + l.h]]
                                    .map(|p| docscan::geometry::rotated_to_source(p, rw as usize, rh as usize, skew));
                                let (x0, x1) = c.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[0]), b.max(p[0])));
                                let (y0, y1) = c.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p[1]), b.max(p[1])));
                                (l.x, l.y, l.w, l.h) = (x0, y0, x1 - x0, y1 - y0);
                            }
                            l
                        })
                        .collect()
                } else {
                    scanner.ocr_tiled(&crop, rw as usize, rh as usize)?
                };
                for mut l in read {
                    (l.x, l.y) = (l.x + rx as f32, l.y + ry as f32);
                    (l.x, l.y, l.w, l.h) = (l.x / k, l.y / k, l.w / k, l.h / k);
                    lines.push(l);
                }
                rect_ms.push(ms(tr));
            }
            let ocr_ms = ms(t);
            let t = Instant::now();
            let out = labels::associate(&codes, &regions, &lines);
            let associate_ms = ms(t);
            let total_ms = ms(t0);
            let same_as_library = if parity && iteration == 0 && mode == "full" {
                let lib = scanner.labelled_native(&rgba, w, h)?;
                Some(serde_json::to_string(&lib.fields)? == serde_json::to_string(&out.fields)?)
            } else {
                None
            };
            println!(
                "{}",
                serde_json::json!({
                    "path": path, "mode": mode, "iteration": iteration, "w": w, "h": h, "models_ms": models_ms, "load_ms": load_ms,
                    "stages": {"luma": luma_ms, "read_all": read_all_ms, "regions": regions_ms, "scale": scale_ms, "plan": plan_ms, "ocr": ocr_ms, "associate": associate_ms},
                    "total_ms": total_ms,
                    "plan": {"rects": plan.rects.len(), "whole_frame": plan.whole_frame.map(|w| format!("{w:?}")),
                             "ocr_px": plan.rects.iter().map(|r| r[2] as u64 * r[3] as u64).sum::<u64>(), "frame_px": (sw * sh) as u64,
                             "tiles": plan.rects.iter().map(|r| tiles(r[2] as usize, r[3] as usize)).sum::<usize>()},
                    "lines": lines.len(),
                    "rect_ms": rect_ms,
                    "canvases": canvases,
                    "detections": canvases + tiled_rects.iter().map(|r| tiles(r[2] as usize, r[3] as usize)).sum::<usize>(),
                    "gutter_lines": gutter_lines,
                    "geometry": {"regions": regions, "rects": plan.rects.iter().map(|r| r.map(|v| v as f32 / k)).collect::<Vec<_>>(),
                                 "line_boxes": lines.iter().map(|l| [l.x, l.y, l.w, l.h]).collect::<Vec<_>>(),
                                 "line_texts": lines.iter().map(|l| l.text.clone()).collect::<Vec<_>>()},
                    "same_as_library": same_as_library,
                    "barcodes": codes.iter().map(|b| serde_json::json!({"format": b.format, "text": b.text})).collect::<Vec<_>>(),
                    "fields": out.fields.iter().map(|f| serde_json::json!({"label": f.label, "value": f.value, "kind": f.kind, "source": f.source,
                        "check": f.check_digit_valid, "format": f.barcode_format, "unread": f.barcode_unread, "bbox": f.bbox})).collect::<Vec<_>>(),
                    "dropped": out.dropped.len(),
                })
            );
        }
    }
    Ok(())
}
