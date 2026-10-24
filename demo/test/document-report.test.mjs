import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { transformWithEsbuild } from 'vite';
const path = new URL('../src/document-report.ts', import.meta.url).pathname;
let { code } = await transformWithEsbuild(readFileSync(path, 'utf8'), path);
const typesPath = new URL('../src/types.ts', import.meta.url).pathname;
const typesCode = (await transformWithEsbuild(readFileSync(typesPath, 'utf8'), typesPath)).code;
code = code.replace('"./types"', JSON.stringify(`data:text/javascript,${encodeURIComponent(typesCode)}`));
const { createDocumentReport, documentReportJson, reportCopyAssessment, sourceLabel } = await import(`data:text/javascript,${encodeURIComponent(code)}`);
const input = { fileIndex: 1, name: 'synthetic-sheet.pdf', sha256: 'a'.repeat(64), source: 'rendered_pdf_page', pageIndex: 2, pageCount: 4 };
const meta = { source: 'pdf', input, captureMs: 20, frames: 1 };
const copy = { status: 'unknown', is_copy: null, confidence: null, signals: [{ code: 'periodicity', value: .4 }], limitations: ['no_validated_copy_detector'] };
const secret = { template: [92374.123], alignedRGBA: [173, 25, 42], imageUrl: 'blob:https://local.invalid/portrait', blob: new Blob(['synthetic image bytes']) };
const count = { status: 'checked', count: 0, capped: false, scope: 'synthetic fixture' };
const file = {
 schemaVersion: 1, status: 'incomplete',
 original: { sha256: input.sha256, sizeBytes: 99, name: input.name, lastModified: null, fileSystemClaimsTrust: 'untrusted', declaredMime: 'application/pdf', detectedMime: 'application/pdf', mimeCheck: 'checked', mimeMismatch: false },
 metadata: { status: 'checked', fields: { Creator: 'Synthetic generator' }, truncated: false, gpsPresence: 'unknown', trust: 'self_reported_unverified' }, image: null,
 pdf: { numPages: 4, inspectedPages: 1, omittedPages: 3, pages: [{ index: 2, width: 100, height: 200, rotation: 0, status: 'complete', text: { status: 'checked', trust: 'untrusted_native_text_not_ocr', truncated: false, items: [{ text: 'Synthetic amount 100', transform: [1,0,0,1,0,0], width: 50, height: 12, fontName: 'f1', fontFamily: 'sans', fontSize: 12, hasEOL: true }] }, annotations: count, javaScriptActions: count }], annotations: count, formFields: count, attachments: count, documentJavaScriptActions: count, formJavaScriptPresence: { status: 'unknown', present: null }, signatures: { status: 'absent', check: 'checked', count: 0, fieldCount: 1, cryptographicVerification: 'not_supported', issuerTrust: 'not_supported' } },
 signals: [{ code: 'limit', severity: 'warning', source: 'inspection', observed: 'Three pages omitted', limitations: 'Bounded inspection' }], errors: [{ code: 'limit', stage: 'pdf', message: 'Page limit', pageIndex: 3 }], limitations: ['No issuer authentication'],
};
const evidence = { schemaVersion: 1, files: [file], inputs: [input], comparisons: [{ input, result: { status: 'compared', method: 'normalized_token_multiset_v1', nativeTokens: 3, ocrTokens: 3, sharedTokens: 2, nativeTokenCoverage: 2/3, ocrTokenSupport: 2/3, nativeOnlySample: ['100'], ocrOnlySample: ['900'], numericDisagreements: { nativeOnly: ['100'], ocrOnly: ['900'] }, reason: 'Readings differ', isTampered: null } }], authenticity: { status: 'not_verified', isAuthentic: null, isTampered: null, issuerVerified: false } };
const document = { kind: 'unknown', accepted: false, copy_assessment: copy, reasons: ['synthetic'], quality: { sharpness: 1, glare: 0, brightness: 100, edge_density: .1 }, printed: { surname: 'Synthetic', names: null, id_number: null }, mrz: null, smart_id_barcode: null, id_barcode: null, barcodes: [], lines: [{ text: 'Synthetic', x: 0, y: 0, w: 10, h: 10 }], mrz_lines: [], skew: 0, quarter_turns: 0, ocr_passes: 1, ...secret };

test('copy abstention preserves nulls and observed signals without inventing confidence', () => {
 const assessment = reportCopyAssessment(copy);
 assert.equal(assessment.is_copy, null); assert.equal(assessment.confidence, null);
 assert.deepEqual(assessment.signals, copy.signals);
 assert.match(assessment.confidenceInterpretation, /Not a calibrated/);
 assert.equal(reportCopyAssessment(undefined).status, 'unknown');
});
test('source labels distinguish zero-based file/page indices from human-readable numbering', () => {
 assert.equal(sourceLabel(input), 'File 2: synthetic-sheet.pdf · PDF page 3 of 4');
 assert.match(sourceLabel({ ...input, pageIndex: null }), /page unknown/);
 assert.match(sourceLabel({ ...input, source: 'uploaded_image', pageIndex: null }), /uploaded image/);
});
test('batch export retains per-page provenance, failed pages and incomplete file evidence', () => {
 const outcome = { kind: 'batch', scanner: 'text', meta, documentEvidence: evidence, pages: [
  { kind: 'id', scanner: 'id', meta, captured: [{ step: 'Synthetic page', result: document, input, fallback: true, ...secret }] },
  { kind: 'file_error', meta: { ...meta, input: { ...input, pageIndex: 3 } }, message: 'Synthetic rendering failure' },
 ] };
 const report = createDocumentReport(outcome);
 assert.equal(report.outcome.pages[0].captured[0].document.printed.surname, 'Synthetic');
 assert.equal(report.outcome.pages[0].captured[0].input.pageIndex, 2);
 assert.equal(report.outcome.pages[1].status, 'failed');
 assert.equal(report.outcome.pages[1].meta.input.pageIndex, 3);
 assert.equal(report.outcome.evidence.files[0].status, 'incomplete');
 assert.equal(report.outcome.evidence.files[0].errors[0].pageIndex, 3);
 assert.equal(report.outcome.evidence.files[0].original.sha256, input.sha256);
 assert.equal(report.authenticity.isAuthentic, null);
 const json = documentReportJson(outcome);
 for (const value of ['92374.123', 'alignedRGBA', 'blob:', 'synthetic image bytes', 'imageUrl']) assert.equal(json.includes(value), false, value);
});
test('signature field counts remain distinct from signed values and trust is unverified', () => {
 const report = createDocumentReport({ kind: 'file_error', meta, message: 'Synthetic', documentEvidence: evidence });
 const sig = report.outcome.evidence.files[0].pdf.signatures;
 assert.equal(sig.fieldCount, 1); assert.equal(sig.count, 0);
 assert.equal(sig.issuerTrust, 'not_supported'); assert.equal(sig.cryptographicVerification, 'not_supported');
 assert.equal(report.outcome.evidence.files[0].pdf.pages[0].text.trust, 'untrusted_native_text_not_ocr');
 assert.deepEqual(report.outcome.evidence.comparisons[0].result.numericDisagreements, { nativeOnly: ['100'], ocrOnly: ['900'] });
 assert.equal(report.outcome.evidence.comparisons[0].result.isTampered, null);
});
test('face-document and liveness results cannot leak nested templates, pixels, or image URLs', () => {
 const outcome = { kind: 'face', flow: 'facedoc', meta, liveness: { passed: true, result: secret, ...secret }, document: { kind: 'unknown', copy_assessment: copy, face: { found: true, ...secret }, ...secret }, photos: [{ label: 'Synthetic', face: secret, ...secret }], match: { matched: true, against: 'document', similarity: .7, threshold: .5, ...secret } };
 const report = createDocumentReport(outcome);
 assert.deepEqual(report.outcome.liveness, { passed: true });
 assert.deepEqual(Object.keys(report.outcome.document), ['kind', 'copy_assessment']);
 assert.equal(report.outcome.document.copy_assessment.is_copy, null);
 const json = documentReportJson(outcome);
 for (const value of ['92374.123', 'alignedRGBA', 'blob:', '"face" :', 'photos', 'imageUrl']) assert.equal(json.includes(value), false, value);
});
test('unknown nested extensions are excluded, even inside selected metadata or checks', () => {
 const injected = { ...evidence, files: [{ ...file, metadata: { ...file.metadata, fields: { ...file.metadata.fields, face: secret } }, face: secret }], face: secret };
 const report = documentReportJson({ kind: 'file_error', meta: { ...meta, face: secret }, message: 'Could not render blob:https://local.invalid/image', documentEvidence: injected });
 assert.equal(report.includes('92374.123'), false);
 assert.equal(report.includes('blob:'), false);
 assert.match(report, /blob URL omitted/);
 assert.equal(JSON.parse(report).outcome.evidence.files[0].metadata.fields.Creator, 'Synthetic generator');
});
test('text and barcode reports preserve useful readings without raw results', () => {
 const text = createDocumentReport({ kind: 'text', meta, result: { text: 'Synthetic text', lines: [{ text: 'Synthetic text', x: 1, y: 2, w: 3, h: 4, ...secret }], ...secret }, ...secret });
 assert.equal(text.outcome.text, 'Synthetic text'); assert.equal(text.outcome.engine, 'ocrs');
 const barcodes = createDocumentReport({ kind: 'barcodes', meta, labels: true, finishedBy: 'operator', barcodes: [{ format: 'Code39', text: 'SYNTHETIC', count: 1, ...secret }], fields: [{ name: 'Label', value: 'SYNTHETIC', source: 'text', ...secret }], ...secret });
 assert.equal(barcodes.outcome.barcodes[0].text, 'SYNTHETIC');
 assert.equal(barcodes.outcome.fields[0].source, 'text');
 assert.equal(JSON.stringify([text, barcodes]).includes('92374.123'), false);
});
test('address report includes fields and checks but not its required captured Blob', () => {
 const report = createDocumentReport({ kind: 'address', meta, captured: { ...secret, result: { method: 'rules', text: 'Synthetic address', fields: { holder_name: 'Synthetic', address: { street: 'Synthetic street', city: null }, statement_period: { from: '2020-01-01', to: '2020-01-31' } }, verification: { accepted: false, postal_code: 'unknown', reasons: ['synthetic'], fields: [{ field: 'holder_name', value: 'Synthetic', found: true, confidence: .8, match_score: 1 }], age: null }, ...secret } } });
 assert.equal(report.outcome.fields.address.street, 'Synthetic street');
 assert.equal(report.outcome.verification.accepted, false);
 assert.equal(JSON.stringify(report).includes('92374.123'), false);
});

 test('identity report preserves the front/back mismatch verdict', () => {
 const front = { ...document, kind: 'za_smart_id_front', printed: { id_number: { value: 'invented-front' } } };
 const back = { ...document, kind: 'za_smart_id_back', id_barcode: { value: 'invented-back' } };
 const result = createDocumentReport({ kind: 'id', scanner: 'smart_id', meta, captured: [{ result: front }, { result: back }] });
 assert.deepEqual(result.outcome.crossCheck, { front: 'invented-front', back: 'invented-back', match: false });
});

test('incomplete inspection warnings are not exported as failed page readings', () => {
 const result = createDocumentReport({ kind: 'file_error', message: 'Metadata unavailable', severity: 'warning', meta });
 assert.equal(result.outcome.status, 'incomplete'); assert.equal(result.outcome.severity, 'warning');
});

test('experimental exposure export retains original text and keeps alternatives separate', () => {
 const result = createDocumentReport({ kind: 'text', meta, imageUrl: secret.imageUrl,
   result: { engine: 'ppocr_v6_tiny', text: 'original 123', lines: [], exposure: {
     version: 'frozen-global-exposure-v1', status: 'compared', applied: true, gain: 4, backgroundP90: .1,
     alternative: { text: 'alternative 128', lines: [], ...secret }, error: null,
   } } });
 assert.equal(result.outcome.text, 'original 123');
 assert.equal(result.outcome.exposure.alternative.text, 'alternative 128');
 assert.equal(result.outcome.exposure.selection, 'original_retained_no_automatic_selection');
 assert.match(result.outcome.exposure.interpretation, /can introduce incorrect characters/);
 assert.equal('template' in result.outcome.exposure.alternative, false);
 assert.equal('imageUrl' in result.outcome.exposure.alternative, false);
});
