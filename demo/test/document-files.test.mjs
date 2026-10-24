import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { deflateSync } from "node:zlib";
// Production uses bundler-compatible .js specifiers. Node 24 strips TS directly for these tests.
registerHooks({ resolve(specifier, context, nextResolve) {
  if (specifier.startsWith("./") && specifier.endsWith(".js") && context.parentURL?.includes("/document-files/")) {
    const source = new URL(specifier.slice(0,-3)+".ts",context.parentURL);
    if (existsSync(source)) return nextResolve(source.href,context);
  }
  return nextResolve(specifier,context);
} });
const { inspectFile, inspectDocumentFile, openPdf } = await import("../src/document-files/index.ts");
const { parseImageMetadata } = await import("../src/document-files/image.ts");
const { limitsFor } = await import("../src/document-files/common.ts");

// Invented 2x2 RGB image, encoded locally with Pillow JPEG2000 (lossless).
const jpxFixture = "AAAADGpQICANCocKAAAAFGZ0eXBqcDIgAAAAAGpwMiAAAAAtanAyaAAAABZpaGRyAAAAAgAAAAIAAwcHAAAAAAAPY29scgEAAAAAABAAAAC5anAyY/9P/1EALwAAAAAAAgAAAAIAAAAAAAAAAAAAAAIAAAACAAAAAAAAAAAAAwcBAQcBAQcBAf9SAAwAAAABAAEEBAAB/1wAB0BASEhQ/2QAJQABQ3JlYXRlZCBieSBPcGVuSlBFRyB2ZXJzaW9uIDIuNS4z/5AACgAAAAAAPgAB/5PPtAQHz7QECM+0BAfPwAY+0Bj8AEAHCQDH2gMfaAx+ACAEBwfPwAZ+ADH4AIAHBAn/2Q==";
const stream = (data, dictionary = "") => `<< /Length ${Buffer.byteLength(data,"latin1")} ${dictionary} >>\nstream\n${data}\nendstream`;
function pdf({ pages = 1, signature = false, blankSignature = false, attachment = false, hugeMetadata = false, encrypted = false, js = false, formJs = false, text = "Invented bank statement 123.45", xmp = false, raster = false, jpx = null } = {}) {
  const objects = [];
  const add = value => { objects.push(value); return objects.length; };
  add(""); add("");
  const font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  const info = add(`<< /Producer (${hugeMetadata ? "Editor".repeat(5000) : "Synthetic Generator"}) /CreationDate (D:20261024120000Z) /ModDate (D:20261023120000Z) >>`);
  const kids = [];
  let field, attachmentId;
  if (signature || blankSignature) {
    let signed;
    if (signature) signed = add("<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached /ByteRange [0 1 4 1] /Contents <010203> /Name (Unverified Invented Signer) >>");
    field = add(`<< /Type /Annot /Subtype /Widget /FT /Sig /T (Signature1) /Rect [0 0 0 0] ${signed ? `/V ${signed} 0 R` : ""} >>`);
  }
  if (formJs) field = add('<< /Type /Annot /Subtype /Widget /FT /Tx /T (InventedField) /Rect [0 0 10 10] /AA << /K << /S /JavaScript /JS (globalThis.DOCUMENT_JS_EXECUTED = true) >> >> >>');
  if (attachment) {
    // Deliberately invalid compressed data: enumeration must not inflate or expose it.
    const payload = add(stream("this-is-not-a-zlib-stream", "/Type /EmbeddedFile /Filter /FlateDecode"));
    attachmentId = add(`<< /Type /Filespec /F (do-not-open.bin) /EF << /F ${payload} 0 R >> >>`);
  }
  const image = raster || jpx ? add(stream((jpx ? Buffer.from(jpx,"base64") : deflateSync(Buffer.from([255,0,0,0,128,0,0,0,255,0,0,0]))).toString("latin1"), `/Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /${jpx ? "JPXDecode" : "FlateDecode"}`)) : null;
  for (let i=0;i<pages;i++) {
    const content = add(stream(image ? "q 160 0 0 160 20 20 cm /Im1 Do Q" : `BT /F1 12 Tf 20 180 Td (${text}) Tj ET`));
    const annot = attachmentId ? add(`<< /Type /Annot /Subtype /FileAttachment /Rect [0 0 10 10] /FS ${attachmentId} 0 R >>`) : null;
    const annotations = [i === 0 ? field : null, annot].filter(Boolean);
    const page = add(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 ${font} 0 R >> ${image ? `/XObject << /Im1 ${image} 0 R >>` : ""} >> /Contents ${content} 0 R ${annotations.length ? `/Annots [${annotations.map(n=>`${n} 0 R`).join(" ")}]` : ""} >>`);
    kids.push(`${page} 0 R`);
  }
  const metadata = xmp ? add(stream('<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/"><xmp:CreatorTool>Synthetic XMP Tool</xmp:CreatorTool></rdf:Description></rdf:RDF></x:xmpmeta>', "/Type /Metadata /Subtype /XML")) : null;
  objects[0] = `<< /Type /Catalog /Pages 2 0 R ${field ? `/AcroForm << /SigFlags 3 /Fields [${field} 0 R] >>` : ""} ${attachmentId ? `/Names << /EmbeddedFiles << /Names [(attachment) ${attachmentId} 0 R] >> >>` : ""} ${js ? '/OpenAction << /S /JavaScript /JS (globalThis.DOCUMENT_JS_EXECUTED = true) >>' : ''} ${metadata ? `/Metadata ${metadata} 0 R` : ''} >>`;
  objects[1] = `<< /Type /Pages /Count ${pages} /Kids [${kids.join(" ")}] >>`;
  const encrypt = encrypted ? add("<< /Filter /Standard /V 1 /R 2 /Length 40 /O <0000000000000000000000000000000000000000000000000000000000000000> /U <0000000000000000000000000000000000000000000000000000000000000000> /P -4 >>") : null;
  let body = "%PDF-1.7\n";
  const offsets = [0];
  for (const [i, object] of objects.entries()) { offsets.push(Buffer.byteLength(body,"latin1")); body += `${i+1} 0 obj\n${object}\nendobj\n`; }
  const xref = Buffer.byteLength(body,"latin1");
  body += `xref\n0 ${offsets.length}\n0000000000 65535 f \n${offsets.slice(1).map(n=>`${String(n).padStart(10,"0")} 00000 n \n`).join("")}trailer\n<< /Size ${offsets.length} /Root 1 0 R /Info ${info} 0 R ${encrypt ? `/Encrypt ${encrypt} 0 R /ID [<0102030405060708> <0102030405060708>]` : ""} >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body,"latin1");
}
function exif() {
  // Synthetic TIFF IFD0: camera Make, software, and a GPS pointer (coordinates never exported).
  const make = Buffer.from("Invented Camera\0"), software = Buffer.from("Invented Editor\0");
  const start = 8+2+3*12+4;
  const gpsOffset = start+make.length+software.length;
  const data = Buffer.alloc(gpsOffset+2+12+4+24);
  data.write("II"); data.writeUInt16LE(42,2); data.writeUInt32LE(8,4); data.writeUInt16LE(3,8);
  const entry = (at,tag,type,count,value) => { data.writeUInt16LE(tag,at); data.writeUInt16LE(type,at+2); data.writeUInt32LE(count,at+4); data.writeUInt32LE(value,at+8); };
  entry(10,0x010f,2,make.length,start); entry(22,0x0131,2,software.length,start+make.length); entry(34,0x8825,4,1,gpsOffset);
  make.copy(data,start); software.copy(data,start+make.length);
  data.writeUInt16LE(1,gpsOffset); entry(gpsOffset+2,2,5,3,gpsOffset+18);
  for(let i=0;i<3;i++){data.writeUInt32LE(i+12,gpsOffset+18+i*8);data.writeUInt32LE(1,gpsOffset+22+i*8);}
  return data;
}
function jpeg(extraMetadata = false) {
  const app = Buffer.concat([Buffer.from("Exif\0\0"),exif()]);
  const length = Buffer.alloc(2);length.writeUInt16BE(app.length+2);
  // Container fixture tests original metadata without any canvas/decode dependency.
  const segment = (marker, data) => { const n=Buffer.alloc(2); n.writeUInt16BE(data.length+2); return Buffer.concat([Buffer.from([255,marker]),n,data]); };
  const xmp = Buffer.from('http://ns.adobe.com/xap/1.0/\0<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:xmp="http://ns.adobe.com/xap/1.0/" xmlns:exif="http://ns.adobe.com/exif/1.0/" xmp:CreatorTool="Invented XMP Editor" xmp:CreateDate="2026-10-24T12:00:00Z" exif:GPSLatitude="private-location"/></rdf:RDF></x:xmpmeta>');
  const program = Buffer.from("Invented IPTC Program");
  const iptc = Buffer.concat([Buffer.from([0x1c,2,65,0,program.length]),program]);
  const size=Buffer.alloc(4);size.writeUInt32BE(iptc.length);
  const photoshop=Buffer.concat([Buffer.from("Photoshop 3.0\0"),Buffer.from("8BIM"),Buffer.from([4,4,0,0]),size,iptc,Buffer.alloc(iptc.length%2)]);
  return Buffer.concat([Buffer.from([255,216,255,225]),length,app,...(extraMetadata ? [segment(225,xmp),segment(237,photoshop)] : []),Buffer.from([255,192,0,11,8,0,1,0,1,1,1,0x11,0,255,217])]);
}
function crc32(data) { let crc = 0xffffffff; for (const byte of data) { crc ^= byte; for(let i=0;i<8;i++) crc = (crc>>>1)^((crc&1)?0xedb88320:0); } return (crc^0xffffffff)>>>0; }
function chunk(type,data) {const t=Buffer.from(type),header=Buffer.alloc(4),crc=Buffer.alloc(4);header.writeUInt32BE(data.length);crc.writeUInt32BE(crc32(Buffer.concat([t,data])));return Buffer.concat([header,t,data,crc]);}
function png(width=1,height=1) {
  const ihdr=Buffer.alloc(13);ihdr.writeUInt32BE(width);ihdr.writeUInt32BE(height,4);ihdr[8]=8;ihdr[9]=2;
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk("IHDR",ihdr),chunk("eXIf",exif()),chunk("IDAT",deflateSync(Buffer.from([0,255,255,255]))),chunk("IEND",Buffer.alloc(0))]);
}
const file = (bytes,type="application/pdf",name="invented.pdf") => new File([bytes],name,{type,lastModified:123456});

test("image failure protocol stays pinned to the audited PDF.js worker artifacts", async()=>{
  const {isFailedPdfImageMessage,PDFJS_IMAGE_PROTOCOL_VERSION}=await import("../src/document-files/pdf-worker-protocol.ts");
  const packageRoot=new URL("../node_modules/pdfjs-dist/",import.meta.url);
  assert.equal(JSON.parse(readFileSync(new URL("package.json",packageRoot))).version,PDFJS_IMAGE_PROTOCOL_VERSION);
  for(const [name,hash] of [
    ["pdf.worker.mjs","07ceb740d746e5d9012fcf9f27d5c7dea09f7d2f5e74f5c8109e5787551a2333"],
    ["pdf.worker.min.mjs","9536359f1b8367850d485731ca1d5e45c159a7b7a0912325e539937aa21ceb18"],
  ]) assert.equal(createHash("sha256").update(readFileSync(new URL(`build/${name}`,packageRoot))).digest("hex"),hash,"Audit image failure plumbing before updating PDF.js");
  assert.equal(isFailedPdfImageMessage({action:"obj",data:["image-id",0,"Image",null]}),true);
  assert.equal(isFailedPdfImageMessage({action:"commonobj",data:["cached-image-id","Image",null]}),true);
  for(const message of [null,{}, {action:"obj",data:["id",0,"Image",{data:new Uint8Array(3)}]},
    {action:"commonobj",data:["id","CopyLocalImage",null]}, {action:"obj",data:["id",0,"Pattern",null]}]) assert.equal(isFailedPdfImageMessage(message),false);
});

test("JPEG and PNG original-byte hash and allowlisted metadata are read before any pixel transform", async () => {
  for (const [bytes,type] of [[jpeg(),"image/jpeg"],[png(),"image/png"]]) {
    const evidence = await inspectFile(file(bytes,type,"untrusted-name"));
    assert.equal(evidence.status,"complete",JSON.stringify(evidence.errors));
    assert.equal(evidence.original.sha256,createHash("sha256").update(bytes).digest("hex"));
    assert.equal(evidence.original.fileSystemClaimsTrust,"untrusted");
    assert.equal(evidence.original.lastModified,123456);
    assert.equal(evidence.metadata.gpsPresence,"present");
    assert.ok(Object.values(evidence.metadata.fields).includes("Invented Camera"));
    assert.ok(Object.values(evidence.metadata.fields).includes("Invented Editor"));
    assert.ok(!JSON.stringify(evidence).includes("GPSLatitude"));
    assert.deepEqual(evidence.image,{width:1,height:1,pixelCount:1});
    assert.equal(evidence.signals.find(s=>s.code==="software_claim").severity,"info");
    assert.equal("authenticityProbability" in evidence,false);
  }
});
test("sniffing overrides untrusted MIME, extension and name without declaring tampering", async()=>{
  const evidence=await inspectFile(file(png(),"application/pdf","statement.pdf"));
  assert.equal(evidence.original.detectedMime,"image/png");assert.equal(evidence.original.mimeMismatch,true);
  assert.ok(evidence.signals.some(s=>s.code==="file_type_mismatch"));
});
test("real PDF parser returns metadata, positioned native text, zero unsigned count, original digest and XMP", async()=>{
  const bytes=pdf({xmp:true});const {evidence,pages}=await inspectDocumentFile(file(bytes));
  assert.equal(evidence.status,"complete",JSON.stringify(evidence.errors));
  assert.equal(evidence.original.sha256,createHash("sha256").update(bytes).digest("hex"));
  assert.equal(evidence.metadata.fields["info.Producer"],"Synthetic Generator");
  assert.equal(evidence.metadata.fields["xmp.xmp:creatortool"],"Synthetic XMP Tool");
  assert.equal(evidence.pdf.signatures.status,"absent");assert.equal(evidence.pdf.signatures.cryptographicVerification,"not_supported");
  assert.equal(evidence.pdf.signatures.fieldCount,0);assert.equal(pages[0].index,0);
  const item=pages[0].text.items[0];assert.equal(item.text,"Invented bank statement 123.45");
  assert.deepEqual(item.transform,[12,0,0,12,20,180]);assert.equal(item.fontSize,12);assert.ok(item.fontName);
  assert.equal(pages[0].text.trust,"untrusted_native_text_not_ocr");
  assert.ok(evidence.signals.some(s=>s.code==="conflicting_dates"));
});
test("signature value presence differs from an empty field; neither claims cryptographic validity",async()=>{
  const signed=await inspectFile(file(pdf({signature:true})));
  assert.equal(signed.pdf.signatures.status,"present_unverified",JSON.stringify(signed));
  assert.equal(signed.pdf.signatures.count,1);assert.equal(signed.pdf.signatures.fieldCount,1);
  const blank=await inspectFile(file(pdf({blankSignature:true})));
  assert.equal(blank.pdf.signatures.status,"unknown");assert.equal(blank.pdf.signatures.fieldCount,1);assert.equal(blank.pdf.signatures.count,0);
});
test("attachments are counted without decompressing their broken payload and JS is not executed",async()=>{
  delete globalThis.DOCUMENT_JS_EXECUTED;
  const evidence=await inspectFile(file(pdf({attachment:true,js:true})));
  assert.equal(evidence.pdf.attachments.status,"checked");assert.equal(evidence.pdf.attachments.count,1);
  assert.equal(evidence.pdf.annotations.count,1);assert.equal(evidence.pdf.documentJavaScriptActions.count,1);
  assert.equal(globalThis.DOCUMENT_JS_EXECUTED,undefined);
  assert.ok(!JSON.stringify(evidence).includes("this-is-not-a-zlib-stream"));
});
test("catalog-only and form-only JavaScript keep their own scopes without executing bodies", async()=>{
  delete globalThis.DOCUMENT_JS_EXECUTED;
  for (const [options, catalog, form] of [[{js:true},1,false],[{formJs:true},0,true],[{},0,false],[{js:true,formJs:true},1,true]]) {
    const evidence=await inspectFile(file(pdf(options)));
    assert.equal(evidence.pdf.documentJavaScriptActions.count,catalog);
    assert.deepEqual(evidence.pdf.formJavaScriptPresence,{status:"checked",present:form});
    assert.equal(globalThis.DOCUMENT_JS_EXECUTED,undefined);
    assert.ok(!JSON.stringify(evidence).includes("DOCUMENT_JS_EXECUTED"));
  }
});
test("field read failures leave form JavaScript unknown independently of catalog actions", async()=>{
  const pdfjs=await import("pdfjs-dist/legacy/build/pdf.mjs");
  const loading=pdfjs.getDocument({data:new Uint8Array(pdf())});
  const doc=await loading.promise;
  const prototype=Object.getPrototypeOf(doc), original=prototype.getFieldObjects;
  prototype.getFieldObjects=()=>Promise.reject(new Error("Invented field read failure"));
  try {
    const evidence=await inspectFile(file(pdf({js:true})));
    assert.equal(evidence.status,"incomplete");
    assert.deepEqual(evidence.pdf.formJavaScriptPresence,{status:"unknown",present:null});
    assert.equal(evidence.pdf.documentJavaScriptActions.count,1);
    assert.ok(evidence.errors.some(error=>error.stage==="pdf_forms"));
  } finally { prototype.getFieldObjects=original; await loading.destroy(); }
});

test("page, text and metadata budgets explicitly report incomplete output",async()=>{
  const evidence=await inspectFile(file(pdf({pages:3,hugeMetadata:true})),{maxPages:2,maxTextChars:12,maxTextItems:1,maxMetadataChars:160,maxStringChars:40});
  assert.equal(evidence.status,"incomplete");assert.equal(evidence.pdf.numPages,3);assert.equal(evidence.pdf.inspectedPages,2);assert.equal(evidence.pdf.omittedPages,1);
  assert.deepEqual(evidence.pdf.pages.map(p=>p.index),[0,1]);
  assert.equal(evidence.pdf.pages[0].text.truncated,true);assert.equal(evidence.pdf.pages[1].text.truncated,true);
  assert.ok(evidence.pdf.pages.flatMap(p=>p.text.items).reduce((n,i)=>n+i.text.length,0)<=12);
  assert.equal(evidence.metadata.truncated,true);
  assert.ok(Object.entries(evidence.metadata.fields).reduce((n,[k,v])=>n+k.length+String(v).length,0)<=160);
});
test("empty, malformed, encrypted, oversized and unsupported inputs fail actionably",async()=>{
  for(const [input,options,code] of [[file(new Uint8Array()),{},"empty_file"],[file(Buffer.from("%PDF-1.7\nnot a document")),{},"invalid_pdf"],[file(pdf({encrypted:true})),{},"encrypted_pdf"],[file(pdf()),{maxBytes:1},"file_too_large"],[file(Buffer.from("<svg/>"),"image/svg+xml"),{},"unsupported_format"],[file(png(10000,10000),"image/png"),{},"image_too_large"],[file(Buffer.from([255,216,255,225,255,255]),"image/jpeg"),{},"malformed_image"]]){
    const evidence=await inspectFile(input,options);assert.equal(evidence.status,"failed");assert.equal(evidence.errors[0].code,code,JSON.stringify(evidence));
  }
});
test("open handle can inspect once, rejects invalid pages and is safely closed twice",async()=>{
  const handle=await openPdf(file(pdf()));
  try{assert.equal(handle.numPages,1);assert.deepEqual(await handle.getEvidence(),await handle.getEvidence());await assert.rejects(handle.renderPage(-1),{code:"invalid_page"});}
  finally{await handle.close();await handle.destroy();}
  assert.throws(()=>handle.getEvidence(),{code:"closed"});
});
test("abort and invalid limits do not masquerade as ordinary evidence failures",async()=>{
  const controller=new AbortController();controller.abort();
  await assert.rejects(inspectFile(file(pdf()),{signal:controller.signal}),{code:"aborted"});
  await assert.rejects(openPdf(file(pdf()),{maxPages:Infinity}),{code:"invalid_limit"});
  await assert.rejects(inspectFile(file(pdf()),{maxPixels:0}),{code:"invalid_limit"});
  const running=new AbortController();const handle=await openPdf(file(pdf({pages:10})),{signal:running.signal});
  const pending=handle.getEvidence();running.abort();await assert.rejects(pending,{code:"aborted"});await handle.close();
});
test("standalone metadata sanitizer is bounded and omits GPS coordinates",async()=>{
  const metadata=await parseImageMetadata(jpeg(),limitsFor({maxMetadataChars:40,maxStringChars:10}));
  assert.equal(metadata.gpsPresence,"present");assert.equal(metadata.truncated,true);
  assert.ok(Object.entries(metadata.fields).reduce((n,[k,v])=>n+k.length+String(v).length,0)<=40);
});

test("header routing reads bounded bytes without trusting MIME or parsing PDF",async()=>{
  const {sniffDocumentKind}=await import("../src/document-files/index.ts");
  assert.equal(await sniffDocumentKind(file(pdf(),"image/jpeg","false.jpg")),"pdf");
  assert.equal(await sniffDocumentKind(file(png(),"application/pdf","false.pdf")),"image");
  assert.equal(await sniffDocumentKind(new Blob(["<svg/>"],{type:"image/png"})),"unsupported");
});

test("browser workers preserve originals, render every PDF page within budget, and cancel", {
  skip: !process.env.DOCSCAN_DOCUMENT_BROWSER_URL,
}, async()=>{
  const {chromium}=await import("playwright-core");
  const browser=await chromium.launch({executablePath:process.env.CHROME??"/usr/bin/google-chrome",headless:true});
  try {
    const page=await browser.newPage();
    const base=process.env.DOCSCAN_DOCUMENT_BROWSER_URL;
    await page.route(`${base}/document-evidence-test`,route=>route.fulfill({contentType:"text/html",body:"<!doctype html><title>Local document evidence tests</title>"}));
    await page.goto(`${base}/document-evidence-test`);
    const requests=[];page.on("request",r=>requests.push({url:r.url(),method:r.method()}));
    const results=await page.evaluate(async ({pdf,png,jpeg,raster,jpx,invalidJpx,blank,moduleUrl})=>{
      let activeWorkers=0,createdWorkers=0;
      const BrowserWorker=globalThis.Worker;
      globalThis.Worker=class extends BrowserWorker {
        live=true;
        constructor(...args){super(...args);activeWorkers++;createdWorkers++;}
        terminate(){if(this.live){this.live=false;activeWorkers--;}super.terminate();}
      };
      const {openPdf,inspectFile}=await import(moduleUrl);
      const decode=(bytes,type)=>new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],"invented",{type});
      const images=[];
      for(const [bytes,type] of [[png,"image/png"],[jpeg,"image/jpeg"]])images.push(await inspectFile(decode(bytes,type)));
      const handle=await openPdf(decode(pdf,"application/pdf"),{maxPixels:1000000});
      const pages=[];
      let evidence;
      try {
        evidence=await handle.getEvidence();
        for(let index=0;index<handle.numPages;index++){
          const pixels=await handle.renderPage(index,{maxPixels:50000});
          pages.push({index,width:pixels.width,height:pixels.height,nonwhite:pixels.data.some((v,i)=>i%4!==3&&v<200)});
        }
      }finally{await handle.close();}
      const rasterHandle=await openPdf(decode(raster,"application/pdf"));
      let rasterResult;
      try { const native=await rasterHandle.getEvidence(); const pixels=await rasterHandle.renderPage(0,{maxPixels:50000}); rasterResult={nativeText:native.pdf.pages[0].text.items.length,colored:pixels.data.some((v,i)=>i%4===0 && v !== pixels.data[i+1])}; } finally { await rasterHandle.close(); }
      const jpxHandle=await openPdf(decode(jpx,"application/pdf"));
      let jpxColored;
      try { const pixels=await jpxHandle.renderPage(0,{maxPixels:50000});jpxColored=pixels.data.some((v,i)=>i%4===0&&v!==pixels.data[i+1]); } finally { await jpxHandle.close(); }
      const failedRenders=[];
      // Both orderings: initial evidence snapshots must not hide later decoder failures.
      for (const [badBytes,inspectFirst] of [[invalidJpx[0],true],[invalidJpx[0],false],[invalidJpx[1],true]]) {
        const broken=await openPdf(decode(badBytes,"application/pdf"));
        try {
          const before=inspectFirst ? await broken.getEvidence() : null;
          let code=null,errorEvidence=null,returnedPixels=false;
          try { await broken.renderPage(0,{maxPixels:50000}); returnedPixels=true; }
          catch(error) { code=error.code; errorEvidence=error.evidence; }
          const after=await broken.getEvidence();
          failedRenders.push({before,code,errorEvidence,after,returnedPixels});
        } finally { await broken.close(); }
      }
      const blankHandle=await openPdf(decode(blank,"application/pdf"));
      let blankRendered;
      try { const pixels=await blankHandle.renderPage(0,{maxPixels:50000}); blankRendered=pixels.data.every(v=>v===255); } finally { await blankHandle.close(); }
      const abort=new AbortController();const cancelled=await openPdf(decode(pdf,"application/pdf"),{signal:abort.signal});
      const pending=cancelled.getEvidence();abort.abort();let abortCode;
      try{await pending;}catch(error){abortCode=error.code;}finally{await cancelled.close();}
      const renderAbort=new AbortController();const interrupted=await openPdf(decode(pdf,"application/pdf"));
      let renderAbortCode;
      try { const pendingRender=interrupted.renderPage(0,{signal:renderAbort.signal});renderAbort.abort();try{await pendingRender;}catch(error){renderAbortCode=error.code;} } finally { await interrupted.close(); }
      return {failedRenders,blankRendered,images,evidence,pages,abortCode,rasterResult,jpxColored,renderAbortCode,activeWorkers,createdWorkers};
    },{moduleUrl:process.env.DOCSCAN_DOCUMENT_MODULE_URL??"/src/document-files/index.ts",pdf:pdf({pages:2,xmp:true}).toString("base64"),raster:pdf({raster:true}).toString("base64"),jpx:pdf({jpx:jpxFixture}).toString("base64"),invalidJpx:[Buffer.from("invented invalid JPEG2000 image"),Buffer.from(jpxFixture,"base64").subarray(0,160)].map(bytes=>pdf({jpx:bytes.toString("base64")}).toString("base64")),blank:pdf({text:""}).toString("base64"),png:png().toString("base64"),jpeg:jpeg().toString("base64")});
    for(const image of results.images){assert.equal(image.status,"complete",JSON.stringify(image.errors));assert.equal(image.metadata.gpsPresence,"present");assert.equal(image.original.sha256.length,64);}
    assert.equal(results.evidence.status,"complete",JSON.stringify(results.evidence.errors));
    assert.deepEqual(results.pages.map(p=>p.index),[0,1]);
    assert.ok(results.pages.every(p=>p.width*p.height<=50000&&p.nonwhite));
    for (const failure of results.failedRenders) {
      assert.equal(failure.returnedPixels,false);
      assert.equal(failure.code,"pdf_image_decode_failed",JSON.stringify(failure));
      assert.equal(failure.after.status,"incomplete");
      assert.equal(failure.after.pdf.pages[0].status,"incomplete");
      assert.ok(failure.after.errors.some(error=>error.code==="pdf_image_decode_failed"));
      assert.equal(failure.errorEvidence.status,"incomplete");
      if(failure.before) assert.equal(failure.before.status,"complete");
    }
    assert.equal(results.blankRendered,true,"A legitimate blank page must render successfully");
    assert.equal(results.abortCode,"aborted");
    assert.deepEqual(results.rasterResult,{nativeText:0,colored:true});assert.equal(results.jpxColored,true);
    assert.equal(results.renderAbortCode,"aborted");assert.equal(results.activeWorkers,0);assert.ok(results.createdWorkers>=5);
    assert.ok(requests.every(r=>r.method==="GET"&&(r.url.startsWith(base)||r.url.startsWith("data:"))),JSON.stringify(requests));
  }finally{await browser.close();}
});


test("JPEG XMP and IPTC claims are allowlisted without exposing GPS or treating editors as proof",async()=>{
  const evidence=await inspectFile(file(jpeg(true),"image/jpeg"));
  assert.equal(evidence.status,"complete",JSON.stringify(evidence));
  assert.ok(Object.values(evidence.metadata.fields).includes("Invented XMP Editor"));
  assert.ok(Object.values(evidence.metadata.fields).includes("Invented IPTC Program"));
  assert.equal(evidence.metadata.gpsPresence,"present");
  assert.ok(!JSON.stringify(evidence).includes("private-location"));
  assert.ok(evidence.signals.every(s=>s.severity==="info"));
});


test("read failures and deadline expiration remain actionable and cancel owned work",async()=>{
  class FailedBlob extends Blob { arrayBuffer(){return Promise.reject(new Error("synthetic read failure"));} }
  const evidence=await inspectFile(new FailedBlob(["bytes"]));
  assert.equal(evidence.status,"failed");assert.equal(evidence.errors[0].code,"file_read_error");
  const {bounded}=await import("../src/document-files/common.ts");let cancelled=0;
  await assert.rejects(bounded(new Promise(()=>{}),1,undefined,()=>cancelled++),{code:"timeout"});
  assert.equal(cancelled,1);
});

test("worker startup failure settles timeout and abort and terminates the owned port", {
  skip: !process.env.DOCSCAN_DOCUMENT_BROWSER_URL,
}, async () => {
  const { chromium } = await import("playwright-core");
  const browser = await chromium.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", headless: true });
  try {
    const page = await browser.newPage();
    const base = process.env.DOCSCAN_DOCUMENT_BROWSER_URL;
    await page.route(`${base}/worker-startup-test`, route => route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Worker startup regression</title>" }));
    await page.goto(`${base}/worker-startup-test`);
    const args = { moduleUrl: process.env.DOCSCAN_DOCUMENT_MODULE_URL ?? "/src/document-files/index.ts", bytes: pdf({ text: "" }).toString("base64") };
    // Load the real runtime and complete one normal startup before blocking only
    // subsequent worker scripts, rather than blocking the module import itself.
    await page.evaluate(async ({ moduleUrl, bytes }) => {
      const api = await import(moduleUrl);
      const file = new Blob([Uint8Array.from(atob(bytes), c => c.charCodeAt(0))]);
      const handle = await api.openPdf(file); await handle.close();
    }, args);
    await page.route(url => url.pathname.includes("pdf.worker.min"), route => route.abort());
    const results = await page.evaluate(async ({ moduleUrl, bytes }) => {
      const api = await import(moduleUrl);
      let created = 0, terminated = 0;
      const NativeWorker = Worker;
      globalThis.Worker = class extends NativeWorker {
        constructor(...args) { super(...args); created++; }
        terminate() { terminated++; return super.terminate(); }
      };
      const codes = [];
      for (const cancel of [false, true]) {
        const controller = new AbortController();
        const pending = api.openPdf(new Blob([Uint8Array.from(atob(bytes), c => c.charCodeAt(0))]), { timeoutMs: cancel ? 1000 : 100, signal: controller.signal });
        const abortTimer = cancel ? setTimeout(() => controller.abort(), 50) : null;
        let watchdog;
        try {
          codes.push(await Promise.race([
            pending.then(async handle => { await handle.close(); return "unexpected_success"; }, error => error.code),
            new Promise(resolve => { watchdog = setTimeout(() => resolve("still_pending"), 1500); }),
          ]));
        } finally { clearTimeout(watchdog); clearTimeout(abortTimer); }
      }
      return { codes, created, terminated };
    }, args);
    assert.deepEqual(results.codes, ["timeout", "aborted"]);
    assert.equal(results.created, 2); assert.equal(results.terminated, 2);
  } finally { await browser.close(); }
});
