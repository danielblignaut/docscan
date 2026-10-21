//! The face pipeline natively, for evaluation (`face/eval/*.py` drive it).
//!
//! ```text
//! face --models DIR photo IMAGE...                 # the PhotoFace JSON per image
//! face --models DIR embed LIST OUT.f32 [--aligned] [--flip] [--shard I/N]
//!     # one template per image path in LIST (one per line) into OUT.f32 (row-major,
//!     # zeros when no face is found) and OUT.f32.json (found flags, quality);
//!     # --aligned: the images are already 112 x 112 ArcFace-aligned crops
//! face --models DIR liveness CLIP.y4m [CONFIG_JSON] [--every N] [--fps F]
//!     # an active liveness session over the clip's frames; prints the result JSON
//! face --models DIR antispoof LIST OUT.json [--shard I/N]
//!     # the MiniFASNet live probability of the most prominent face in each image
//! ```
//!
//! `--models DIR` holds `face_detector.onnx`, `face_landmarks_detector.onnx`,
//! `minifasnet.onnx` and the recogniser named by `--recogniser FILE:NAME:KIND`
//! (default `w600k_mbf.onnx:w600k_mbf:arcface`).

use std::io::{BufRead, Read, Write};

use docscan::face::image::Frame;
use docscan::face::{FaceEngine, antispoof::AntiSpoof, detect::Detector, liveness, mesh::Mesh, recognise};

fn load_rgba(path: &str) -> anyhow::Result<(Vec<u8>, usize, usize)> {
    let img = image::open(path)?.to_rgba8();
    let (w, h) = img.dimensions();
    Ok((img.into_raw(), w as usize, h as usize))
}

struct Args {
    models: String,
    recogniser: String,
    rest: Vec<String>,
    flags: std::collections::HashMap<String, String>,
}

fn args() -> Args {
    let mut models = "../models/face".to_string();
    let mut recogniser = "w600k_mbf.onnx:w600k_mbf:arcface".to_string();
    let mut rest = Vec::new();
    let mut flags = std::collections::HashMap::new();
    let mut it = std::env::args().skip(1).peekable();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--models" => models = it.next().unwrap(),
            "--recogniser" => recogniser = it.next().unwrap(),
            "--aligned" | "--flip" | "--no-antispoof" | "--largest" => {
                flags.insert(a.clone(), "1".into());
            }
            "--shard" | "--every" | "--fps" | "--box-scale" | "--start" | "--align" => {
                flags.insert(a.clone(), it.next().unwrap());
            }
            _ => rest.push(a),
        }
    }
    Args { models, recogniser, rest, flags }
}

fn engine(a: &Args, need_rec: bool) -> anyhow::Result<FaceEngine> {
    let read = |f: &str| std::fs::read(format!("{}/{f}", a.models));
    let mut e = FaceEngine::default();
    e.detector = Some(Detector::load(read("face_detector.onnx")?)?);
    e.mesh = Some(Mesh::load(read("face_landmarks_detector.onnx")?)?);
    if !a.flags.contains_key("--no-antispoof") {
        if let Ok(b) = read("minifasnet.onnx") {
            let mut s = AntiSpoof::load(b)?;
            if let Some(k) = a.flags.get("--box-scale") {
                s.box_scale = k.parse()?;
            }
            e.antispoof = Some(s);
        }
    }
    if need_rec {
        let parts: Vec<&str> = a.recogniser.split(':').collect();
        let path = if parts[0].starts_with('/') { parts[0].to_string() } else { format!("{}/{}", a.models, parts[0]) };
        let kind = recognise::InputKind::parse(parts.get(2).copied().unwrap_or("arcface"))?;
        e.recogniser = Some(recognise::Recogniser::load(std::fs::read(&path)?, kind)?);
        e.recogniser_name = parts.get(1).copied().unwrap_or("model").to_string();
    }
    Ok(e)
}

fn shard(a: &Args, n: usize) -> (usize, usize) {
    match a.flags.get("--shard") {
        Some(s) => {
            let (i, k) = s.split_once('/').unwrap();
            let (i, k): (usize, usize) = (i.parse().unwrap(), k.parse().unwrap());
            (n * i / k, n * (i + 1) / k)
        }
        None => (0, n),
    }
}

fn read_list(path: &str) -> anyhow::Result<Vec<String>> {
    Ok(std::fs::read_to_string(path)?.lines().map(str::trim).filter(|l| !l.is_empty()).map(String::from).collect())
}

/// Reads a YUV4MPEG2 (4:2:0) clip as RGBA frames, and its frame rate.
fn read_y4m(path: &str) -> anyhow::Result<(Vec<Vec<u8>>, usize, usize, f64)> {
    let mut f = std::io::BufReader::new(std::fs::File::open(path)?);
    let mut header = String::new();
    f.read_line(&mut header)?;
    let (mut w, mut h, mut fps) = (0usize, 0usize, 30.0f64);
    for tok in header.split_whitespace() {
        match tok.as_bytes()[0] {
            b'W' => w = tok[1..].parse()?,
            b'H' => h = tok[1..].parse()?,
            b'F' => {
                let (n, d) = tok[1..].split_once(':').unwrap();
                fps = n.parse::<f64>()? / d.parse::<f64>()?;
            }
            _ => {}
        }
    }
    let (cw, ch) = (w.div_ceil(2), h.div_ceil(2));
    let mut frames = Vec::new();
    loop {
        let mut line = String::new();
        if f.read_line(&mut line)? == 0 {
            break;
        }
        let mut buf = vec![0u8; w * h + 2 * cw * ch];
        f.read_exact(&mut buf)?;
        let (y, uv) = buf.split_at(w * h);
        let (u, v) = uv.split_at(cw * ch);
        let mut rgba = vec![255u8; w * h * 4];
        for r in 0..h {
            for c in 0..w {
                let yy = y[r * w + c] as f32 - 16.0;
                let uu = u[(r / 2) * cw + c / 2] as f32 - 128.0;
                let vv = v[(r / 2) * cw + c / 2] as f32 - 128.0;
                let i = (r * w + c) * 4;
                rgba[i] = (1.164 * yy + 1.596 * vv).clamp(0.0, 255.0) as u8;
                rgba[i + 1] = (1.164 * yy - 0.392 * uu - 0.813 * vv).clamp(0.0, 255.0) as u8;
                rgba[i + 2] = (1.164 * yy + 2.017 * uu).clamp(0.0, 255.0) as u8;
            }
        }
        frames.push(rgba);
    }
    Ok((frames, w, h, fps))
}

fn main() -> anyhow::Result<()> {
    let a = args();
    let cmd = a.rest.first().cloned().unwrap_or_default();
    match cmd.as_str() {
        "photo" => {
            let e = engine(&a, true)?;
            for p in &a.rest[1..] {
                let (rgba, w, h) = load_rgba(p)?;
                let mut r = e.photo(&Frame::new(&rgba, w, h)?)?;
                r.aligned.clear();
                let mut v = serde_json::to_value(&r)?;
                v["template"] = serde_json::json!(r.template.len());
                println!("{}", serde_json::json!({"image": p, "face": v}));
            }
        }
        "embed" => {
            let e = engine(&a, true)?;
            let list = read_list(&a.rest[1])?;
            let out = &a.rest[2];
            let (s0, s1) = shard(&a, list.len());
            let aligned = a.flags.contains_key("--aligned");
            let flip = a.flags.contains_key("--flip");
            let rec = e.recogniser.as_ref().unwrap();
            let mut bin = std::io::BufWriter::new(std::fs::File::create(out)?);
            let mut meta = Vec::new();
            let mut dim = 0;
            for p in &list[s0..s1] {
                let (rgba, w, h) = load_rgba(p)?;
                let frame = Frame::new(&rgba, w, h)?;
                let (v, info) = if aligned {
                    let hwc: Vec<f32> = rgba.chunks_exact(4).flat_map(|px| [px[0] as f32, px[1] as f32, px[2] as f32]).collect();
                    anyhow::ensure!(w == 112 && h == 112, "{p} is not 112 x 112");
                    let mut v = rec.embed_aligned(&hwc)?;
                    if flip {
                        let f = recognise::flip_hwc(&hwc, 112, 112);
                        let u = rec.embed_aligned(&f)?;
                        for (x, y) in v.iter_mut().zip(u) {
                            *x += y;
                        }
                        let n = v.iter().map(|x| x * x).sum::<f32>().sqrt();
                        v.iter_mut().for_each(|x| *x /= n);
                    }
                    (v, serde_json::json!({"found": true}))
                } else {
                    let dets = e.detect_all(&frame, true)?;
                    // LFW's subject is the face at the centre of the image; a
                    // document's (--largest) is its largest face.
                    let (cx, cy) = (w as f32 / 2.0, h as f32 / 2.0);
                    let pick = if a.flags.contains_key("--largest") {
                        dets.iter().max_by(|x, y| (x.bbox[2] * x.bbox[3]).total_cmp(&(y.bbox[2] * y.bbox[3])))
                    } else {
                        dets.iter().min_by(|x, y| {
                            let d = |d: &docscan::face::detect::Detection| (d.bbox[0] + d.bbox[2] / 2.0 - cx).powi(2) + (d.bbox[1] + d.bbox[3] / 2.0 - cy).powi(2);
                            d(x).total_cmp(&d(y))
                        })
                    };
                    match pick {
                        Some(d) => {
                            let r = e.landmarks(&frame, d)?;
                            let pose = docscan::face::pose::estimate(&r.points);
                            let align = a.flags.get("--align").and_then(|s| recognise::Alignment::parse(s)).unwrap_or(recognise::Alignment::Iris);
                            let five = recognise::five_points_with(&r.points, align);
                            let v = rec.embed(&frame, &five, flip)?;
                            let al = docscan::face::image::warp_hwc(&frame, &recognise::alignment(&five), 112, 112, 1.0, 0.0);
                            let q = docscan::face::quality::assess(&frame, &r.points, &pose, Some(&al));
                            (v, serde_json::json!({"found": true, "faces": dets.len(), "presence": r.presence, "quality": q.score, "iod": q.interocular_px, "sharpness": q.sharpness, "yaw": pose.yaw, "pitch": pose.pitch}))
                        }
                        None => (Vec::new(), serde_json::json!({"found": false})),
                    }
                };
                if !v.is_empty() {
                    dim = v.len();
                }
                let v = if v.is_empty() { vec![0f32; dim.max(1)] } else { v };
                for x in &v {
                    bin.write_all(&x.to_le_bytes())?;
                }
                meta.push(info);
            }
            std::fs::write(format!("{out}.json"), serde_json::to_string(&serde_json::json!({"dim": dim, "items": meta}))?)?;
        }
        "antispoof" => {
            let e = engine(&a, false)?;
            let list = read_list(&a.rest[1])?;
            let (s0, s1) = shard(&a, list.len());
            let fas = e.antispoof.as_ref().unwrap();
            let mut out = Vec::new();
            for p in &list[s0..s1] {
                let (rgba, w, h) = load_rgba(p)?;
                let frame = Frame::new(&rgba, w, h)?;
                let dets = e.detect_all(&frame, true)?;
                let best = dets.iter().max_by(|x, y| (x.bbox[2] * x.bbox[3]).total_cmp(&(y.bbox[2] * y.bbox[3])));
                let v = match best {
                    Some(d) => {
                        let r = e.landmarks(&frame, d)?;
                        let s = fas.score(&frame, docscan::face::mesh::bbox(&r.points))?;
                        serde_json::json!({"found": true, "real": s.real, "print": s.print, "replay": s.replay})
                    }
                    None => serde_json::json!({"found": false}),
                };
                out.push(v);
            }
            std::fs::write(&a.rest[2], serde_json::to_string(&out)?)?;
        }
        "liveness" => {
            let e = engine(&a, true)?;
            let (frames, w, h, fps) = read_y4m(&a.rest[1])?;
            let fps = a.flags.get("--fps").map(|f| f.parse().unwrap()).unwrap_or(fps);
            let every: usize = a.flags.get("--every").map(|f| f.parse().unwrap()).unwrap_or(1);
            let start: usize = a.flags.get("--start").map(|f| f.parse().unwrap()).unwrap_or(0);
            let config: liveness::Config = match a.rest.get(2) {
                Some(c) => serde_json::from_str(c)?,
                None => liveness::Config::default(),
            };
            let mut s = liveness::Session::new(config);
            e.reset_tracking();
            let mut trace = Vec::new();
            let mut ms = Vec::new();
            for (i, f) in frames.iter().enumerate().skip(start).step_by(every) {
                let ts = i as f64 * 1000.0 / fps;
                let t = docscan_now();
                let p = s.frame(&e, &Frame::new(f, w, h)?, ts)?;
                ms.push(docscan_now() - t);
                trace.push(serde_json::json!({"i": i, "phase": p.phase, "hint": p.hint, "found": p.found, "bbox": p.bbox, "dir": p.direction, "yaw": p.pose.yaw, "pitch": p.pose.pitch, "cov": p.coverage}));
                if matches!(s.phase(), liveness::Phase::Done | liveness::Phase::Failed) {
                    break;
                }
            }
            let mut r = serde_json::to_value(s.result(&e))?;
            r["best_frame"] = serde_json::json!(null);
            r["aligned"] = serde_json::json!(null);
            r["template"] = serde_json::json!(r["template"].as_array().map(|t| t.len()));
            ms.sort_by(f64::total_cmp);
            let res: Vec<_> = s.planarity_residuals().iter().map(|(r, m)| serde_json::json!([r, m])).collect();
            let par: Vec<_> = s.parallax_samples().iter().map(|(r, m)| serde_json::json!([r, m])).collect();
            println!(
                "{}",
                serde_json::json!({"clip": a.rest[1], "result": r, "residuals": res, "parallax": par, "outliers": s.outlier_samples(), "antispoof": s.antispoof_samples(), "ms_median": ms.get(ms.len() / 2), "trace": if std::env::var("TRACE").is_ok() { serde_json::json!(trace) } else { serde_json::json!(null) }})
            );
        }
        _ => anyhow::bail!("usage: see the header of examples/face.rs"),
    }
    Ok(())
}

fn docscan_now() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64() * 1000.0
}
