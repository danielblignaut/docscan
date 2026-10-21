// The wasm scanner in headless Chrome: per-call times on a small fixed subset,
// for the single-threaded build (docscan/pkg, what GitHub Pages serves) and,
// when built, the multithreaded one (docscan/pkg-threads, rayon over Web
// Workers, which needs a cross-origin-isolated page).
//
//   node bench/wasm/bench.mjs --inputs inputs.json --out result.json [--quick]
//
// inputs.json (written by bench/bench.py): {"barcodes": [paths], "document": [paths],
// "page": [paths], "face": [paths], "repeats": N}. The scanner runs in a module
// Worker, as the demo runs it (worker.mjs: rayon's pool blocks with
// Atomics.wait, which a page's main thread may not do). Each image is decoded
// once (scaled to at most 1280 px wide, as the demo analyses camera frames),
// then each call is timed `repeats` times after one warm-up; the per-image
// median is reported. --quick measures the single-threaded build only.
import { createServer } from "node:http";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { cpus } from "node:os";
import { extname, join, normalize } from "node:path";

const REPO = new URL("../../", import.meta.url).pathname;
const DATA = process.env.BENCH_DATA ?? "/tmp/docscan-bench";
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const OUT = opt("--out", `${DATA}/wasm-result.json`);
const INPUTS = JSON.parse(readFileSync(opt("--inputs", `${DATA}/wasm-inputs.json`)));
const TIMEOUT_MS = Number(opt("--timeout", 600000));
const require = createRequire(join(REPO, "demo", "package.json"));
// A private snapshot of what is served (the wasm builds, the models, the
// worker), so a concurrent rebuild in this worktree (wasm-pack empties pkg/
// first) cannot pull a file from under the measurement; and the server
// listens on a port the OS picks, so concurrent runs never clash.
mkdirSync(join(DATA, "tmp"), { recursive: true });
const ROOT = mkdtempSync(join(DATA, "tmp", "wasm-serve-")) + "/";
for (const rel of ["docscan/pkg", "docscan/pkg-threads", "models", "bench/wasm/worker.mjs"]) {
  if (existsSync(join(REPO, rel))) cpSync(join(REPO, rel), join(ROOT, rel), { recursive: true, dereference: true });
}
const cleanup = () => rmSync(ROOT, { recursive: true, force: true });
process.on("exit", cleanup);
const { chromium } = require("playwright-core");

const MIME = { ".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm", ".html": "text/html", ".json": "application/json",
  ".png": "image/png", ".jpg": "image/jpeg", ".rten": "application/octet-stream", ".onnx": "application/octet-stream" };
const ISOLATED = { "cross-origin-opener-policy": "same-origin", "cross-origin-embedder-policy": "require-corp", "cross-origin-resource-policy": "same-origin" };
// /repo/... serves the repository, /data/... the benchmark data; every response cross-origin isolated.
const server = createServer((req, res) => {
  const url = decodeURIComponent(req.url.split("?")[0]);
  if (url === "/") {
    res.writeHead(200, { "content-type": "text/html", ...ISOLATED });
    return res.end("<!doctype html><title>docscan bench</title>");
  }
  let file = null;
  if (url.startsWith("/repo/")) file = normalize(join(ROOT, url.slice(6)));
  if (url.startsWith("/data/")) file = normalize(join(DATA, url.slice(6)));
  // A package directory (wasm-bindgen-rayon's workers `import('../../..')`, which a
  // bundler resolves): serve its package.json's main.
  if (file && existsSync(file) && statSync(file).isDirectory() && existsSync(join(file, "package.json"))) {
    file = join(file, JSON.parse(readFileSync(join(file, "package.json"))).main ?? "index.js");
  }
  if (!file || !(file.startsWith(ROOT) || file.startsWith(DATA)) || !existsSync(file) || !statSync(file).isFile()) {
    res.writeHead(404);
    return res.end();
  }
  res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream", ...ISOLATED });
  res.end(readFileSync(file));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;
const toUrl = (p) => (p.startsWith(DATA) ? `/data/${p.slice(DATA.length + 1)}` : `/repo/${p.slice(ROOT.length)}`).split("/").map(encodeURIComponent).join("/");

const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", args: ["--enable-features=SharedArrayBuffer"] });
const result = { builds: {}, info: { chrome: browser.version() } };
const hw = Math.min(8, cpus().length);
const builds = [["single", "docscan/pkg", 1]];
if (existsSync(join(ROOT, "docscan/pkg-threads/docscan_bg.wasm")) && !args.includes("--quick")) builds.push([`threads${hw}`, "docscan/pkg-threads", hw]);
const inputs = { ...INPUTS };
for (const k of ["barcodes", "document", "page", "face"]) inputs[k] = (INPUTS[k] ?? []).map(toUrl);

for (const [name, pkg, threads] of builds) {
  const page = await browser.newPage();
  const logs = [];
  page.on("console", (m) => logs.push(m.text()));
  page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
  page.on("response", (r) => r.status() >= 400 && logs.push(`HTTP ${r.status()} ${r.url().replace(base, "")}`));
  await page.goto(`${base}/`);
  result.info[`${name}_cross_origin_isolated`] = await page.evaluate(() => crossOriginIsolated);
  try {
    const run = page.evaluate(({ pkg, threads, inputs }) => new Promise((resolve, reject) => {
      const w = new Worker("/repo/bench/wasm/worker.mjs", { type: "module" });
      w.onmessage = (e) => (e.data.error ? reject(new Error(e.data.error)) : resolve(e.data));
      w.onerror = (e) => reject(new Error(`worker: ${e.message ?? "failed to load"}`));
      w.postMessage({ pkg, threads, inputs });
    }), { pkg, threads, inputs });
    const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error(`timed out after ${TIMEOUT_MS} ms`)), TIMEOUT_MS));
    result.builds[name] = await Promise.race([run, timeout]);
  } catch (e) {
    result.info[`${name}_error`] = `${String(e).split("\n")[0]} ${logs.slice(-4).join(" | ")}`;
    console.error(name, result.info[`${name}_error`]);
  }
  await page.close();
}
await browser.close();
server.close();
writeFileSync(OUT, JSON.stringify(result));
console.error(`wasm: ${Object.keys(result.builds).join(", ") || "nothing"} -> ${OUT}`);
process.exit(0);
