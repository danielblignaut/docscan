// "Test with a photo": the same scanner as the camera flow, run once on an
// uploaded image, ending on the same results screen. No window events fire:
// they announce camera captures to a host page.
import { downscale, flattenPage, today } from "./AddressCapture";
import { toJpeg } from "./camera";
import { type Captured, FLOWS } from "./IdCapture";
import { chooseExtractor, type Extractor } from "./models";
import type { Outcome } from "./outcome";
import type { ScannerClient } from "./scanner-client";
import type { ScannerId } from "./scanners";
import type { AddressResult, Barcode, DocumentResult, Labelled, PageAnalysis } from "./types";

async function pixels(file: File, maxWidth = Number.POSITIVE_INFINITY): Promise<ImageData> {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, maxWidth / bmp.width);
  const c = new OffscreenCanvas(Math.round(bmp.width * scale), Math.round(bmp.height * scale));
  const ctx = c.getContext("2d")!;
  ctx.drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close();
  return ctx.getImageData(0, 0, c.width, c.height);
}

/**
 * `files`: one photo per step, in order (a smart ID's front, then its back);
 * extra photos are read as the last step.
 */
export async function analysePhotos(client: ScannerClient, scanner: ScannerId, files: File[], method: Extractor | "auto"): Promise<Outcome> {
  const t0 = performance.now();
  const meta = (frames: number, ocrFrames = 0) => ({ source: "photo" as const, captureMs: performance.now() - t0, frames, ocrFrames });

  if (scanner === "barcodes" || scanner === "labels") {
    const file = files[0];
    // The same analysis width as the camera flow.
    const image = await pixels(file, 1920);
    const imageUrl = URL.createObjectURL(file);
    if (scanner === "barcodes") {
      const { result } = await client.run<Barcode[]>({ kind: "barcodes", image, formats: [] });
      const barcodes = result.map((b) => ({ format: b.format, text: b.text, count: 1 }));
      return { kind: "barcodes", labels: false, barcodes, fields: [], imageUrl, finishedBy: "one photo", meta: meta(1) };
    }
    const { result } = await client.run<Labelled>({ kind: "labelled", image });
    const fields = result.fields.filter((f) => f.check_digit_valid !== false);
    const barcodes = fields.filter((f) => f.barcode_format).map((f) => ({ format: f.barcode_format!, text: f.value, count: 1 }));
    return { kind: "barcodes", labels: true, barcodes, fields, imageUrl, finishedBy: "one photo", meta: meta(1, 1) };
  }

  if (scanner === "address") {
    const file = files[0];
    const full = await pixels(file);
    const fullWidth = full.width;
    // The page is found at about the camera flow's analysis size. Every
    // request hands its pixels to the worker, so each one gets its own copy.
    const small = downscale(full, 1280);
    const k = fullWidth / small.width;
    const { result: page } = await client.run<PageAnalysis>({ kind: "page", image: small });
    // A page outline when one is found; otherwise the photo is read as it is (a scan, a screenshot).
    let image: ImageData;
    let imageUrl: string;
    let blob: Blob;
    if (page.outline && page.size) {
      ({ flat: image, imageUrl, blob } = await flattenPage(client, await pixels(file), k, page));
    } else {
      image = await pixels(file);
      blob = await toJpeg(downscale(image, 1024));
      imageUrl = URL.createObjectURL(blob);
    }
    const tRead = performance.now();
    const extractor = chooseExtractor((await client.ready).tagger, method);
    const { result } = await client.run<AddressResult>({ kind: "address", image, today: today(), method: extractor });
    return {
      kind: "address",
      captured: { result, imageUrl, blob, captureMs: 0, readMs: performance.now() - tRead, asked: method },
      meta: meta(2, 1),
    };
  }

  const steps = FLOWS[scanner];
  const captured: Captured[] = [];
  for (const [i, file] of files.entries()) {
    const step = steps[Math.min(i, steps.length - 1)];
    const tStep = performance.now();
    const image = await pixels(file, 1280);
    const w = image.width;
    const { result } = await client.run<DocumentResult>({ kind: "document", image, runOcr: true, expected: step.expect });
    let imageUrl = URL.createObjectURL(file);
    if (result.document) {
      // Flattened as the camera flow flattens: from the photo at full resolution.
      const full = await pixels(file);
      const k = full.width / w;
      const corners = result.document.corners.flatMap(([x, y]) => [x * k, y * k]);
      const [aw, ah] = result.analysed_size;
      const outW = Math.min(2000, Math.round(aw * k));
      const outH = Math.round((outW * ah) / aw);
      const flat = await client.run<ImageData>({ kind: "flatten", image: full, corners, width: outW, height: outH });
      imageUrl = URL.createObjectURL(await toJpeg(flat.result));
    }
    captured.push({ step: step.label, result, imageUrl, fallback: false, stepMs: performance.now() - tStep, frames: 1 });
  }
  return { kind: "id", scanner, captured, meta: meta(files.length, files.length) };
}
