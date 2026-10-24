// Production UI regression using only locally generated, fictional PDFs.
// Follows the repository's Playwright e2e workflow; starts its own preview.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright-core';

function pdf(pages = 2, hidden = true) {
  const objects = ['', '', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    '<< /Producer (Invented document generator) /CreationDate (D:20261024120000Z) >>'];
  const kids = [];
  for (let i = 0; i < pages; i++) {
    const content = `BT /F1 22 Tf 36 520 Td (FICTIONAL STATEMENT PAGE ${i + 1}) Tj 0 -48 Td (ACCOUNT BALANCE 1234.50) Tj 0 -48 Td (Synthetic evidence test only) Tj ${hidden ? '3 Tr 0 -48 Td (HIDDEN AMOUNT 99999.00) Tj' : ''} ET`;
    objects.push(`<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`);
    const stream = objects.length;
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 500 600] /Resources << /Font << /F1 3 0 R >> >> /Contents ${stream} 0 R >>`);
    kids.push(`${objects.length} 0 R`);
  }
  objects[0] = '<< /Type /Catalog /Pages 2 0 R >>';
  objects[1] = `<< /Type /Pages /Count ${pages} /Kids [${kids.join(' ')}] >>`;
  let body = '%PDF-1.7\n';
  const offsets = [0];
  for (const [i, object] of objects.entries()) { offsets.push(Buffer.byteLength(body)); body += `${i + 1} 0 obj\n${object}\nendobj\n`; }
  const start = Buffer.byteLength(body);
  body += `xref\n0 ${offsets.length}\n0000000000 65535 f \n${offsets.slice(1).map(n => `${String(n).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size ${offsets.length} /Root 1 0 R /Info 4 0 R >>\nstartxref\n${start}\n%%EOF\n`;
  return Buffer.from(body);
}
const server = spawn('node', ['node_modules/vite/bin/vite.js', 'preview', '--port', '4187', '--strictPort', ...(process.env.DOCSCAN_TEST_BUILD ? ['--outDir', process.env.DOCSCAN_TEST_BUILD] : [])], { cwd: new URL('../', import.meta.url), env: { ...process.env, DOCSCAN_BASE: process.env.DOCSCAN_TEST_BASE ?? '/' }, stdio: 'pipe' });
await new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error('Preview start timed out')), 15000);
  server.stdout.on('data', d => { if (String(d).includes('4187')) { clearTimeout(timer); resolve(); } });
  server.on('exit', code => { clearTimeout(timer); reject(new Error(`Preview exited ${code}`)); });
});
const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome' });
const page = await browser.newPage({ viewport: { width: 540, height: 960 } });
const errors = [], disallowedRequests = [];
page.on('pageerror', e => errors.push(e.message));
page.on('request', r => { if (!r.url().startsWith('http://localhost:4187/') && !/^(blob:|data:)/.test(r.url()) || r.method() !== 'GET') disallowedRequests.push(r.url()); });
await page.addInitScript(() => {
  window.__files = []; window.__cameraEvents = []; window.__objectUrls = new Set(); window.__workers = new Set();
  window.addEventListener('docscan:file', e => window.__files.push(e.detail.outcome));
  window.addEventListener('docscan:complete', e => window.__cameraEvents.push(e.detail));
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
  URL.createObjectURL = blob => { const url = create(blob); window.__objectUrls.add(url); return url; };
  URL.revokeObjectURL = url => { window.__objectUrls.delete(url); revoke(url); };
  const NativeWorker = window.Worker;
  window.Worker = class extends NativeWorker {
    constructor(...args) { super(...args); window.__workers.add(this); }
    terminate() { window.__workers.delete(this); return super.terminate(); }
  };
});
async function upload(scanner, bytes, name = 'invented.pdf', mimeType = 'application/pdf') {
  await page.locator(`[data-photo="${scanner}"]`).setInputFiles({ name, mimeType, buffer: bytes });
  await page.locator('[data-testid="results"]').waitFor({ timeout: 180000 });
  return page.evaluate(() => window.__files.at(-1));
}
async function home() {
  await page.locator('[data-testid="results-home"]').click();
  await page.locator('[data-testid="home"]').waitFor();
  await page.waitForFunction(() => window.__objectUrls.size === 0);
  assert.equal(await page.evaluate(() => window.__workers.size), 1, 'only the reusable OCR worker remains');
}
try {
  await page.goto(`http://localhost:4187${process.env.DOCSCAN_TEST_BASE ?? '/'}?threads=${process.env.DOCSCAN_TEST_THREADS ?? '1'}`);
  await page.waitForFunction(() => window.__docscan?.ready, null, { timeout: 60000 });
  const bytes = pdf();
  const result = await upload('text', bytes, 'misnamed.jpg', 'image/jpeg');
  assert.equal(result.kind, 'batch'); assert.equal(result.pages.length, 2);
  const evidence = result.documentEvidence;
  assert.equal(evidence.files.length, 1);
  assert.equal(evidence.files[0].status, 'complete');
  assert.equal(evidence.files[0].original.sha256, createHash('sha256').update(bytes).digest('hex'));
  assert.equal(evidence.files[0].original.mimeMismatch, true);
  assert.deepEqual(evidence.inputs.map(i => i.pageIndex), [0, 1]);
  assert.equal(evidence.files[0].metadata.fields['info.Producer'], 'Invented document generator');
  assert.equal(evidence.files[0].pdf.signatures.status, 'absent');
  assert.equal(evidence.authenticity.isAuthentic, null); assert.equal(evidence.authenticity.isTampered, null);
  assert.equal(evidence.authenticity.issuerVerified, false);
  for (const [i, child] of result.pages.entries()) {
    assert.equal(child.kind, 'text'); assert.equal(child.meta.input.pageIndex, i);
    assert.match(child.result.text, /FICTIONAL STATEMENT/); assert.doesNotMatch(child.result.text, /99999/);
    const comparison = evidence.comparisons[i].result;
    assert.equal(comparison.status, 'compared'); assert.equal(comparison.isTampered, null);
    assert.ok(comparison.numericDisagreements.nativeOnly.includes('99999.00'));
  }
  assert.equal(await page.getByLabel('Extracted text', { exact: true }).count(), 2);
  assert.equal(await page.evaluate(() => window.__cameraEvents.length), 0);
  const downloadPromise = page.waitForEvent('download');
  await page.locator('[data-testid="export-document-report"]').click();
  const download = await downloadPromise;
  const report = JSON.parse(await readFile(await download.path(), 'utf8'));
  assert.equal(report.outcome.evidence.files[0].original.sha256, evidence.files[0].original.sha256);
  assert.equal(report.outcome.pages.length, 2);
  assert.equal(report.authenticity.isAuthentic, null);
  assert.doesNotMatch(JSON.stringify(report), /blob:|"imageUrl"|"alignedRGBA"|"template"/);
  console.log('PASS original hash/MIME, two rendered pages, hidden text discrepancy, honest authenticity, UI');
  await home();

  const id = await upload('passport', pdf(1, false));
  assert.equal(id.kind, 'id'); assert.equal(id.captured.length, 1);
  assert.equal(id.captured[0].result.copy_assessment.status, 'unknown');
  assert.equal(id.captured[0].result.copy_assessment.is_copy, null);
  assert.equal(id.captured[0].result.copy_assessment.confidence, null);
  assert.equal(id.documentEvidence.comparisons[0].result.status, 'not_comparable');
  assert.equal(id.captured[0].result.accepted, false, 'a fictional statement cannot become an accepted passport');
  console.log('PASS WASM identity copy fields serialize as explicit null, no false acceptance');
  await home();

  const invalid = await upload('text', Buffer.from('%PDF-1.7\nnot a document'));
  assert.equal(invalid.kind, 'file_error');
  assert.equal(invalid.documentEvidence.files[0].status, 'failed');
  console.log('PASS malformed PDF retains failed evidence');
  await home();
  assert.deepEqual(errors, []); assert.deepEqual(disallowedRequests, []);
  console.log('PASS all owned object URLs released, PDF workers terminated, no external requests');
} finally { await browser.close(); server.kill(); }
