// "Test with a photo": the same scanner as the camera flow, run once on an
// uploaded image, ending on the same results screen. No window events fire:
// they announce camera captures to a host page.
import { downscale, flattenPage, today } from "./AddressCapture";
import { toJpeg } from "./camera";
import { type Captured, FLOWS } from "./IdCapture";
import { chooseExtractor, type Extractor } from "./models";
import type { PageText } from "./TextCapture";
import type { Outcome } from "./outcome";
import type { ScannerClient } from "./scanner-client";
import type { ScannerId } from "./scanners";
import type { FaceClient } from "./face-client";
import { documentMatch, matchEnrolments } from "./FaceFlow";
import { listEnrolments } from "./face-store";
import type { PhotoFace } from "./face-types";
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
export async function analysePhotos(client: ScannerClient, scanner: ScannerId, files: File[], method: Extractor | "auto", face: () => FaceClient): Promise<Outcome> {
  const t0 = performance.now();
  const meta = (frames: number, ocrFrames = 0) => ({ source: "photo" as const, captureMs: performance.now() - t0, frames, ocrFrames });

  if (scanner === "liveness" || scanner === "faceid" || scanner === "facedoc") {
    // A still cannot show liveness: these read the face's quality, the passive
    // anti-spoofing score and the template, and compare where there are two.
    const fc = face();
    const ready = await fc.ready;
    const read = async (file: File, label: string) => {
      const imageUrl = URL.createObjectURL(file);
      const { result } = await fc.run<PhotoFace>({ kind: "photo", image: await pixels(file, 1600) });
      return { label, imageUrl, face: result };
    };
    if (scanner === "facedoc") {
      if (files.length < 2) throw new Error("choose two photos: the identity document, then the selfie");
      // The document flattened first when its outline is found, as the camera flow does.
      const docFile = files[0];
      const image = await pixels(docFile, 1280);
      const { result: doc } = await client.run<DocumentResult>({ kind: "document", image, runOcr: false, expected: "" });
      let docPhoto = await read(docFile, "Identity document");
      if (doc.document) {
        const full = await pixels(docFile);
        const k = full.width / image.width;
        const corners = doc.document.corners.flatMap(([x, y]) => [x * k, y * k]);
        const [aw, ah] = doc.analysed_size;
        const outW = Math.min(2000, Math.round(aw * k));
        const outH = Math.round((outW * ah) / aw);
        const flat = await client.run<ImageData>({ kind: "flatten", image: full, corners, width: outW, height: outH });
        const flatUrl = URL.createObjectURL(await toJpeg(flat.result));
        const { result } = await fc.run<PhotoFace>({ kind: "photo", image: flat.result });
        if (result.found) docPhoto = { label: "Identity document (flattened)", imageUrl: flatUrl, face: result };
      }
      const selfie = await read(files[1], "Selfie");
      const match = selfie.face.found ? documentMatch(selfie.face.template, docPhoto.face) : null;
      return { kind: "face", flow: "facedoc", liveness: null, match, photos: [docPhoto, selfie], meta: meta(2) };
    }
    const photo = await read(files[0], "Photo");
    const match = scanner === "faceid" && photo.face.found ? matchEnrolments(photo.face.template, await listEnrolments(), ready.threshold) : null;
    return { kind: "face", flow: scanner, liveness: null, match, photos: [photo], meta: meta(1) };
  }

  if (scanner === "barcodes" || scanner === "labels") {
    const file = files[0];
    // The same analysis width as the camera flow.
    const image = await pixels(file, 1920);
    const imageUrl = URL.createObjectURL(file);
    // Both modes read the printed labels too (IMEI1, SN, …), so values whose
    // bars are too fine to decode still come through from print.
    const { result } = await client.run<Labelled>({ kind: "labelled", image });
    const fields = result.fields.filter((f) => f.check_digit_valid !== false);
    const barcodes = fields.filter((f) => f.barcode_format).map((f) => ({ format: f.barcode_format!, text: f.value, count: 1 }));
    return { kind: "barcodes", labels: scanner === "labels", barcodes, fields, imageUrl, finishedBy: "one photo", meta: meta(1, 1) };
  }

  if (scanner === "address" || scanner === "text") {
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
    if (scanner === "text") {
      const { result } = await client.run<PageText>({ kind: "text_page", image });
      return { kind: "text", result, imageUrl, meta: meta(2, 1) };
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

  const steps = FLOWS[scanner as keyof typeof FLOWS];
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
