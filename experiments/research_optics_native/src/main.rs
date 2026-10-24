//! Runs `docscan/src/exposure.rs` (included by path, unchanged) on raw RGB
//! frames, for parity and timing against the frozen Python arm.
//!
//! `exposure apply IN OUT`: IN is `u32le width, u32le height, RGB bytes`;
//! OUT gets the same format only when the gate opens. Prints one JSON line
//! of diagnostics, plus `analyse_ns` / `apply_ns` for that one call.
//!
//! `exposure table GAIN...`: the gain table for each gain, one JSON list a line.
//!
//! `exposure time IN REPEATS`: times analyse+apply REPEATS times in process
//! (after one warm-up) and prints the per-call nanoseconds, so process
//! start-up and file I/O are not in the measurement.

#[allow(dead_code)]
#[path = "../../../docscan/src/exposure.rs"]
mod exposure;

use std::time::Instant;

fn read(path: &str) -> (Vec<u8>, usize, usize) {
    let data = std::fs::read(path).expect("read input");
    let w = u32::from_le_bytes(data[0..4].try_into().unwrap()) as usize;
    let h = u32::from_le_bytes(data[4..8].try_into().unwrap()) as usize;
    (data[8..].to_vec(), w, h)
}

fn json(d: &exposure::ExposureDiagnostics, changed: bool) -> String {
    format!(
        "\"version\":\"{}\",\"width\":{},\"height\":{},\"thumbnail_width\":{},\"thumbnail_height\":{},\"background_p90\":{:?},\"applied\":{},\"gain\":{:?},\"changed\":{}",
        exposure::VERSION, d.width, d.height, d.thumbnail_width, d.thumbnail_height,
        d.background_p90, d.applied, d.gain, changed
    )
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("apply") => {
            let (rgb, w, h) = read(&args[2]);
            let start = Instant::now();
            let d = exposure::analyse(&rgb, w, h, exposure::Layout::Rgb).expect("analyse");
            let analyse_ns = start.elapsed().as_nanos();
            let start = Instant::now();
            let out = d.applied.then(|| exposure::apply_gain(&rgb, exposure::Layout::Rgb, d.gain));
            let apply_ns = start.elapsed().as_nanos();
            let changed = out.as_ref().is_some_and(|o| *o != rgb);
            if let Some(out) = out {
                let mut bytes = Vec::with_capacity(out.len() + 8);
                bytes.extend_from_slice(&(w as u32).to_le_bytes());
                bytes.extend_from_slice(&(h as u32).to_le_bytes());
                bytes.extend_from_slice(&out);
                std::fs::write(&args[3], bytes).expect("write output");
            }
            println!("{{{},\"analyse_ns\":{analyse_ns},\"apply_ns\":{apply_ns}}}", json(&d, changed));
        }
        Some("time") => {
            let (rgb, w, h) = read(&args[2]);
            let repeats: usize = args[3].parse().unwrap();
            let run = || exposure::correct(&rgb, w, h, exposure::Layout::Rgb).expect("correct");
            let first = run();
            let mut ns = Vec::with_capacity(repeats);
            for _ in 0..repeats {
                let start = Instant::now();
                std::hint::black_box(run());
                ns.push(start.elapsed().as_nanos());
            }
            let list: Vec<String> = ns.iter().map(u128::to_string).collect();
            println!("{{{},\"ns\":[{}]}}", json(&first.diagnostics, first.changed), list.join(","));
        }
        Some("table") => {
            // The 256-entry output table for each gain given, for parity.
            for g in &args[2..] {
                let t = exposure::gain_table(g.parse().unwrap());
                let list: Vec<String> = t.iter().map(u8::to_string).collect();
                println!("[{}]", list.join(","));
            }
        }
        _ => {
            eprintln!("usage: exposure apply IN OUT | exposure time IN REPEATS");
            std::process::exit(2);
        }
    }
}
