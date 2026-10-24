import { useEffect, useRef, useState } from "react";
import { grab, openCamera, snapshot, still } from "./camera";
import { OUTLINE_COLOUR, outlineState } from "./outline";
import { type CaptureMeta, median, type Outcome, type SeenCode } from "./outcome";
import type { ScannerClient } from "./scanner-client";
import type { Barcode, Labelled, LabelledField } from "./types";

/**
 * A code is listed once read in this many frames. rxing occasionally reports
 * a spurious short code (a UPC-E inside a dense symbol) in a single frame; a
 * real code in view is read again in the next.
 */
export const CONFIRM_FRAMES = 2;
/** Analyse up to this width: small codes need every pixel the camera gives. */
const MAX_WIDTH = 1920;

/**
 * Every this many frames is an OCR pass that names the codes: often in
 * device-label mode, where the printed values are the point, and less often
 * in barcodes mode, where OCR mostly adds names and should not slow decoding.
 */
const LABEL_EVERY = 4;
const LABEL_EVERY_BARCODES = 6;

/**
 * The scan finishes on its own once at least one code is confirmed and no new
 * one has been confirmed for this long. A sheet of codes held still confirms
 * every readable code within about a second of the first (a fast pass takes
 * 40–200 ms at 1280×720, and each code needs two reads), so 2.5 s of nothing
 * new means the set is complete, while still being short enough that staff do
 * not wonder whether it is stuck. A code that keeps failing to read is not
 * waited for: staff can rescan it on its own.
 *
 * Device labels use the same quiet rule, once at least one field with a check
 * digit (an IMEI's Luhn, an EAN's checksum) has been listed: an OCR pass takes
 * 1–4 s, so in practice it means "the next pass found nothing new".
 */
export const QUIET_MS = 2500;
/**
 * Device labels finish sooner when this many consecutive OCR passes list the
 * same fields and every value with a check digit in those passes is valid: a
 * misread digit would fail its check, so two clean, identical passes are a
 * settled reading.
 */
export const STABLE_PASSES = 2;

/**
 * A labelled field is listed once seen with a passing check digit (or, for a
 * value with none, in two OCR passes): a single misread digit fails the check.
 */
function fieldKey(f: LabelledField) {
  return `${f.label ?? ""}|${f.value}`;
}

type Docscan = { events: unknown[]; frames: unknown[] };
const docscan = () => (window as unknown as { __docscan: Docscan }).__docscan;

/**
 * Reads every barcode in the full frame, outlines each, and keeps a running
 * list. With `labels`, it also reads the printed text: each code takes its
 * label (`IMEI1`, `SN`), printed values with no barcode are listed, and check
 * digits are verified. It finishes by itself (QUIET_MS, STABLE_PASSES), takes
 * a still of the last frame, releases the camera and hands the set on.
 */
export function MultiBarcode({ client, labels = false, onDone }: { client: ScannerClient; labels?: boolean; onDone: (o: Outcome) => void }) {
  const [fields, setFields] = useState<(LabelledField & { seen: number })[]>([]);
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const [seen, setSeen] = useState<SeenCode[]>([]);
  const [rate, setRate] = useState({ ms: 0, inFrame: 0 });
  const [quietLeft, setQuietLeft] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const finishNow = useRef(false);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    let disposed = false;
    const all = new Map<string, SeenCode>();
    const labelled = new Map<string, LabelledField & { seen: number }>();
    let shown: (LabelledField & { seen: number })[] = [];
    let frame = 0;
    /** When the last new code was confirmed, or the listed fields last changed. */
    let lastNewAt = 0;
    let lastSignature = "";
    let stablePasses = 0;
    const barcodeMs: number[] = [];
    const ocrMs: number[] = [];
    const t0 = performance.now();
    // Barcodes: green from the first confirmed code (the quiet rule starts),
    // and nothing breaks the run: confirmed codes stay confirmed. Device
    // labels: green from the first listed field with a check digit.
    const outline = outlineState(() => {});
    // The still is the frame that read the most codes, not whatever the
    // camera shows when the quiet rule fires (staff may already be moving away).
    let frameNow = document.createElement("canvas");
    let best = document.createElement("canvas");
    let bestCount = -1;
    const release = () => {
      for (const t of stream?.getTracks() ?? []) t.stop();
    };
    const confirmed = () => [...all.values()].filter((c) => c.count >= CONFIRM_FRAMES);
    const hasChecked = () => shown.some((f) => f.check_digit_valid === true);

    async function finish(video: HTMLVideoElement, finishedBy: string) {
      stopped = true;
      // A hand finish before any code counted still goes through green.
      outline.set("green");
      const at = performance.now();
      const source = bestCount > 0 ? best : video;
      const blob = await still(source, { x: 0, y: 0, w: video.videoWidth, h: video.videoHeight }).catch(() => null);
      release();
      if (disposed) return;
      const imageUrl = blob ? URL.createObjectURL(blob) : null;
      const barcodes = confirmed();
      const meta: CaptureMeta = {
        source: "camera",
        captureMs: at - t0,
        frames: barcodeMs.length + ocrMs.length,
        ocrFrames: ocrMs.length,
        fastMs: median(barcodeMs),
        ocrMs: median(ocrMs),
      };
      docscan().events.push({ type: "complete", mode: labels ? "labels" : "multi", finishedBy, sinceStartMs: Math.round(meta.captureMs), barcodes: barcodes.map(({ format, text }) => ({ format, text })), fields: shown });
      // For a host page: the set is final and the camera is off.
      window.dispatchEvent(new CustomEvent("docscan:complete", { detail: { barcodes, fields: shown, imageUrl, blob } }));
      outline.set("done");
      onDone({ kind: "barcodes", labels, barcodes, fields: shown, imageUrl, finishedBy, meta });
    }

    /** Whether a finishing rule fires now; the reason if so. */
    function finishReason(now: number): string | null {
      if (finishNow.current) return "finished by hand";
      if (labels && stablePasses >= STABLE_PASSES) return `labels stable for ${STABLE_PASSES} OCR passes, check digits valid`;
      // Barcodes mode starts its quiet clock on a confirmed code or on a
      // printed field with a valid check digit (bars too fine to decode).
      const started = labels ? hasChecked() : confirmed().length > 0 || hasChecked();
      if (started && now - lastNewAt >= QUIET_MS) return `nothing new for ${QUIET_MS / 1000} s`;
      return null;
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
      // Both modes read the printed labels, so a code is named IMEI1 or SN
      // (above, below or left of it) and a value whose bars will not decode
      // still comes through from print.
      if (frame % (labels ? LABEL_EVERY : LABEL_EVERY_BARCODES) === 0) {
        try {
          const { result, ms } = await client.run<Labelled>({ kind: "labelled", image });
          if (stopped) return;
          ocrMs.push(ms);
          for (const f of result.fields) {
            const key = fieldKey(f);
            const prev = labelled.get(key);
            labelled.set(key, { ...f, seen: (prev?.seen ?? 0) + 1 });
          }
          const listed = [...labelled.values()].filter((f) => f.check_digit_valid === true || (f.check_digit_valid === null && f.seen >= 2));
          // A label (IMEI1) keeps only its best-supported value.
          const byLabel = new Map<string, LabelledField & { seen: number }>();
          for (const f of listed) {
            const k = f.label ?? `${f.barcode_format}|${f.value}`;
            const cur = byLabel.get(k);
            if (!cur || f.seen > cur.seen) byLabel.set(k, f);
          }
          // Number unlabelled codes in reading order across the whole capture.
          let n = 0;
          shown = [...byLabel.values()]
            .sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0])
            .map((f) => ({ ...f, name: f.label ?? `Barcode ${++n}` }));
          const now = performance.now();
          const signature = shown.map(fieldKey).sort().join("\n");
          // Clean: something with a check digit is listed, and nothing this pass read failed its check.
          const clean = hasChecked() && result.fields.every((f) => f.check_digit_valid !== false);
          if (signature !== lastSignature) {
            lastSignature = signature;
            lastNewAt = now;
            stablePasses = clean ? 1 : 0;
          } else {
            stablePasses = clean ? stablePasses + 1 : 0;
          }
          if (hasChecked()) outline.set("green", { fields: shown.length });
          setFields(shown);
          window.dispatchEvent(new CustomEvent("docscan:labels", { detail: { fields: shown } }));
          docscan().events.push({ type: "labels", fields: shown, stablePasses });
          docscan().frames.push({ ocr: true, ms, size: [image.width, image.height], fields: shown.length });
          const why = finishReason(now);
          if (why) return void finish(video, why);
        } catch (e) {
          setError(String(e));
        }
        requestAnimationFrame(loop);
        return;
      }
      try {
        const { result, ms } = await client.run<Barcode[]>({ kind: "barcodes", image, formats: [] });
        if (stopped) return;
        barcodeMs.push(ms);
        if (result.length >= bestCount && result.length > 0) {
          // Swap rather than copy: the frame just analysed becomes the best one.
          [best, frameNow] = [frameNow, best];
          bestCount = result.length;
        }
        const now = performance.now();
        const fresh: Barcode[] = [];
        for (const b of result) {
          const key = `${b.format}|${b.text}`;
          const s = all.get(key) ?? { format: b.format, text: b.text, count: 0 };
          s.count++;
          all.set(key, s);
          if (s.count === CONFIRM_FRAMES) fresh.push(b);
        }
        docscan().frames.push({ ms, size: [image.width, image.height], read: result.length });
        if (fresh.length) {
          lastNewAt = now;
          docscan().events.push({ type: "barcodes", sinceStartMs: Math.round(now - t0), barcodes: fresh.map(({ format, text }) => ({ format, text })) });
        }
        if (!labels && confirmed().length) outline.set("green", { codes: confirmed().length });
        draw(video, overlay, result, scale, OUTLINE_COLOUR[outline.get()]);
        setSeen([...all.values()]);
        setRate({ ms: Math.round(ms), inFrame: result.length });
        const started = labels ? hasChecked() : confirmed().length > 0 || hasChecked();
        setQuietLeft(started ? Math.max(0, QUIET_MS - (now - lastNewAt)) : null);
        const why = finishReason(now);
        if (why) return void finish(video, why);
      } catch (e) {
        setError(String(e));
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
      stopped = true;
      release();
    };
  }, [client, labels, onDone]);

  const confirmedCount = seen.filter((s) => s.count >= CONFIRM_FRAMES).length;
  const hint =
    error ??
    (confirmedCount === 0
      ? labels
        ? "Fill the frame with the label"
        : "Point at the barcodes"
      : quietLeft !== null
        ? `${confirmedCount} found · finishing in ${(quietLeft / 1000).toFixed(1)} s unless more appear`
        : `${confirmedCount} found · reading the label…`);

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
          {(confirmedCount > 0 || fields.length > 0) && (
            <button type="button" className="finish" data-testid="finish" onClick={() => (finishNow.current = true)}>
              Finish now
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
