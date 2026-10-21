import type React from "react";
import { useEffect, useRef, useState } from "react";
import { cropToScreen, grab, grabFull, guideInVideo, openCamera, snapshot, toJpeg } from "./camera";
import { drawPolygon, OUTLINE_COLOUR, type OutlineState, outlineState } from "./outline";
import { type CaptureMeta, median } from "./outcome";
import type { ScannerClient } from "./scanner-client";
import { crossCheck, type DocumentKind, type DocumentResult, readingKey } from "./types";

export type DocType = "auto" | "smart_id" | "green_book" | "passport" | "photo_page";

interface Step {
  label: string;
  accepts: DocumentKind[];
  /** Width ÷ height of the guide: ID-1 cards are 85.6 × 54 mm, passport data pages 125 × 88. */
  aspect: number;
  /** The smart ID back is read from its barcode alone; skipping OCR keeps it fast. */
  ocr: boolean;
  /** What the scanner should expect: it narrows the orientation search. */
  expect: "" | "smart_id_front" | "smart_id_back" | "green_book" | "passport";
  /**
   * After this long on the step, settle for the smart ID back's Code 39 (the
   * identity number alone) when its PDF417 will not read: a low-resolution
   * camera cannot resolve the PDF417's modules.
   */
  fallbackAfterMs?: number;
}

const PASSPORTS: DocumentKind[] = ["za_passport", "gb_passport", "other_passport"];
const CODE39_FALLBACK_MS = 8000;

export const FLOWS: Record<DocType, Step[]> = {
  // The face-vs-document flow: any document that carries the holder's photo.
  photo_page: [
    {
      label: "The ID's photo page: passport, smart ID front or ID book",
      accepts: ["za_smart_id_front", "za_green_book", ...PASSPORTS, "other_id_card"],
      aspect: 1.5,
      ocr: true,
      expect: "",
    },
  ],
  auto: [
    {
      label: "Any identity document",
      accepts: ["za_smart_id_front", "za_smart_id_back", "za_green_book", ...PASSPORTS, "other_id_card"],
      aspect: 1.5,
      ocr: true,
      expect: "",
      fallbackAfterMs: CODE39_FALLBACK_MS,
    },
  ],
  smart_id: [
    { label: "Smart ID card — front", accepts: ["za_smart_id_front"], aspect: 1.586, ocr: true, expect: "smart_id_front" },
    {
      label: "Smart ID card — back",
      accepts: ["za_smart_id_back"],
      aspect: 1.586,
      ocr: false,
      expect: "smart_id_back",
      fallbackAfterMs: CODE39_FALLBACK_MS,
    },
  ],
  // The book is usually photographed open and sideways; the scanner turns the page upright itself.
  green_book: [{ label: "Green ID book — photo page", accepts: ["za_green_book"], aspect: 1.42, ocr: true, expect: "green_book" }],
  passport: [{ label: "Passport — photo page", accepts: PASSPORTS, aspect: 1.42, ocr: true, expect: "passport" }],
};

/** Laplacian variance below this is too blurred to read (calibrated on the test set). */
export const SHARPNESS_MIN = 60;
/**
 * More than this fraction of the page under washed-out patches usually hides
 * a field. It only drives the hint: OCR still runs, and a field the glare hid
 * fails its check digits or Luhn, so nothing wrong is captured.
 */
export const GLARE_MAX = 0.05;
/**
 * Two identical accepted readings, from different frames, before capturing.
 * Frames with no reading in between (the fast pass, a blurred frame) do not
 * reset the count; a different reading does, and so does this much time.
 */
const STABLE_READS = 2;
const STABLE_WINDOW_MS = 12000;

export interface Captured {
  step: string;
  result: DocumentResult;
  imageUrl: string;
  /** Read from the smart ID back's Code 39 alone: the PDF417 never read. */
  fallback: boolean;
  /** Time on this step before it was captured, and the frames analysed in it. */
  stepMs?: number;
  frames?: number;
}

export { crossCheck };

type Docscan = { events: unknown[]; frames: unknown[] };
const docscan = () => (window as unknown as { __docscan: Docscan }).__docscan;

function hint(r: DocumentResult | null, step: Step): string {
  if (!r) return "Starting…";
  const q = r.quality;
  if (q.edge_density < 0.01) return "Place the document inside the frame";
  if (!r.document) return "Fit the whole document inside the frame";
  if (q.brightness < 50) return "Too dark — move to better light";
  if (q.sharpness < SHARPNESS_MIN) return "Hold still — the image is blurred";
  if (q.glare > GLARE_MAX && !r.accepted) return "Tilt slightly to remove the glare";
  if (r.kind !== "unknown" && !step.accepts.includes(r.kind)) {
    if (r.kind === "za_smart_id_back") return "That is the back — show the front";
    if (r.kind === "za_smart_id_front") return "That is the front — turn the card over";
    return `That looks like a ${r.kind.replaceAll("_", " ")}`;
  }
  if (r.kind === "za_smart_id_back" && !r.smart_id_barcode) {
    return r.id_barcode ? "Reading the large barcode… hold closer and steady" : "Hold the card closer — its barcodes are too small to read";
  }
  if (r.kind !== "unknown" && !r.accepted) return "Reading… hold steady";
  return "Reading…";
}

export function IdCapture({
  client,
  docType,
  onDone,
}: {
  client: ScannerClient;
  docType: DocType;
  onDone: (c: Captured[], meta: CaptureMeta) => void;
}) {
  const steps = FLOWS[docType];
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const [last, setLast] = useState<DocumentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fps, setFps] = useState({ fast: 0, ocrMs: 0 });
  const [outlineUi, setOutlineUi] = useState<OutlineState>("grey");
  const captured = useRef<Captured[]>([]);
  const step = steps[stepIndex];

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    let lastKey: string | null = null;
    let lastKeyAt = 0;
    let repeats = 0;
    let wantOcr = false;
    let frames = 0;
    let since = performance.now();
    let current = 0;
    let stepStart = performance.now();
    let stepFrames = 0;
    const fastMs: number[] = [];
    const ocrMs: number[] = [];
    const t0 = performance.now();
    const outline = outlineState(setOutlineUi);
    /** The last outline drawn, kept on screen through a frame that finds none while capturing. */
    let lastPts: [number, number][] | null = null;
    const frame = document.createElement("canvas");

    async function loop() {
      const video = videoRef.current;
      const guide = guideRef.current;
      if (stopped) return;
      if (!video || !guide || video.readyState < 2 || client.busy) {
        requestAnimationFrame(loop);
        return;
      }
      const s = steps[current];
      const rect = guideInVideo(video, guide);
      const image = grab(video, rect);
      // The analysed frame, for the saved image.
      snapshot(video, frame);
      const runOcr = s.ocr && wantOcr;
      try {
        const { result, ms } = await client.run<DocumentResult>({ kind: "document", image, runOcr, expected: s.expect });
        if (stopped) return;
        docscan().frames.push({
          step: current,
          ocr: runOcr,
          ms,
          size: [image.width, image.height],
          kind: result.kind,
          accepted: result.accepted,
          document: result.document !== null,
          reading: readingKey(result),
          reasons: result.reasons,
          passes: result.ocr_passes,
          turns: result.quarter_turns,
          timings: result.timings_ms,
        });
        frames++;
        stepFrames++;
        (runOcr ? ocrMs : fastMs).push(ms);
        const now = performance.now();
        if (now - since > 1000) {
          // Computed now: the updater runs later, after the counters reset.
          const fast = Math.round((frames * 1000) / (now - since));
          setFps((f) => ({ ...f, fast }));
          frames = 0;
          since = now;
        }
        if (runOcr) {
          const ocrMs = Math.round(ms);
          setFps((f) => ({ ...f, ocrMs }));
        }
        setLast(result);
        const q = result.quality;
        // Only spend an OCR pass on a frame worth reading: sharp, and the
        // whole document in view (nothing is captured without it).
        wantOcr = q.sharpness >= SHARPNESS_MIN && q.edge_density >= 0.01 && result.document !== null;

        // Capture only a complete document: its whole outline must be in view.
        const fallback =
          s.fallbackAfterMs !== undefined &&
          now - stepStart > s.fallbackAfterMs &&
          result.kind === "za_smart_id_back" &&
          !result.smart_id_barcode &&
          result.id_barcode !== null;
        const readable = s.accepts.includes(result.kind) && result.document;
        const key = readable ? (fallback ? `back39:${result.id_barcode!.value}` : readingKey(result)) : null;
        const live = lastKey !== null && now - lastKeyAt < STABLE_WINDOW_MS;
        if (key) {
          const sameRun = live && key === lastKey;
          if (sameRun) repeats++;
          else repeats = 1;
          // Green from the first frame that counts; a different reading
          // breaks the run (grey) until it is itself read again.
          if (sameRun || !live) outline.set("green", { step: current });
          else outline.set("grey", { step: current, why: "different reading" });
          lastKey = key;
          lastKeyAt = now;
        } else if (lastKey !== null && !live) {
          outline.set("grey", { step: current, why: "no reading for too long" });
          lastKey = null;
          repeats = 0;
        }
        const green = outline.get() !== "grey";
        const pts = result.document ? result.document.corners.map((p) => cropToScreen(video, rect, image.width, p)) : green ? lastPts : null;
        lastPts = pts;
        drawPolygon(overlayRef.current, video, pts, OUTLINE_COLOUR[outline.get()]);
        if (key && repeats >= STABLE_READS) {
          // The saved image is the document itself: flattened from the
          // full-resolution frame with the outline the scanner found.
          const full = grabFull(frame, rect);
          const k = full.width / image.width;
          const corners = result.document!.corners.flatMap(([x, y]) => [x * k, y * k]);
          const [aw, ah] = result.analysed_size;
          const outW = Math.min(2000, Math.round(aw * k));
          const outH = Math.round((outW * ah) / aw);
          const flat = await client.run<ImageData>({ kind: "flatten", image: full, corners, width: outW, height: outH });
          const blob = await toJpeg(flat.result);
          const at = performance.now();
          const entry: Captured = { step: s.label, result, imageUrl: URL.createObjectURL(blob), fallback, stepMs: at - stepStart, frames: stepFrames };
          captured.current.push(entry);
          docscan().events.push({
            type: "captured",
            step: s.label,
            kind: result.kind,
            fallback,
            stepMs: Math.round(at - stepStart),
            sinceStartMs: Math.round(at - t0),
            result,
          });
          // For a host page: one event per captured side, with the reading and
          // the flattened JPEG (`blob`, and `imageUrl` for an <img>).
          window.dispatchEvent(new CustomEvent("docscan:captured", { detail: { ...entry, blob } }));
          stepStart = at;
          stepFrames = 0;
          lastKey = null;
          repeats = 0;
          wantOcr = false;
          if (current + 1 < steps.length) {
            current++;
            setStepIndex(current);
            // The next step starts looking again.
            outline.set("grey", { step: current });
          } else {
            stopped = true;
            outline.set("done");
            const check = crossCheck(captured.current);
            if (check) docscan().events.push({ type: "crosscheck", ...check });
            // The flow is finished: the camera stops when this view unmounts.
            window.dispatchEvent(new CustomEvent("docscan:complete", { detail: { captured: captured.current, crossCheck: check } }));
            onDone(captured.current, {
              source: "camera",
              captureMs: at - t0,
              frames: fastMs.length + ocrMs.length,
              ocrFrames: ocrMs.length,
              fastMs: median(fastMs),
              ocrMs: median(ocrMs),
            });
            return;
          }
        }
      } catch (e) {
        setError(String(e));
      }
      requestAnimationFrame(loop);
    }

    openCamera()
      .then((s) => {
        stream = s;
        // Left before the camera opened (Back to home): release it at once.
        if (stopped) {
          for (const t of s.getTracks()) t.stop();
          return;
        }
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          void videoRef.current.play();
        }
        requestAnimationFrame(loop);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    return () => {
      stopped = true;
      for (const t of stream?.getTracks() ?? []) t.stop();
    };
  }, [client, steps, onDone]);

  return (
    <div className="capture">
      <div className="viewport">
        <video ref={videoRef} playsInline muted />
        <canvas ref={overlayRef} className="overlay outline" />
        <div
          ref={guideRef}
          className={`guide ${outlineUi !== "grey" ? "guide-found" : ""}`}
          style={{ "--aspect": String(step.aspect) } as React.CSSProperties}
        >
          {docType === "passport" ? <div className="mrz-band" /> : null}
        </div>
        <div className="step-label" data-testid="step">
          {step.label}
          {steps.length > 1 ? <span className="step-count">{` ${stepIndex + 1} of ${steps.length}`}</span> : null}
        </div>
        <div className="capture-foot">
          <div className="hint" data-testid="hint">
            {error ?? hint(last, step)}
          </div>
          <div className="stats">
            {fps.fast} analyses/s · last OCR {fps.ocrMs} ms · sharp {last?.quality.sharpness.toFixed(0) ?? "–"} · glare{" "}
            {((last?.quality.glare ?? 0) * 100).toFixed(1)}% · {last?.kind.replaceAll("_", " ") ?? "–"}
          </div>
        </div>
      </div>
    </div>
  );
}
