// The measurements, in a module Worker (bench.mjs starts it): load the build,
// start its thread pool when multithreaded, decode the inputs once, then time
// each call `repeats` times after a warm-up and report per-image medians.
self.onmessage = async ({ data: { pkg, threads, inputs } }) => {
  try {
    const mod = await import(`/repo/${pkg}/docscan.js`);
    await mod.default();
    if (threads > 1) {
      if (!self.crossOriginIsolated) throw new Error("not cross-origin isolated");
      await mod.initThreadPool(threads);
    }
    const bytes = async (u) => new Uint8Array(await (await fetch(u)).arrayBuffer());
    const pixels = async (u, max = 1280) => {
      const bmp = await createImageBitmap(await (await fetch(u)).blob());
      const k = Math.min(1, max / bmp.width);
      const w = Math.round(bmp.width * k);
      const h = Math.round(bmp.height * k);
      const ctx = new OffscreenCanvas(w, h).getContext("2d");
      ctx.drawImage(bmp, 0, 0, w, h);
      const name = decodeURIComponent(u.split("/").pop()).replace(/\.[a-z]+$/, "");
      return { w, h, data: new Uint8Array(ctx.getImageData(0, 0, w, h).data.buffer), name };
    };
    const scanner = new mod.Scanner();
    scanner.load_ocr(await bytes("/repo/models/text-detection.rten"), await bytes("/repo/models/text-recognition.rten"));
    const face = new mod.FaceScanner();
    face.load_tracker(await bytes("/repo/models/face/face_detector.onnx"), await bytes("/repo/models/face/face_landmarks_detector.onnx"));
    const R = inputs.repeats;
    const time = async (list, fn) => {
      const items = [];
      const samples = [];
      for (const u of list) {
        const im = await pixels(u);
        fn(im); // warm-up
        const ts = [];
        for (let r = 0; r < R; r++) {
          const t0 = performance.now();
          fn(im);
          ts.push(performance.now() - t0);
        }
        ts.sort((a, b) => a - b);
        items.push(im.name);
        samples.push(ts[Math.floor(ts.length / 2)]);
      }
      return { items, samples, repeats: R, threads };
    };
    const out = {};
    out.barcodes_ms = { ...(await time(inputs.barcodes, (im) => scanner.barcodes(im.data, im.w, im.h, []))), desc: "barcodes(): every barcode in a camera frame" };
    out.id_fast_ms = { ...(await time(inputs.document, (im) => scanner.document(im.data, im.w, im.h, false, ""))), desc: "document() without OCR: the fast pass" };
    out.id_ocr_ms = { ...(await time(inputs.document, (im) => scanner.document(im.data, im.w, im.h, true, ""))), desc: "document() with OCR" };
    out.poa_page_ms = { ...(await time(inputs.page, (im) => scanner.page(im.data, im.w, im.h))), desc: "page(): proof-of-address outline and quality per frame" };
    out.face_track_ms = { ...(await time(inputs.face, (im) => face.track(im.data, im.w, im.h))), desc: "FaceScanner.track(): detect, mesh, pose, quality per frame" };
    self.postMessage(out);
  } catch (e) {
    self.postMessage({ error: String(e) });
  }
};
