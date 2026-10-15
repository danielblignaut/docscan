// End-to-end: headless Chrome with a fake camera playing a .y4m video, the
// built demo served by `vite preview`, and an assertion on what the page
// captured. Usage: node e2e/run.mjs [case-name ...]
//
// A case's `video` is relative to testdata/video/ (see the README to build
// the clips), or absolute. Expectations:
// - `captured`: `count` captures of `kinds`, with `fields` [index, path, value];
//   `address: true` also wants one `docscan:address` event (?mode=address); a
//   field's optional fourth element "~" lets one character differ (`near`);
//   `crosscheck: true` also wants the front/back identity numbers to agree.
// - `barcodes`: every code in `codes` confirmed; `exact` forbids any other
//   than those and the `optional` ones.
// - `not_captured`: nothing is captured within `waitMs`, the last reading is
//   `lastKind` and the hint contains `hint`.
// - `labels` (?mode=labels): the scan finishes by itself with every field in
//   `fields` ([label or null, value, check_digit_valid]) listed.
// - `abandon`: open the home screen, tap the `scanner` card, wait `waitMs`,
//   then the overlaid Back to home: the menu returns, the camera is released
//   and nothing more is analysed.
//
// Every flow that finishes must reach the results screen, whose Back to home
// returns to the menu; a flow left waiting (`not_captured`, `complete: false`)
// is left through the capture screen's own Back to home, which must release
// the camera. Barcodes and device labels finish on their own (MultiBarcode.tsx,
// QUIET_MS and STABLE_PASSES) and fire `docscan:complete`.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { chromium } from "playwright-core";

const VIDEO = new URL("../../testdata/video/", import.meta.url).pathname;
const OUT = new URL("./out/", import.meta.url).pathname;
const CASES = JSON.parse(readFileSync(new URL("./cases.json", import.meta.url)));
const only = process.argv.slice(2);
// Appended to every case's query, e.g. E2E_QUERY="&threads=1" for the single-threaded build.
const EXTRA = process.env.E2E_QUERY ?? "";
mkdirSync(OUT, { recursive: true });

const chrome = ["/usr/bin/google-chrome"].find(existsSync);
// vite itself, in its own process group, so killing the group leaves nothing behind.
const server = spawn("node", ["node_modules/vite/bin/vite.js", "preview", "--port", "4173", "--strictPort"], {
  stdio: "pipe",
  detached: true,
  cwd: new URL("../", import.meta.url).pathname,
});
const stopServer = () => {
  try {
    process.kill(-server.pid);
  } catch {}
};
await new Promise((resolve, reject) => {
  server.stdout.on("data", (d) => String(d).includes("4173") && resolve());
  server.stderr.on("data", (d) => process.stderr.write(d));
  server.on("exit", (code) => reject(new Error(`vite preview exited with ${code}`)));
});
// Never leave the preview server behind, whatever happens.
process.on("exit", stopServer);
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => process.exit(130));

function levenshtein(a, b) {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) cur.push(Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)));
    prev = cur;
  }
  return prev[b.length];
}

const median = (xs) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return Math.round(s[Math.floor(s.length / 2)]);
};

/** Per-frame timings the page recorded: the fast pass and the OCR pass apart. */
function timings(frames) {
  const fast = frames.filter((f) => !f.ocr).map((f) => f.ms);
  const ocr = frames.filter((f) => f.ocr);
  const passes = {};
  for (const f of ocr) passes[f.passes] = (passes[f.passes] ?? 0) + 1;
  return {
    frames: frames.length,
    fastMs: median(fast),
    fastP90: fast.length ? Math.round([...fast].sort((a, b) => a - b)[Math.floor(fast.length * 0.9)]) : null,
    ocrMs: median(ocr.map((f) => f.ms)),
    ocrFrames: ocr.length,
    ocrPerPassMs: median(ocr.filter((f) => f.passes).map((f) => f.timings.ocr / f.passes)),
    passes,
    size: frames[0]?.size,
  };
}

const results = [];
for (const c of CASES.filter((c) => !only.length || only.includes(c.name))) {
  const video = c.video.startsWith("/") ? c.video : VIDEO + c.video;
  if (!existsSync(video)) {
    results.push({ name: c.name, ok: false, why: `missing ${video}` });
    console.log(JSON.stringify(results.at(-1)));
    continue;
  }
  const browser = await chromium.launch({
    executablePath: chrome,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-video-capture=${video}`,
      "--enable-features=SharedArrayBuffer",
    ],
  });
  const page = await browser.newPage({ viewport: c.viewport ?? { width: 1280, height: 860 } });
  const logs = [];
  page.on("console", (m) => logs.push(m.text()));
  page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
  const t0 = Date.now();
  // Record the page's own window events and every camera track it opens, to
  // check the host-facing contract: events fire, and the camera is released.
  await page.addInitScript(() => {
    window.__host = { captured: 0, complete: 0, address: 0, tracks: [] };
    addEventListener("docscan:captured", () => window.__host.captured++);
    addEventListener("docscan:address", () => window.__host.address++);
    addEventListener("docscan:complete", () => window.__host.complete++);
    const open = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (c) => {
      const stream = await open(c);
      window.__host.tracks.push(...stream.getTracks());
      return stream;
    };
  });
  await page.goto(`http://localhost:4173/${c.query}${EXTRA}`);
  const want = c.expect;
  let outcome;
  try {
    await page.waitForFunction(() => window.__docscan?.ready, null, { timeout: 30000 });
    const ready = Date.now() - t0;
    var threads = await page.evaluate(() => window.__docscan.ready.threads);
    if (want.type === "not_captured") {
      await page.waitForTimeout(want.waitMs);
    } else if (want.type === "abandon") {
      await page.locator(`[data-scanner=${want.scanner}]`).click();
      await page.locator("[data-testid=capture]").waitFor({ timeout: 5000 });
      await page.waitForFunction(() => window.__host.tracks.some((t) => t.readyState === "live"), null, { timeout: 10000 });
      await page.waitForTimeout(want.waitMs);
    } else if (want.type === "labels") {
      await page.locator("[data-testid=results]").waitFor({ timeout: c.timeout ?? 90000 });
    } else {
      await page.waitForFunction(
        ({ want }) => {
          const ev = window.__docscan.events;
          if (want.type === "captured") return ev.filter((e) => e.type === "captured").length >= want.count;
          const seen = new Set(ev.filter((e) => e.type === "barcodes").flatMap((e) => e.barcodes.map((b) => `${b.format}|${b.text}`)));
          return want.codes.every((k) => seen.has(k));
        },
        { want },
        { timeout: c.timeout ?? 45000, polling: 250 },
      );
    }
    // Barcodes now finish by themselves: wait for the set to be handed on.
    if (want.type === "barcodes") await page.locator("[data-testid=results]").waitFor({ timeout: 60000 });
    const doneMs = Date.now() - t0;
    // The page renders the result screen after the last capture.
    if (want.type === "captured") await page.waitForTimeout(500);
    const { events, frames } = await page.evaluate(() => window.__docscan);
    const captured = events.filter((e) => e.type === "captured");
    const problems = [];
    const near = [];
    const host = () =>
      page.evaluate(() => ({
        captured: window.__host.captured,
        complete: window.__host.complete,
        address: window.__host.address,
        live: window.__host.tracks.filter((t) => t.readyState !== "ended").length,
      }));
    const finish = events.find((e) => e.type === "complete");
    const finishes = want.type === "barcodes" || want.type === "labels" || (want.type === "captured" && want.complete !== false);
    if (want.type === "captured") {
      for (const [i, path, value, tolerance] of want.fields ?? []) {
        const got = path.split(".").reduce((o, k) => o?.[k], captured[i]?.result);
        const [a, b] = [String(got).toUpperCase(), String(value).toUpperCase()];
        if (a === b) continue;
        // "~": one character's OCR slip is allowed (small print read from a
        // 1080-pixel-wide video frame), and reported as `near`.
        if (tolerance === "~" && levenshtein(a, b) <= 1) near.push(`${i}.${path}: want ${value}, got ${got}`);
        else problems.push(`${i}.${path}: want ${value}, got ${got}`);
      }
      const h = await host();
      if (h.captured !== want.count) problems.push(`docscan:captured fired ${h.captured}×, want ${want.count}`);
      if (want.address && h.address !== 1) problems.push(`docscan:address fired ${h.address}×`);
      if (want.complete === false) {
        // A flow left waiting on a later step: no completion, camera still on.
        if (h.complete !== 0) problems.push(`docscan:complete fired ${h.complete}× mid-flow`);
        if (!h.live) problems.push("camera stopped mid-flow");
      } else {
        if (h.complete !== 1) problems.push(`docscan:complete fired ${h.complete}×`);
        if (h.live) problems.push(`${h.live} camera track(s) still live after completion`);
      }
      const kinds = captured.map((e) => e.kind);
      if (want.kinds && JSON.stringify(kinds) !== JSON.stringify(want.kinds)) problems.push(`kinds ${kinds}`);
      if (want.crosscheck) {
        const check = events.find((e) => e.type === "crosscheck");
        if (!check?.match) problems.push(`crosscheck ${JSON.stringify(check)}`);
        const shown = await page.locator("[data-testid=crosscheck]").textContent().catch(() => null);
        if (!shown?.includes("agree")) problems.push(`crosscheck not shown: ${shown}`);
      }
    } else if (want.type === "barcodes") {
      const seen = new Set(events.filter((e) => e.type === "barcodes").flatMap((e) => e.barcodes.map((b) => `${b.format}|${b.text}`)));
      const extra = [...seen].filter((k) => !want.codes.includes(k) && !(want.optional ?? []).includes(k));
      if (want.exact && extra.length) problems.push(`unexpected codes confirmed: ${extra.join(", ")}`);
      const h = await host();
      if (h.complete !== 1) problems.push(`docscan:complete fired ${h.complete}×`);
      if (h.live) problems.push(`${h.live} camera track(s) still live after finishing`);
      // The results form lists every confirmed code.
      for (const k of want.codes) {
        const shown = await page.locator(`[data-testid=barcodes] [data-field="${k.replaceAll('"', '\\"')}"] input`).inputValue().catch(() => null);
        if (shown !== k.slice(k.indexOf("|") + 1)) problems.push(`results do not show ${k}`);
      }
    } else if (want.type === "labels") {
      const fields = finish?.fields ?? [];
      for (const [label, value, check] of want.fields) {
        if (!fields.some((f) => f.label === label && f.value === value && f.check_digit_valid === check)) problems.push(`field ${label}=${value} (check ${check}) not listed: ${JSON.stringify(fields.map((f) => [f.label, f.value, f.check_digit_valid]))}`);
      }
      const h = await host();
      if (h.complete !== 1) problems.push(`docscan:complete fired ${h.complete}×`);
      if (h.live) problems.push(`${h.live} camera track(s) still live after finishing`);
    } else if (want.type === "abandon") {
      const before = await page.evaluate(() => window.__docscan.frames.length);
      await page.locator("[data-testid=capture-home]").click();
      if (!(await page.locator("[data-testid=home]").waitFor({ timeout: 5000 }).then(() => true, () => false))) problems.push("Back to home did not return to the menu");
      // Let any frame in flight land, then nothing more may be analysed.
      await page.waitForTimeout(2500);
      const after = await page.evaluate(() => window.__docscan.frames.length);
      if (!before) problems.push("nothing was analysed before Back");
      if (after - before > 1) problems.push(`${after - before} frames analysed after Back`);
      const h = await host();
      if (h.live) problems.push(`${h.live} camera track(s) still live after Back`);
      if (captured.length) problems.push(`captured ${captured.map((e) => e.kind)}`);
      if (new URL(page.url()).search.match(/[?&](doc|mode)=/)) problems.push(`URL still names a scanner: ${page.url()}`);
    } else {
      if (captured.length) problems.push(`captured ${captured.map((e) => e.kind)}`);
      const kinds = new Set(frames.map((f) => f.kind));
      if (want.lastKind && !kinds.has(want.lastKind)) problems.push(`never read as ${want.lastKind}: ${[...kinds]}`);
      // The clip loops through an empty frame, so wait for the hint to come round.
      const hinted = await page
        .waitForFunction((h) => document.querySelector("[data-testid=hint]")?.textContent?.includes(h), want.hint, { timeout: 15000, polling: 100 })
        .then(() => true, () => false);
      if (want.hint && !hinted) problems.push(`hint never said "${want.hint}"`);
    }
    // Outline colour transitions (src/outline.ts): grey while looking, green
    // once capture starts, done when the flow moves on; each step of a
    // multi-step flow starts grey again.
    const outline = events.filter((e) => e.type === "outline").map((e) => e.state);
    if (outline[0] !== "grey") problems.push(`outline starts ${outline[0]}`);
    if (finishes) {
      if (outline.at(-1) !== "done" || outline.at(-2) !== "green") problems.push(`outline ends ${outline.slice(-3).join(" → ")}, want green → done`);
      if (outline.filter((s) => s === "done").length !== 1) problems.push(`outline done ${outline.filter((s) => s === "done").length}×`);
      if (want.type === "captured" && want.count > 1) {
        // grey → green for each step, then done.
        const greens = outline.filter((s, i) => s === "green" && outline[i - 1] === "grey").length;
        if (greens < want.count) problems.push(`outline went green ${greens}× for ${want.count} steps (${outline.join(" → ")})`);
      }
    } else if (outline.includes("done")) problems.push("outline done without finishing");
    if (finishes) {
      // The results screen, then its Back to home.
      const results = page.locator("[data-testid=results]");
      if (!(await results.waitFor({ timeout: 10000 }).then(() => true, () => false))) problems.push("never reached the results screen");
      else {
        if (!(await page.locator("[data-testid=results] img.captured").count())) problems.push("results show no captured image");
        if (!(await page.locator("[data-testid=results] [data-testid=metadata]").count())) problems.push("results have no Metadata section");
        await page.screenshot({ path: `${OUT}${c.name}.png`, fullPage: true });
        await page.locator("[data-testid=results-home]").click();
        if (!(await page.locator("[data-testid=home]").waitFor({ timeout: 5000 }).then(() => true, () => false))) problems.push("results Back to home did not return to the menu");
      }
    } else if (want.type !== "abandon") {
      // A flow still waiting: its capture screen's Back to home must release the camera.
      await page.screenshot({ path: `${OUT}${c.name}.png`, fullPage: true });
      await page.locator("[data-testid=capture-home]").click();
      if (!(await page.locator("[data-testid=home]").waitFor({ timeout: 5000 }).then(() => true, () => false))) problems.push("capture Back to home did not return to the menu");
      await page.waitForTimeout(300);
      const h = await host();
      if (h.live) problems.push(`${h.live} camera track(s) still live after Back to home`);
    }
    outcome = {
      ok: problems.length === 0,
      threads,
      readyMs: ready,
      doneMs,
      captures: captured.map((e) => ({ kind: e.kind, stepMs: e.stepMs, sinceStartMs: e.sinceStartMs, fallback: e.fallback, readMs: e.readMs, method: e.result?.method, wasmMemoryMb: e.wasmMemoryMb, ocrMs: e.result?.timings_ms?.ocr })),
      problems,
      ...(near.length ? { near } : {}),
      ...(finish ? { finishedBy: finish.finishedBy, finishMs: finish.sinceStartMs } : {}),
      outline: outline.join(" → "),
      timings: timings(frames),
    };
  } catch (e) {
    const ds = await page.evaluate(() => window.__docscan ?? { events: [], frames: [] }).catch(() => ({ events: [], frames: [] }));
    const hint = await page.locator("[data-testid=hint]").textContent().catch(() => null);
    const stats = await page.locator(".stats").textContent().catch(() => null);
    outcome = {
      ok: false,
      why: String(e).split("\n")[0],
      hint,
      stats,
      captures: ds.events.filter((e) => e.type === "captured").map((e) => e.kind),
      kinds: [...new Set(ds.frames.map((f) => f.kind))],
      timings: timings(ds.frames),
      logs: logs.slice(-5),
      seen: [...new Set(ds.events.filter((e) => e.type === "barcodes").flatMap((e) => e.barcodes.map((b) => `${b.format}|${b.text}`)))],
    };
    writeFileSync(`${OUT}${c.name}.frames.json`, JSON.stringify(ds.frames));
  }
  writeFileSync(`${OUT}${c.name}.frames.json`, JSON.stringify(await page.evaluate(() => window.__docscan?.frames ?? []).catch(() => [])));
  if (!outcome.ok || want.type === "abandon") await page.screenshot({ path: `${OUT}${c.name}.png`, fullPage: true });
  await browser.close();
  results.push({ name: c.name, ...outcome });
  console.log(JSON.stringify(results.at(-1)));
}
stopServer();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
writeFileSync(`${OUT}results${process.env.E2E_TAG ?? ""}.json`, JSON.stringify(results, null, 2));
process.exit(failed.length ? 1 : 0);
