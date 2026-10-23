// General OCR browser regressions; synthetic photos from eval/text_eval.py
// and the existing synthetic proof-of-address video. No personal documents.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { chromium } from "playwright-core";

const server = spawn("node", ["node_modules/vite/bin/vite.js", "preview", "--port", "4186", "--strictPort"], { cwd: new URL("../", import.meta.url), stdio: "pipe" });
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
page.on("pageerror", (e) => errors.push(e.message));
await page.addInitScript(() => {
  window.__textEvents = [];
  window.__tracks = [];
  const get = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (...args) => {
    const stream = await get(...args);
    window.__tracks.push(...stream.getTracks());
    return stream;
  };
  for (const type of ["docscan:text", "docscan:complete"]) window.addEventListener(type, (e) => window.__textEvents.push({ type, detail: e.detail }));
});
try {
  await page.goto("http://localhost:4186/?threads=1");
  await page.evaluate(async () => {
    const cache = await caches.open("docscan-models-v1");
    await cache.put("/models/poa-tagger.onnx", new Response("obsolete model"));
  });
  await page.reload();
  await page.waitForFunction(() => window.__docscan?.ready, null, { timeout: 60000 });
  await page.locator('[data-photo="text"]').setInputFiles("/tmp/docscan-text-dev/family0-size14-clean.png");
  await page.locator('[data-testid="results"][data-kind="text"]').waitFor({ timeout: 120000 });
  const text = await page.getByLabel("Extracted text", { exact: true }).inputValue();
  assert.match(text, /DOCUMENT CAPTURE DEVELOPMENT SAMPLE/);
  assert.match(text, /twelve pencils/);
  assert.equal(await page.evaluate(() => window.__textEvents.length), 0, "photo reading must not announce a live capture");
  mkdirSync(new URL("./out/", import.meta.url), { recursive: true });
  await page.screenshot({ path: new URL("./out/text-photo.png", import.meta.url).pathname, fullPage: true });
  console.log("PASS photo OCR and versioned model cache");

  await page.goto("http://localhost:4186/?mode=text&threads=1");
  await page.locator('[data-testid="results"][data-kind="text"]').waitFor({ timeout: 180000 });
  const result = await page.evaluate(() => ({ events: window.__textEvents, tracks: window.__tracks.map((t) => t.readyState) }));
  assert.deepEqual(result.events.map((e) => e.type), ["docscan:text", "docscan:complete"]);
  assert.ok(result.events[0].detail.result.words.length > 10);
  assert.ok(result.tracks.length > 0 && result.tracks.every((s) => s === "ended"));
  await page.screenshot({ path: new URL("./out/text-camera.png", import.meta.url).pathname, fullPage: true });
  console.log("PASS hands-free text capture, one completion, camera released");

  // Leave while OCR runs. A subsequent photo request queues behind it,
  // proving the abandoned request has drained before checking its events.
  await page.goto("http://localhost:4186/?mode=text&threads=1");
  await page.waitForFunction(() => document.querySelector('[data-testid="hint"]')?.textContent?.includes("Reading the page"), null, { timeout: 120000 });
  await page.locator('[data-testid="capture-home"]').click();
  await page.locator('[data-testid="home"]').waitFor();
  await page.waitForFunction(() => window.__docscan?.ready, null, { timeout: 60000 });
  await page.locator('[data-photo="text"]').setInputFiles("/tmp/docscan-text-dev/family1-size28-clean.png");
  await page.locator('[data-testid="results"][data-kind="text"]').waitFor({ timeout: 180000 });
  assert.match(await page.getByLabel("Extracted text", { exact: true }).inputValue(), /SAMPLE INVOICE/);
  assert.equal(await page.evaluate(() => window.__textEvents.length), 0, "abandoned capture must not publish results");
  console.log("PASS leaving during OCR cancels capture completion");
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
  server.kill();
}
