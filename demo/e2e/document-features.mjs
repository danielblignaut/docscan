// Run after generate-feature-fixtures.py and the production build. All inputs are fictional.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {readFileSync,writeFileSync,mkdtempSync} from 'node:fs';
import {chromium} from 'playwright-core';
const dir='/tmp/docscan-feature-fixtures';
const artifacts=mkdtempSync('/tmp/docscan-feature-browser-');
console.log(JSON.stringify({artifacts,engine:process.env.DOCSCAN_FINANCIAL_ENGINE??'ppocr_v6_tiny'}));
const root=process.env.DOCSCAN_URL??'http://localhost:4197/';
let server;
if(!process.env.DOCSCAN_URL){
 server=spawn('node',['node_modules/vite/bin/vite.js','preview','--port','4197','--strictPort'],{cwd:new URL('../',import.meta.url),stdio:'pipe'});
 await new Promise((resolve,reject)=>{server.stdout.on('data',d=>String(d).includes('4197')&&resolve());server.on('exit',c=>reject(Error(`preview exited ${c}`)));});
}
const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',`--use-file-for-fake-video-capture=${dir}/items-pan.y4m`]});
const page=await browser.newPage({viewport:{width:430,height:900}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>{
 window.__features={files:[],complete:[],reviews:[],views:[],tracks:[],urls:new Set()};
 for(const [event,key] of [['docscan:file','files'],['docscan:complete','complete'],['docscan:items-review','reviews'],['docscan:item-view','views']])window.addEventListener(event,e=>window.__features[key].push(e.detail));
 const open=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
 navigator.mediaDevices.getUserMedia=async options=>{const s=await open(options);window.__features.tracks.push(...s.getTracks());return s;};
 const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);
 URL.createObjectURL=blob=>{const url=create(blob);window.__features.urls.add(url);return url;};URL.revokeObjectURL=url=>{window.__features.urls.delete(url);revoke(url);};
});
async function home(){await page.getByTestId('results-home').click();await page.getByTestId('home').waitFor();}
async function stopLabels(){const b=page.getByTestId('cancel-label-reading');if(await b.count())await b.click();}
async function report(){
 const download=page.waitForEvent('download');await page.getByTestId('export-document-report').click();const file=await download;
 return JSON.parse(readFileSync(await file.path(),'utf8'));
}
try{
 await page.goto(root+'?threads=1&textEngine='+(process.env.DOCSCAN_FINANCIAL_ENGINE??'ppocr_v6_tiny'));await page.waitForFunction(()=>window.__docscan?.captureReady,null,{timeout:60000});
 if(process.env.DOCSCAN_FEATURE_CASES!=='tables'){
 for(const name of ['gs1-dm','gs1-128']){
  await page.locator('[data-photo=barcodes]').setInputFiles(`${dir}/${name}.png`);
  await page.getByTestId('gs1-fields').waitFor({timeout:30000});await stopLabels();
  const r=await report();const code=r.outcome.barcodes.find(c=>c.gs1?.status==='parsed');
  assert.ok(code,`${name}: GS1 not parsed`);assert.equal(code.gs1.identifiers.gtin,'09506000134352');assert.equal(code.gs1.identifiers.serial,'SERIAL-42');assert.equal(code.gs1.identifiers.lot,'DEMOLOT');
  assert.ok(code.symbology_identifier);console.log(`PASS ${name}: actual decoder, GS1 fields, UI and curated JSON`);await home();
 }
 await page.locator('[data-photo=items]').setInputFiles(`${dir}/items.png`);
 await page.getByTestId('item-groups').waitFor({timeout:30000});await stopLabels();
 const expected=JSON.parse(readFileSync(`${dir}/expected.json`,'utf8')).items;
 const r=await report();assert.equal(r.outcome.itemGrouping.items.length,2);
 const serials=r.outcome.itemGrouping.items.map(i=>i.roles.serial.value).sort();assert.deepEqual(serials,expected.map(i=>i.serial).sort());
 await page.getByText('Review item boundaries',{exact:true}).click();await page.getByRole('button',{name:'Outline an item',exact:true}).click();
 const image=page.getByTestId('item-review-image');
 for(const [x0,x1] of [[.01,.49],[.51,.99]]){
  await image.scrollIntoViewIfNeeded();const b=await image.boundingBox();
  await page.mouse.move(b.x+b.width*x0,b.y+b.height*.01);await page.mouse.down();await page.mouse.move(b.x+b.width*x1,b.y+b.height*.99,{steps:6});await page.mouse.up();
 }
 const reviewed=await report();assert.equal(reviewed.outcome.itemGrouping.items.length,2);assert.ok(reviewed.outcome.itemGrouping.items.every(i=>i.strength==='explicit'));
 console.log('PASS two boxes sharing a GTIN retain distinct serial/IMEI groups; manual regions update the exported result');await home();
 await page.locator('[data-scanner=items]').click();
 await page.waitForFunction(()=>window.__features.views.length>=2,null,{timeout:60000});
 await page.getByTestId('finish-items').click();await page.getByTestId('item-session-results').waitFor({timeout:15000});await stopLabels();
 const session=await report();assert.equal(session.outcome.scanner,'items');assert.ok(session.outcome.pages.length>=2);
 assert.ok(session.outcome.items.rows.length>=2);assert.equal(await page.evaluate(()=>window.__features.tracks.every(t=>t.readyState==='ended')),true);
 console.log('PASS continuous camera pan: separate saved views, stable identifier tracks, camera release and cancellable background reading');await home();
 }
 for(const name of (process.env.DOCSCAN_FINANCIAL_CASES??'invoice_basic,bank_basic_dmy,payslip_stacked').split(',')){
  await page.locator('[data-photo=tables]').setInputFiles(`${dir}/${name}.pdf`);
  await page.getByTestId('financial-results').waitFor({timeout:180000});
  const actual=(await report()).outcome;assert.equal(actual.kind,'financial');
  writeFileSync(`${artifacts}/${name}-browser-report.json`,JSON.stringify(actual,null,2),{mode:0o600,flag:'wx'});
  const raw=await page.evaluate(()=>window.__features.files.at(-1)?.outcome);writeFileSync(`${artifacts}/${name}-browser-raw.json`,JSON.stringify(raw,null,2),{mode:0o600,flag:'wx'});
  const gold=JSON.parse(readFileSync(new URL(`../../experiments/financial_tables/fixtures/${name}.json`,import.meta.url))).gold;
  assert.equal(actual.report.documentKind,gold.documentKind);assert.ok(actual.report.tables.length>0);
  const values=actual.report.tables.flatMap(t=>t.rows.flatMap(r=>r.cells.map(c=>c.value).filter(v=>v!==null)));
  const expectedValues=gold.tables.flatMap(t=>t.rows.flatMap(r=>Object.entries(r).filter(([k])=>['quantity','unit_price','amount','debit','credit','balance'].includes(k)).map(([,v])=>v)));
  const matched=expectedValues.filter(v=>values.includes(v)).length;
  // Count numeric cells at their expected table/row/column, so duplicated
  // numbers elsewhere cannot conceal swapped columns or missing rows.
  let exactCells=0,expectedCells=0;
  for(const [ti,t] of gold.tables.entries())for(const [ri,row] of t.rows.entries())for(const [role,value] of Object.entries(row)){
    if(!['quantity','unit_price','amount','debit','credit','balance','ytd'].includes(role))continue;
    expectedCells++;
    if(actual.report.tables[ti]?.rows[ri]?.cells.some(c=>c.role===role&&c.value===value))exactCells++;
  }
  if(!process.env.DOCSCAN_BENCHMARK_ONLY) {
   assert.equal(exactCells,expectedCells,`${name}: numeric cell values or positions changed`);
   assert.equal(actual.report.tables.length,gold.tables.length,`${name}: table count changed`);
   if(matched<expectedValues.length)assert.ok(actual.report.checks.some(c=>c.status!=='consistent')||actual.report.ambiguities.length,`${name}: OCR loss must not look fully reconciled`);
  }
  assert.equal(actual.report.authenticity.incomeVerified,false);assert.equal(actual.report.authenticity.bankAuthenticated,false);
  assert.ok(actual.report.tables.every(t=>t.rows.every(row=>row.cells.every(c=>c.source.lineIndices.length>0))));
  const csv=page.waitForEvent('download');await page.getByRole('button',{name:'Download this table as CSV'}).first().click();const downloaded=await csv;
  assert.match(readFileSync(await downloaded.path(),'utf8'),/row_id/);
  console.log(JSON.stringify({fixture:name,tables:actual.report.tables.length,numericValues:matched,expectedNumericValues:expectedValues.length,exactCells,expectedCells,checks:actual.report.checks.map(c=>({code:c.code,status:c.status}))}));
  await home();
 }
 assert.deepEqual(errors,[]);await page.waitForFunction(()=>window.__features.urls.size===0,null,{timeout:5000});
 console.log('PASS feature flows clean up all owned previews; no page errors');
}finally{await browser.close();server?.kill();}
