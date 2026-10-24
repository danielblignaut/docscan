import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
// Regression from a publisher synthetic statement; no source media in git.
const root=new URL('../../', import.meta.url).pathname.replace(/\/$/, '');
const data=process.env.DOCSCAN_PUBLIC_DATA ?? '/tmp/docscan-public-data';
const folder=process.argv[2] ?? root+'/docscan/pkg';
const api=await import(pathToFileURL(folder+'/docscan.js'));
const instance=api.initSync({module:readFileSync(folder+'/docscan_bg.wasm')});
const scanner=new api.PaddleTextScanner();
scanner.load_detector(readFileSync(root+'/models/ppocr-v6-tiny-det.onnx'));
scanner.load_recognizer(readFileSync(root+'/models/ppocr-v6-tiny-rec.onnx'),readFileSync(root+'/docscan/src/text_v6_dictionary.json','utf8'));
const pixels=execFileSync(data+'/venv/bin/python',['-c','import sys; from PIL import Image; im=Image.open(sys.argv[1]).convert("RGBA"); sys.stdout.buffer.write(im.width.to_bytes(4,"little")+im.height.to_bytes(4,"little")+im.tobytes())',data+'/bankstatemently/rendered-dev-v1/bsb-001-p3.png'],{maxBuffer:32*1024*1024});
const w=pixels.readUInt32LE(0),h=pixels.readUInt32LE(4);
try {
 const result=scanner.read(new Uint8Array(pixels.buffer,pixels.byteOffset+8),w,h);
 if(!result.text.includes('execution and settlement')) throw Error('Long line not recovered');
 console.log(JSON.stringify({passed:true,lines:result.lines.length,memoryBytes:instance.memory.buffer.byteLength}));
} catch(e){console.error(String(e));process.exitCode=1;}
