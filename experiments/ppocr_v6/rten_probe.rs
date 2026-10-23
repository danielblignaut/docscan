//! Execute an official ONNX graph on a saved real input using docscan's RTen.
//! Args: MODEL INPUT_F32 N,C,H,W OUTPUT_F32. Files contain little-endian f32.
use std::{error::Error, fs, io::Write, time::Instant};
use rten::{Model, ValueView};
use rten_tensor::prelude::*;

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 4 { return Err("expected MODEL INPUT_F32 N,C,H,W OUTPUT_F32".into()); }
    let shape: Vec<usize> = args[2].split(',').map(str::parse).collect::<Result<_, _>>()?;
    let bytes = fs::read(&args[1])?;
    if bytes.len() % 4 != 0 { return Err("input is not whole f32 values".into()); }
    let data: Vec<f32> = bytes.chunks_exact(4).map(|b| f32::from_le_bytes(b.try_into().unwrap())).collect();
    if data.len() != shape.iter().product::<usize>() { return Err("input shape and byte count disagree".into()); }
    let model = Model::load_file(&args[0])?;
    let input = ValueView::from_shape(shape.as_slice(), &data)?;
    let start = Instant::now();
    let mut outputs = model.run(vec![(model.input_ids()[0], input.into())], model.output_ids(), None)?;
    let elapsed = start.elapsed().as_secs_f64() * 1000.0;
    let tensor = outputs.remove(0).into_tensor::<f32>().ok_or("non-f32 output")?;
    let mut file = fs::File::create(&args[3])?;
    for value in tensor.iter() { file.write_all(&value.to_le_bytes())?; }
    println!("{{\"output_shape\":{:?},\"inference_ms\":{elapsed}}}", tensor.shape());
    Ok(())
}
