// Screenshots of the demo's three screens at a phone viewport (390×844) and
// at desktop width, for a passport and the barcode scanner, into e2e/out/.
// Usage: node e2e/screens.mjs (after `npx vite build`).
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { chromium } from "playwright-core";

const VIDEO = new URL("../../testdata/video/", import.meta.url).pathname;
const OUT = new URL("./out/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

const server = spawn("node", ["node_modules/vite/bin/vite.js", "preview", "--port", "4173", "--strictPort"], {
  stdio: "pipe",
  detached: true,
  cwd: new URL("../", import.meta.url).pathname,
});
process.on("exit", () => {
  try {
    process.kill(-server.pid);
  } catch {}
});
await new Promise((resolve) => server.stdout.on("data", (d) => String(d).includes("4173") && resolve()));

const VIEWPORTS = { phone: { width: 390, height: 844 }, desktop: { width: 1280, height: 860 } };
const DEVICE = { phone: { isMobile: true, hasTouch: true, deviceScaleFactor: 2 }, desktop: {} };
// The capture screen is shot `captureAt` ms after the camera opens.
const FLOWS = [
  { name: "passport", video: "gb_passport.y4m", card: "passport", captureAt: 4000 },
  { name: "barcodes", video: "hd/multi-barcode.y4m", card: "barcodes", captureAt: 3900 },
];

const shots = [];
for (const [vp, viewport] of Object.entries(VIEWPORTS)) {
  for (const flow of FLOWS) {
    const browser = await chromium.launch({
      executablePath: "/usr/bin/google-chrome",
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-video-capture=${VIDEO}${flow.video}`],
    });
    const page = await browser.newPage({ viewport, ...DEVICE[vp] });
    await page.goto("http://localhost:4173/");
    await page.waitForFunction(() => window.__docscan?.captureReady, null, { timeout: 30000 });
    if (flow === FLOWS[0]) {
      const path = `${OUT}screen-${vp}-home.png`;
      await page.screenshot({ path, fullPage: vp === "desktop" });
      shots.push(path);
    }
    await page.locator(`[data-scanner=${flow.card}]`).click();
    await page.waitForTimeout(flow.captureAt);
    if (await page.locator("[data-testid=capture]").count()) {
      const path = `${OUT}screen-${vp}-${flow.name}-capture.png`;
      await page.screenshot({ path });
      shots.push(path);
    }
    // The fake camera plays the landscape clip as it is, where a phone held
    // upright films in portrait: on a phone viewport the passport is cropped
    // out of view. So it is captured at desktop size, and the results are
    // shot back at phone size. (Barcodes read the whole frame either way.)
    const widen = vp === "phone" && flow.card === "passport";
    if (widen) await page.setViewportSize(VIEWPORTS.desktop);
    await page.locator("[data-testid=results]").waitFor({ timeout: 60000 });
    if (widen) await page.setViewportSize(viewport);
    // Open the Metadata so the screenshot shows it.
    for (const d of await page.locator("details.metadata").all()) await d.evaluate((el) => (el.open = true));
    await page.waitForTimeout(300);
    const path = `${OUT}screen-${vp}-${flow.name}-results.png`;
    await page.screenshot({ path, fullPage: true });
    shots.push(path);
    await browser.close();
  }
}
console.log(shots.join("\n"));
process.exit(0);
