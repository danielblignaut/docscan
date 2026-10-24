import { useEffect, useRef, useState } from "react";
import { createProcessingSession } from "./processing";
import { ProcessingView } from "./ProcessingView";
import { grab, openCamera, snapshot, still } from "./camera";
import { OUTLINE_COLOUR, outlineState } from "./outline";
import { type CaptureMeta, median, type Outcome, type SeenCode } from "./outcome";
import type { ScannerClient } from "./scanner-client";
import type { Barcode, Labelled, LabelledField } from "./types";
import { CONFIRM_FRAMES, countFrame, finishCapture, QUIET_FRAMES, QUIET_MS, quietClock, quietDone, quietLeft, STABLE_PASSES } from "./barcode-completion";

export { CONFIRM_FRAMES, QUIET_MS, STABLE_PASSES } from "./barcode-completion";
/** Analyse up to this width: small codes need every pixel the camera gives. */
const MAX_WIDTH = 1920;

type Docscan = { events: unknown[]; frames: unknown[] };
const docscan = () => (window as unknown as { __docscan: Docscan }).__docscan;

/**
 * Reads every barcode in the full frame, outlines each, and keeps a running
 * list. It finishes by itself (the quiet rule in barcode-completion.ts) or by
 * hand, releases the camera, and only then does the slow work: a still of the
 * frame that read the most codes and, with `labels`, an OCR pass over up to
 * STABLE_PASSES distinct acquired frames on `reader`, which names each code
 * (`IMEI1`, `SN`), lists printed values with no barcode and verifies check
 * digits. A failed still or label read keeps the confirmed codes.
 */
export function MultiBarcode({ client, reader = client, labels = false, onDone }: { client: ScannerClient; reader?: ScannerClient; labels?: boolean; onDone: (o: Outcome) => void }) {
  const [fields, setFields] = useState<LabelledField[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const [seen, setSeen] = useState<SeenCode[]>([]);
  const [rate, setRate] = useState({ ms: 0, inFrame: 0 });
  const [quietLeftMs, setQuietLeftMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const finishNow = useRef(false);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    let disposed = false;
    const operation = createProcessingSession(labels ? "labels" : "barcodes", "camera");
    /** Which analysed frame each canvas holds (canvases swap roles). */
    const snapshots = new WeakMap<HTMLCanvasElement, number>();
    const all = new Map<string, SeenCode>();
    const clock = quietClock();
    let frame = 0;
    const barcodeMs: number[] = [];
    const t0 = performance.now();
    // Barcodes: green from the first confirmed code (the quiet rule can then
    // fire), and nothing breaks the run: confirmed codes stay confirmed.
    // Device labels stay grey until capture: the label is read afterwards.
    const outline = outlineState(() => {});
    // The still is the frame that read the most codes (the latest such), not
    // whatever the camera shows when the scan finishes: staff may already be
    // moving away. With no code read yet, `best` is the latest analysed frame
    // and `frameNow` the one before, so a hand capture still has two frames.
    let frameNow = document.createElement("canvas");
    let best = document.createElement("canvas");
    let bestCount = -1;
    const release = () => {
      for (const t of stream?.getTracks() ?? []) t.stop();
    };
    const confirmed = () => [...all.values()].filter((c) => c.count >= CONFIRM_FRAMES);

    async function finish(finishedBy: string) {
      stopped = true;
      outline.set("green");
      const at = performance.now();
      // Distinct acquired frames, never repeated OCR of one image.
      const sources = [best];
      if (snapshots.has(frameNow) && snapshots.get(frameNow) !== snapshots.get(best)) sources.push(frameNow);
      const labelFrames = labels ? sources.slice(0, STABLE_PASSES).map((canvas) =>
        grab(canvas, { x: 0, y: 0, w: canvas.width, h: canvas.height }, MAX_WIDTH)) : [];
      const encodeStill = () => still(best, { x: 0, y: 0, w: best.width, h: best.height });
      release();
      // Frames this step consumes: the still's alone, or each label frame (the still's among them).
      operation.captured({ inputCount: labels ? labelFrames.length : 1 });
      operation.stage(labels ? "reading_labels" : "finalizing_barcodes");
      setStage(labels ? "Reading printed labels…" : "Finishing barcode reading…");
      const barcodes = confirmed();
      if (labels && barcodes.length) window.dispatchEvent(new CustomEvent("docscan:partial", {
        detail: { operationId: operation.id, scanner: "labels", status: "processing", barcodes },
      }));
      try {
        const done = await finishCapture({
          encodeStill,
          labelFrames,
          readLabel: (image) => reader.run<Labelled>({ kind: "labelled", image }),
          onFields: (shown) => {
            setFields(shown);
            window.dispatchEvent(new CustomEvent("docscan:labels", { detail: { operationId: operation.id, fields: shown } }));
          },
          cancelled: () => disposed,
        });
        if (!done || disposed) return;
        const { blob, fields: shown, ocrMs, labelReadError, labelReadWarning } = done;
        const imageUrl = blob ? URL.createObjectURL(blob) : null;
        const meta: CaptureMeta = { source: "camera", captureMs: at - t0, frames: barcodeMs.length + ocrMs.length,
          ocrFrames: ocrMs.length, fastMs: median(barcodeMs), ocrMs: median(ocrMs) };
        docscan().events.push({ type: "complete", mode: labels ? "labels" : "multi", finishedBy,
          sinceStartMs: Math.round(performance.now() - t0), barcodes: barcodes.map(({ format, text }) => ({ format, text })), fields: shown,
          ...(labelReadError ? { labelReadError } : {}), ...(labelReadWarning ? { labelReadWarning } : {}) });
        operation.complete();
        window.dispatchEvent(new CustomEvent("docscan:complete", { detail: { operationId: operation.id, barcodes, fields: shown, imageUrl, blob,
          ...(labelReadError ? { labelReadError } : {}), ...(labelReadWarning ? { labelReadWarning } : {}) } }));
        outline.set("done");
        onDone({ kind: "barcodes", operationId: operation.id, labels, barcodes, fields: shown, imageUrl, ...(blob ? { blob } : {}), finishedBy, meta,
          ...(labelReadError ? { labelReadError } : {}), ...(labelReadWarning ? { labelReadWarning } : {}) });
      } catch (error) {
        if (disposed) return;
        operation.fail(error);
        setError(error instanceof Error ? error.message : String(error));
      }
    }

    async function loop() {
      const video = videoRef.current;
      const overlay = overlayRef.current;
      if (stopped) return;
      if (!video || !overlay || video.readyState < 2 || client.busy) {
        requestAnimationFrame(loop);
        return;
      }
      const rect = { x: 0, y: 0, w: video.videoWidth, h: video.videoHeight };
      const image = grab(video, rect, MAX_WIDTH);
      snapshot(video, frameNow);
      const scale = image.width / video.videoWidth;
      frame++;
      snapshots.set(frameNow, frame);
      try {
        const { result, ms } = await client.run<Barcode[]>({ kind: "barcodes", image, formats: [] });
        if (stopped) return;
        barcodeMs.push(ms);
        if (result.length > 0 ? result.length >= bestCount : bestCount <= 0) {
          // Swap rather than copy: the frame just analysed becomes the best one.
          [best, frameNow] = [frameNow, best];
          bestCount = result.length;
        }
        const now = performance.now();
        const fresh = countFrame(all, clock, result, now);
        docscan().frames.push({ ms, size: [image.width, image.height], read: result.length });
        if (fresh.length) {
          docscan().events.push({ type: "barcodes", sinceStartMs: Math.round(now - t0), barcodes: fresh.map(({ format, text }) => ({ format, text })) });
        }
        if (!labels && confirmed().length) outline.set("green", { codes: confirmed().length });
        draw(video, overlay, result, scale, OUTLINE_COLOUR[outline.get()]);
        setSeen([...all.values()].map((s) => ({ ...s })));
        setRate({ ms: Math.round(ms), inFrame: result.length });
        setQuietLeftMs(quietLeft(clock, now));
        if (finishNow.current) return void finish("finished by hand");
        if (quietDone(clock, now)) return void finish(`nothing new for ${QUIET_MS / 1000} s and ${QUIET_FRAMES} frames`);
      } catch (e) {
        if (disposed || stopped) return;
        setError(String(e));
        // Retry by reopening the scanner, never by spawning workers each frame.
        return;
      }
      requestAnimationFrame(loop);
    }

    openCamera()
      .then(async (s) => {
        stream = s;
        if (stopped) return release();
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          await videoRef.current.play();
        }
        if (stopped) return;
        requestAnimationFrame(loop);
      })
      .catch((e) => { if (!stopped) setError(e instanceof Error ? e.message : String(e)); });
    return () => {
      disposed = true;
      operation.cancel();
      stopped = true;
      release();
    };
  }, [client, reader, labels, onDone]);

  const confirmedCount = seen.filter((s) => s.count >= CONFIRM_FRAMES).length;
  const hint =
    error ??
    (confirmedCount === 0
      ? labels
        ? "Fill the frame with the label"
        : "Point at the barcodes"
      : quietLeftMs !== null
        ? `${confirmedCount} found · finishing in ${(quietLeftMs / 1000).toFixed(1)} s unless more appear`
        : `${confirmedCount} found · reading the label…`);

  if (stage) return <ProcessingView title={labels ? "Device label" : "Barcodes"} stage={error ?? stage} failed={error !== null} />;
  return (
    <div className="capture">
      <div className="viewport">
        <video ref={videoRef} playsInline muted />
        <canvas ref={overlayRef} className="overlay" />
        <div className="step-label" data-testid="step">
          {labels ? "Device label" : "Barcodes"}
        </div>
        <div className="capture-foot">
          {(confirmedCount > 0 || fields.length > 0) && (
            <div className="sheet">
              {fields.length > 0 && (
                <dl className="live-fields" data-testid="fields">
                  {fields.map((f) => (
                    <div key={`${f.name}|${f.value}`}>
                      <dt>{f.name}</dt>
                      <dd>
                        <code>{f.value}</code> {f.check_digit_valid ? <small className="ok">✓</small> : null}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              <ul className="codes" data-testid="codes">
                {seen.map((s) => (
                  <li key={`${s.format}|${s.text}`} className={s.count < CONFIRM_FRAMES ? "pending" : undefined}>
                    <b>{s.format}</b> <code>{s.text}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="hint" data-testid="hint">
            {hint}
          </div>
          {(labels || confirmedCount > 0 || fields.length > 0) && (
            <button type="button" className="finish" data-testid="finish" onClick={() => (finishNow.current = true)}>
              {labels ? "Capture label now" : "Finish now"}
            </button>
          )}
          <div className="stats">
            {rate.inFrame} in frame · {rate.ms} ms per frame
          </div>
        </div>
      </div>
    </div>
  );
}

/** Maps analysis-image points to the on-screen video (object-fit: cover) and outlines each code. */
function draw(video: HTMLVideoElement, canvas: HTMLCanvasElement, codes: Barcode[], scale: number, colour: string) {
  const box = video.getBoundingClientRect();
  canvas.width = box.width * devicePixelRatio;
  canvas.height = box.height * devicePixelRatio;
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  const s = Math.max(box.width / video.videoWidth, box.height / video.videoHeight);
  const offX = (video.videoWidth * s - box.width) / 2;
  const offY = (video.videoHeight * s - box.height) / 2;
  const map = ([x, y]: [number, number]) => [(x / scale) * s - offX, (y / scale) * s - offY] as const;
  ctx.lineWidth = 3;
  ctx.font = "600 13px system-ui";
  for (const c of codes) {
    if (!c.points.length) continue;
    const pts = c.points.map(map);
    ctx.strokeStyle = colour;
    ctx.beginPath();
    if (pts.length <= 2) {
      // 1D codes report scan-line end points: draw a bar across them.
      const [a, b] = [pts[0], pts[pts.length - 1]];
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
    } else {
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
    }
    ctx.stroke();
    const [lx, ly] = pts[0];
    const label = `${c.format}: ${c.text.slice(0, 24)}`;
    ctx.fillStyle = "rgba(0,0,0,.7)";
    ctx.fillRect(lx, ly - 18, ctx.measureText(label).width + 8, 18);
    ctx.fillStyle = "#fff";
    ctx.fillText(label, lx + 4, ly - 5);
  }
}
