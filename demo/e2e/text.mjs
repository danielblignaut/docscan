// General OCR browser regressions; synthetic photos from eval/text_eval.py
// and the existing synthetic proof-of-address video. No personal documents.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { chromium } from "playwright-core";

const server = spawn("node", ["node_modules/vite/bin/vite.js", "preview", "--port", "4186", "--strictPort", ...(process.env.DOCSCAN_TEST_BUILD ? ["--outDir", process.env.DOCSCAN_TEST_BUILD] : [])], { cwd: new URL("../", import.meta.url), stdio: "pipe" });
await new Promise((resolve, reject) => {
  server.stdout.on("data", (d) => String(d).includes("4186") && resolve());
  server.on("exit", (code) => reject(new Error(`preview exited ${code}`)));
});
const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", args: [
  "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
  `--use-file-for-fake-video-capture=${new URL("../../testdata/video/poa/poa_00003.y4m", import.meta.url).pathname}`,
] });
const page = await browser.newPage({ viewport: { width: 540, height: 960 } });
const errors = [];
const threads = process.env.DOCSCAN_TEST_THREADS ?? "1";
const engine = process.env.DOCSCAN_TEXT_ENGINE ?? "ocrs";
const paddleRequests = [];
page.on("request", (r) => { if (r.url().includes("/models/ppocr-v6-")) paddleRequests.push(r.url()); });
page.on("pageerror", (e) => errors.push(e.message));
await page.addInitScript(() => {
  window.__textEvents = [];
  window.__tracks = [];
  window.__textReadResponses = 0;
  const NativeWorker = window.Worker;
  window.Worker = class extends NativeWorker {
    constructor(...args) {
      super(...args);
      this.addEventListener("message", (event) => {
        if (event.data.kind === "result" && ["text_page", "text_v6"].includes(event.data.request)) window.__textReadResponses++;
      });
    }
  };
  const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (...args) => {
    const stream = await get(...args);
    window.__tracks.push(...stream.getTracks());
    return stream;
  };
  for (const type of ["docscan:text", "docscan:complete"]) window.addEventListener(type, (e) => window.__textEvents.push({ type, detail: e.detail }));
});
try {
  await page.goto(`http://localhost:4186/?threads=${threads}&textEngine=${engine}`);
  await page.evaluate(async () => {
    const cache = await caches.open("docscan-models-v1");
    await cache.put("/models/poa-tagger.onnx", new Response("obsolete model"));
  });
  await page.reload();
  await page.waitForFunction(() => window.__docscan?.ready, null, { timeout: 60000 });
  assert.equal(await page.evaluate(() => window.__docscan.ready.tagger), true, "a stale unversioned model must not disable the current tagger");
  assert.ok(await page.evaluate(async () => (await (await caches.open("docscan-models-v1")).keys()).some((r) => /poa-tagger\.onnx\?v=/.test(r.url))));
  assert.equal(paddleRequests.length, 0, "optional models must not load before use");
  await page.locator('[data-photo="text"]').setInputFiles("/tmp/docscan-text-dev/family0-size14-clean.png");
  await page.locator('[data-testid="results"][data-kind="text"]').waitFor({ timeout: 120000 });
  const text = await page.getByLabel("Extracted text", { exact: true }).inputValue();
  assert.match(text, /DOCUMENT CAPTURE DEVELOPMENT SAMPLE/);
  assert.match(text, /twelve pencils/);
  assert.equal(paddleRequests.length, engine !== "ocrs" ? 3 : 0);
  assert.equal(await page.evaluate(() => window.__textEvents.length), 0, "photo reading must not announce a live capture");
  mkdirSync(new URL("./out/", import.meta.url), { recursive: true });
  await page.screenshot({ path: new URL(`./out/text-${engine}-${threads}-photo.png`, import.meta.url).pathname, fullPage: true });
  console.log(`PASS ${engine} photo OCR, lazy models and versioned cache`);

  await page.goto(`http://localhost:4186/?mode=text&threads=${threads}&textEngine=${engine}`);
  await page.locator('[data-testid="results"][data-kind="text"]').waitFor({ timeout: 180000 });
  const result = await page.evaluate(() => ({ events: window.__textEvents, tracks: window.__tracks.map((t) => t.readyState) }));
  assert.deepEqual(result.events.map((e) => e.type), ["docscan:text", "docscan:complete"]);
  const reading = result.events[0].detail.result;
  assert.ok(reading.lines.length > 3);
  if (engine !== "ocrs") {
    assert.equal(reading.engine, "ppocr_v6_tiny"); assert.ok(!("words" in reading));
    assert.equal(reading.passes, engine === "ppocr_v6_tiny_detail" ? 2 : 1);
    assert.ok([960, 1600].includes(reading.detection_max_side));
  }
  else assert.ok(reading.words.length > 10);
  assert.ok(result.tracks.length > 0 && result.tracks.every((s) => s === "ended"));
  await page.screenshot({ path: new URL(`./out/text-${engine}-${threads}-camera.png`, import.meta.url).pathname, fullPage: true });
  console.log("PASS hands-free text capture, one completion, camera released", JSON.stringify({ engine, threads, timings: reading.timings_ms, wasmMemoryBytes: result.events[1].detail.meta.memoryBytes }));

  // Leave while OCR runs. Cancellation stops the worker; a subsequent photo
  // reloads it and must not receive any abandoned capture events.
  await page.goto(`http://localhost:4186/?mode=text&threads=${threads}&textEngine=${engine}`);
  await page.waitForFunction(() => document.querySelector('[data-testid="processing"] [role="status"]')?.textContent?.includes("Reading the page"), null, { timeout: 120000 });
  await page.locator('[data-testid="capture-home"]').click();
  await page.locator('[data-testid="home"]').waitFor();
  await page.waitForFunction(() => window.__docscan?.ready, null, { timeout: 60000 });
  await page.locator('[data-photo="text"]').setInputFiles("/tmp/docscan-text-dev/family1-size28-clean.png");
  await page.locator('[data-testid="results"][data-kind="text"]').waitFor({ timeout: 180000 });
  assert.match(await page.getByLabel("Extracted text", { exact: true }).inputValue(), /SAMPLE INVOICE/);
  assert.equal(await page.evaluate(() => window.__textEvents.length), 0, "abandoned capture must not publish results");
  console.log("PASS leaving during OCR cancels capture completion");
  // Upload reads also must not take over a different scanner opened while
  // the worker is busy. New camera frames prove the old request has drained.
  await page.goto(`http://localhost:4186/?threads=${threads}&textEngine=${engine}`);
  await page.waitForFunction(() => window.__docscan?.ready, null, { timeout: 60000 });
  await page.locator('[data-photo="text"]').setInputFiles("/tmp/docscan-text-dev/family0-size14-clean.png");
  await page.locator('[data-testid="processing-cancel"]').click();
  await page.locator('[data-testid="home"]').waitFor();
  await page.locator('[data-scanner="barcodes"]').click();
  await page.locator('[data-testid="capture"][data-scanner="barcodes"]').waitFor();
  await page.waitForFunction(() => document.querySelector('[data-testid="results"]') || (window.__docscan.frames.length >= 3), null, { timeout: 120000 });
  assert.equal(await page.locator('[data-testid="capture"][data-scanner="barcodes"]').count(), 1);
  assert.equal(await page.locator('[data-testid="results"]').count(), 0);
  await page.locator('[data-testid="capture-home"]').click();
  await page.locator('[data-testid="home"]').waitFor();
  console.log("PASS leaving a photo read cannot replace a newer camera flow");
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
  server.kill();
}
