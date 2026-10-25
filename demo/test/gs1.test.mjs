import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {transformWithEsbuild} from 'vite';
const root=new URL('../src/gs1/',import.meta.url);
const dictionary=await transformWithEsbuild(readFileSync(new URL('dictionary.ts',root),'utf8'),'dictionary.ts');
let {code}=await transformWithEsbuild(readFileSync(new URL('index.ts',root),'utf8'),'index.ts');
code=code.replace('"./dictionary"',JSON.stringify(`data:text/javascript,${encodeURIComponent(dictionary.code)}`));
const {parseGs1,gs1Checksum}=await import(`data:text/javascript,${encodeURIComponent(code)}`);
const gtin='09506000134352',gs='\x1d';
test('explicit GS1 carrier extracts GTIN, lot, serial and expiry without OCR',()=>{
 const r=parseGs1(`]C101${gtin}1726120010LOT-ABC${gs}21SERIAL-42`);
 assert.equal(r.status,'parsed');assert.equal(r.identifiers.gtin,gtin);assert.equal(r.identifiers.lot,'LOT-ABC');assert.equal(r.identifiers.serial,'SERIAL-42');
 assert.deepEqual(r.fields.find(f=>f.ai==='17').date,{yearTwoDigits:26,month:12,day:null,endOfMonth:true});
 assert.equal(r.fields[0].checks.checksum,true);assert.ok(r.warnings.includes('two_digit_year_requires_century_policy'));
});
test('ordinary numeric barcodes and literal scanner-looking text are not guessed as GS1',()=>{
 assert.equal(parseGs1(`01${gtin}21SN`).status,'not_gs1');
 assert.equal(parseGs1(`]C101${gtin}`,{symbologyIdentifier:']C0'}).status,'not_gs1');
 assert.equal(parseGs1(`01${gtin}`,{symbologyIdentifier:']d2'}).identifiers.gtin,gtin);
 assert.equal(parseGs1('a retail label').status,'not_gs1');
});
test('variable-length fields consume to FNC1/end; numeric-looking serials are not split',()=>{
 const r=parseGs1(`]C101${gtin}10ABC17261231`);
 assert.equal(r.fields.length,2);assert.equal(r.identifiers.lot,'ABC17261231');
 assert.equal(parseGs1(`]C110${'A'.repeat(21)}21SN`).status,'invalid');
});
test('non-predefined fixed fields still require separators and IMEIs remain strings',()=>{
 const r=parseGs1(`]C101${gtin}21SN${gs}8040351204123456785${gs}8041351204123456793`);
 assert.equal(r.identifiers.imei1,'351204123456785');assert.equal(r.identifiers.imei2,'351204123456793');
 assert.equal(parseGs1(`]C180403512041234567858041351204123456793`).status,'invalid');
});
test('human-readable syntax retains source positions and malformed/unknown fields are explicit',()=>{
 const input=`(01)${gtin}(10)LOT(21)SN`;
 const r=parseGs1(input);assert.equal(r.syntax,'human_readable');
 for(const f of r.fields)assert.equal(input.slice(f.start,f.end),f.value);
 assert.equal(parseGs1('(8888)unknown').status,'unsupported');
 assert.equal(parseGs1(`]C101${gtin}8888unknown`).status,'unsupported');
 assert.equal(parseGs1(`]C101${gtin.slice(0,-1)}1`).status,'invalid');
 assert.equal(gs1Checksum(gtin),true);
});
test('Digital Link is parsed locally with qualifier order, percent decoding and duplicate checks',()=>{
 const r=parseGs1(`https://example.invalid/products/01/${gtin}/10/LOT%2FA/21/SN%2B1?17=261231&linkType=example`);
 assert.equal(r.status,'parsed');assert.equal(r.identifiers.lot,'LOT/A');assert.equal(r.identifiers.serial,'SN+1');
 assert.equal(r.fields.find(f=>f.ai==='17').date.month,12);
 assert.equal(parseGs1(`https://example.invalid/01/${gtin}/21/SN/10/LOT`).status,'invalid');
 assert.equal(parseGs1(`https://example.invalid/01/${gtin}?01=${gtin}`).status,'invalid');
 assert.equal(parseGs1(`https://example.invalid/01/${gtin}/21/%ZZ`).status,'invalid');
 assert.equal(parseGs1(`https://example.invalid/01/${gtin}?10=A+B`).identifiers.lot,'A+B');
 assert.equal(parseGs1('https://example.invalid/some/other/page').status,'not_gs1');
});
test('invalid dates, duplicate IDs, unsupported rules and exact decimals remain visible',()=>{
 assert.equal(parseGs1(`(01)${gtin}(17)260230`).status,'invalid');
 assert.equal(parseGs1(`(01)${gtin}(17)240229`).status,'parsed');
 const dup=parseGs1(`(01)${gtin}(21)ONE(21)TWO`);assert.equal(dup.status,'invalid');assert.equal(dup.identifiers.serial,undefined);
 const weight=parseGs1(`(01)${gtin}(3102)001234`);assert.deepEqual(weight.fields[1].decimal,{value:'12.34',unit:'kg'});
 const price=parseGs1('(3912)710001234');assert.deepEqual(price.fields[0].decimal,{value:'12.34',unit:null,currencyCode:'710'});
 assert.ok(price.fields[0].uncheckedRules.includes('iso4217'));
});
test('optional components cannot be partially truncated and parsing is bounded',()=>{
 assert.equal(parseGs1(`(01)${gtin}(8008)26102512`).status,'parsed');
 assert.equal(parseGs1('(8008)261025121').status,'invalid');
 assert.ok(parseGs1('(90)'+ 'A'.repeat(9000)).errors.includes('input_limit'));
 assert.equal(parseGs1(`]C1${gs}01${gtin}`).status,'invalid');
});

test('incomplete and invalid carriers expose observations but never normalized identifiers',()=>{
 for(const input of [']C121ABC123',']C18040351204123456785']){
  const r=parseGs1(input);assert.equal(r.status,'incomplete');assert.deepEqual(r.identifiers,{});assert.ok(r.fields.length);
 }
 for(const input of [`]C101${gtin}1726`,`https://example.invalid/01/${gtin}/10/LOT/22/V`,`https://example.invalid/01/${gtin}?21=SERIAL`]){
  const r=parseGs1(input);assert.equal(r.status,'invalid');assert.deepEqual(r.identifiers,{});
 }
 assert.equal(parseGs1('10614141000415',{symbologyIdentifier:']e0'}).status,'not_gs1');
});
test('Digital Link rejects URL normalization and retains exact raw path offsets',()=>{
 for(const path of [`/x/../01/${gtin}/21/SERIAL`,`//01/${gtin}/21/SERIAL`,`/01/${gtin}//21/SERIAL`]){
  const r=parseGs1('https://example.invalid'+path);assert.equal(r.status,'invalid');assert.deepEqual(r.identifiers,{});
 }
 assert.equal(parseGs1(`https://example.invalid\\01\\${gtin}\\21\\SERIAL`).status,'invalid');
 const input=`https://example.invalid/stem/01/${gtin}/21/SER%2F123`;
 const r=parseGs1(input);for(const f of r.fields)assert.equal(decodeURIComponent(input.slice(f.start,f.end)),f.value);
 const badDate=parseGs1('(7007)251399250101');assert.equal(badDate.fields[0].checks.calendar,false);
});

test('CSET64 follows the pinned GS1 optional-padding rule without verifying signatures',()=>{
 const good=parseGs1(`(01)${gtin}(21)SERIAL(8030)AAAA==`);
 assert.equal(good.status,'parsed');assert.equal(good.fields.at(-1).checks.format,true);
 assert.equal(parseGs1(`(01)${gtin}(21)SERIAL(8030)AA=A`).status,'invalid');
 assert.equal(good.interpretation,'parsed_data_not_product_or_issuer_verification');
});
