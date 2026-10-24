#!/usr/bin/env python3
"""Build isolated native RTen probes from the unchanged shipped OCR source.

No repository source/model changes. The hybrid probe changes only the pinned
recognizer dictionary/class count and matching artifact bounds; geometry and
selection are unchanged. Not a browser integration.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import yaml

REPO=Path(__file__).resolve().parents[2]
OUT=Path('/tmp/docscan-research-ocr/native')
MODELS=Path('/tmp/docscan-ppocr-v6')
CRATES=('anyhow','rten','rten_imageproc','rten_tensor','serde','serde_json','serde_wasm_bindgen','wasm_bindgen','image')

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    deps=REPO/'docscan/target/release/deps'
    fingerprints=deps.parent/'.fingerprint'
    examples=list(fingerprints.glob('docscan-*/example-text_v6.json'))
    if len(examples)!=1:raise ValueError('Need one current native text_v6 Cargo fingerprint')
    expected={row[1]:row[3] for row in json.loads(examples[0].read_text())['deps']}
    libs={}
    for crate in CRATES:
        matches=[]
        for fingerprint in fingerprints.glob(f'*/lib-{crate}'):
            if int.from_bytes(bytes.fromhex(fingerprint.read_text()), 'little')==expected[crate]:
                path=deps/f'lib{crate}-{fingerprint.parent.name.rsplit("-",1)[1]}.rlib'
                if path.exists():matches.append(path)
        if len(matches)!=1:raise ValueError(f'No unique Cargo-matched {crate} rlib')
        libs[crate]=matches[0]
    source=(REPO/'docscan/src/text_v6.rs').read_text()
    model_manifest=json.loads((MODELS/'provenance.json').read_text())
    for kind in ['tiny_det','tiny_rec','small_rec']:
        for name,record in model_manifest[kind]['files'].items():
            if sha(MODELS/kind/name)!=record['sha256']:raise ValueError('Pinned model changed')
    for tier in ['tiny','small']:
        folder=OUT/tier;folder.mkdir(parents=True,exist_ok=True)
        if (folder/'reader').exists():
            old=json.loads((folder/'build.json').read_text())
            if old['binary_sha256']!=sha(folder/'reader') or old['source_sha256']!=sha(REPO/'docscan/src/text_v6.rs'):
                raise ValueError('Existing immutable probe differs; version a new build directory')
            print(tier,'existing probe verified; preserved',flush=True)
            continue
        config=yaml.safe_load((MODELS/f'{tier}_rec/inference.yml').read_text())
        chars=['']+config['PostProcess']['character_dict']+[' ']
        expected=6906 if tier=='tiny' else 18710
        assert len(chars)==expected
        (folder/'text_v6_dictionary.json').write_text(json.dumps(chars,ensure_ascii=False))
        text=source
        if tier=='small':
            changes={'const CLASSES: usize = 6906;':'const CLASSES: usize = 18710;',
                     'json.len() <= 128 * 1024':'json.len() <= 256 * 1024',
                     'bytes.len() <= 16 * 1024 * 1024':'bytes.len() <= 32 * 1024 * 1024',
                     'engine: "ppocr_v6_tiny",':'engine: "experimental_tiny_detector_small_recognizer",'}
            for old,new in changes.items():
                if old not in text:raise ValueError('Source seam changed')
                text=text.replace(old,new)
        (folder/'text_v6.rs').write_text(text)
        main='''mod text_v6;
fn now() -> f64 { std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs_f64()*1000.0 }
fn to_js<T: serde::Serialize>(v: &T) -> Result<wasm_bindgen::JsValue,wasm_bindgen::JsError> {
    v.serialize(&serde_wasm_bindgen::Serializer::json_compatible()).map_err(|e| wasm_bindgen::JsError::new(&e.to_string()))
}
fn main()->anyhow::Result<()> {
    let args:Vec<String>=std::env::args().skip(1).collect();
    let mut reader=text_v6::PaddleTextScanner::new();
    reader.load_detector_native(std::fs::read(args[0].clone())?)?;
    reader.load_recognizer_native(std::fs::read(args[1].clone())?,text_v6::DICTIONARY_JSON)?;
    let image=image::open(&args[2])?.to_rgba8();
    let result=if args.get(3).is_some_and(|a|a=="detail") {
        reader.read_detailed_native(image.as_raw(),image.width() as usize,image.height() as usize)
    } else { reader.read_native(image.as_raw(),image.width() as usize,image.height() as usize) };
    match result { Ok(v)=>println!("{}",serde_json::to_string(&v)?),Err(e)=>println!("{}",serde_json::json!({"error":e.to_string()})) }
    Ok(())
}
'''
        (folder/'main.rs').write_text(main)
        command=[str(Path.home()/'.cargo/bin/rustc'),'--edition','2024','-O',str(folder/'main.rs'),'-L',f'dependency={deps}','-o',str(folder/'reader')]
        for crate,path in libs.items():command+=['--extern',f'{crate}={path}']
        subprocess.run(command,check=True,env={**os.environ, "CARGO_PKG_NAME":"docscan-research-probe", "CARGO_MANIFEST_DIR":str(folder), "CARGO_PKG_VERSION":"0.0.0", "CARGO_PKG_AUTHORS":"", "CARGO_PKG_DESCRIPTION":"isolated native OCR experiment"})
        provenance={'source_sha256':sha(REPO/'docscan/src/text_v6.rs'),'experimental_source_sha256':sha(folder/'text_v6.rs'),
                    'dictionary_sha256':sha(folder/'text_v6_dictionary.json'),'binary_sha256':sha(folder/'reader'),
                    'recognizer_tier':tier,'classes':expected,'dependencies':{k:sha(v) for k,v in libs.items()},
                    'model_hashes':{'detector':sha(MODELS/'tiny_det/inference.onnx'),'recognizer':sha(MODELS/f'{tier}_rec/inference.onnx')},
                    'limits':'Native feasibility, no model fitting, browser or shipped engine change'}
        (folder/'build.json').write_text(json.dumps(provenance,indent=2)+'\n')
        print(tier,provenance['binary_sha256'],flush=True)

if __name__=='__main__':main()
