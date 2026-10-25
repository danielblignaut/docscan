// Shared hands-free page capture. Acquisition ends at the second stable
// accepted frame: the camera is released, `docscan:capture-ready` fires and
// the processing view replaces the camera before flattening and OCR start.
// See docs/capture-processing.md.
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { cropToScreen, grab, grabFull, guideInVideo, openCamera, snapshot, toJpeg } from "./camera";
import { drawPolygon, OUTLINE_COLOUR, type OutlineState, outlineState } from "./outline";
import { type CaptureMeta, median } from "./outcome";
import { createProcessingSession } from "./processing";
import { ProcessingView } from "./ProcessingView";
import type { ScannerClient } from "./scanner-client";
import type { PageAnalysis } from "./types";

/** A4 portrait, width ÷ height. */
const A4 = 210 / 297;
/** Two consecutive accepted frames with the outline within this fraction of the page size. */
const STABLE_READS = 2;
const STABLE_TOLERANCE = 0.04;
/** The saved colour image's long side (for a person, or a VLM, to look at). */
const COLOUR_LONG = 1024;
/** The flattened page handed to OCR: at most this long (it is read at 1754). */
const FLAT_MAX_LONG = 2480;
/** The analysed crop extends this fraction of the guide's size beyond it on every side. */
const GUIDE_MARGIN = 0.15;

export interface CapturedPage {
  flat: ImageData;
  imageUrl: string;
  blob: Blob;
  captureMs: number;
}

/**
 * What `onRead` is handed besides the page: whether the screen is still
 * mounted, and `done`, called once the reading is ready and before it is
 * published (the processing lifecycle completes there, ahead of
 * `docscan:complete`). A throw is a failed read: the page offers a recapture.
 */
export interface PageWork {
  operationId: string;
  active: () => boolean;
  done: () => void;
}

/** Processing stages, as published in `docscan:processing` and as shown. */
const STAGES = { flatten: "Flattening the page…", read: "Reading the page (OCR)…" } as const;

type Docscan = { events: unknown[]; frames: unknown[] };
const docscan = () => (window as unknown as { __docscan: Docscan }).__docscan;

function hint(p: PageAnalysis | null): string {
  if (!p) return "Starting…";
  const r = p.reasons[0];
  if (!r) return "Hold still…";
  if (r === "no page in view" || r === "no page outline") return "Fit the whole page inside the frame";
  if (r.includes("shape")) return "Show one whole page, flat";
  if (r.includes("out of view")) return "Move back: part of the page is cut off";
  if (r === "too dark") return "Too dark — move to better light";
  if (r === "blurred") return "Hold still — the image is blurred";
  if (r === "glare") return "Tilt slightly to remove the glare";
  return r;
}

function similar(a: PageAnalysis, b: PageAnalysis): boolean {
  if (!a.outline || !b.outline || !a.size) return false;
  const tol = STABLE_TOLERANCE * Math.max(...a.size);
  return a.outline.corners.every(([x, y], i) => Math.hypot(x - b.outline!.corners[i][0], y - b.outline!.corners[i][1]) < tol);
}

export function PageCapture({ client, captureClient, title, scanner, onRead }: {
  /** Flattens and reads the captured page. */
  client: ScannerClient;
  /** Analyses the live frames (`page`); a model-free worker answers at once. Defaults to `client`. */
  captureClient?: ScannerClient;
  title: string;
  /** The scanner id published in the processing events. */
  scanner: string;
  onRead: (page: CapturedPage, meta: CaptureMeta, work: PageWork) => Promise<void>;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const [last, setLast] = useState<PageAnalysis | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fps, setFps] = useState(0);
  const [outlineUi, setOutlineUi] = useState<OutlineState>("grey");
  /** Bumped by "Capture again": a fresh camera, run and session. */
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    let mounted = true;
    const live = captureClient ?? client;
    const session = createProcessingSession(scanner, "camera");
    setStage(null);
    setError(null);
    setLast(null);
    let previous: PageAnalysis | null = null;
    let repeats = 0;
    const outline = outlineState(setOutlineUi);
    /** The analysed frame, for the saved page. */
    const frame = document.createElement("canvas");
    let frames = 0;
    let since = performance.now();
    const pageMs: number[] = [];
    const t0 = performance.now();
    const release = () => {
      for (const t of stream?.getTracks() ?? []) t.stop();
    };

    async function capture(rect: ReturnType<typeof guideInVideo>, analysedWidth: number, page: PageAnalysis) {
      stopped = true;
      const captureMs = performance.now() - t0;
      const full = grabFull(frame, rect);
      // The camera is no longer needed: release it, say so, and show the
      // processing view before the slow part.
      release();
      session.captured({ step: title.toLowerCase(), inputCount: 1 });
      docscan().events.push({ type: "capture_ready", sinceStartMs: Math.round(captureMs), operationId: session.id });
      session.stage("flatten");
      setStage(STAGES.flatten);
      let imageUrl: string | null = null;
      let handed = false;
      try {
        const flattened = await flattenPage(client, full, full.width / analysedWidth, page);
        imageUrl = flattened.imageUrl;
        if (!mounted) { URL.revokeObjectURL(imageUrl); return; }
        window.dispatchEvent(new CustomEvent("docscan:captured", { detail: { step: title.toLowerCase(), imageUrl, blob: flattened.blob, page } }));
        docscan().events.push({ type: "page_captured", sinceStartMs: Math.round(captureMs), page });
        session.stage("read");
        setStage(STAGES.read);
        const done = () => { handed = true; session.complete(); };
        await onRead({ flat: flattened.flat, imageUrl, blob: flattened.blob, captureMs }, { source: "camera", captureMs, frames: pageMs.length, fastMs: median(pageMs) }, { operationId: session.id, active: () => mounted, done });
        // Read, and still on screen: the reader owns the image from here.
        if (mounted) { done(); outline.set("done"); }
      } catch (e) {
        // A failed read never completes: the page asks for a recapture.
        if (imageUrl && !handed) URL.revokeObjectURL(imageUrl);
        session.fail(e);
        if (mounted) setError(e instanceof Error ? e.message : String(e));
      }
    }

    async function loop() {
      const video = videoRef.current;
      const guide = guideRef.current;
      if (stopped) return;
      if (!video || !guide || video.readyState < 2 || live.busy) {
        requestAnimationFrame(loop);
        return;
      }
      // A generous margin round the guide: a page is large, and held a little
      // low or high it should still be found whole.
      const rect = guideInVideo(video, guide, GUIDE_MARGIN);
      const image = grab(video, rect);
      snapshot(video, frame);
      try {
        const { result, ms } = await live.run<PageAnalysis>({ kind: "page", image });
        if (stopped) return;
        docscan().frames.push({ ms, size: [image.width, image.height], accepted: result.accepted, reasons: result.reasons, shape: result.shape, quality: result.quality });
        frames++;
        pageMs.push(ms);
        const now = performance.now();
        if (now - since > 1000) {
          setFps(Math.round((frames * 1000) / (now - since)));
          frames = 0;
          since = now;
        }
        setLast(result);
        const wasRunning = repeats > 0;
        if (result.accepted && previous?.accepted && similar(result, previous)) repeats++;
        else repeats = result.accepted ? 1 : 0;
        // Green from the first accepted frame; grey when the run breaks (a
        // rejected frame, or the page moved), until a run starts again.
        if (repeats > 1 || (repeats === 1 && !wasRunning)) outline.set("green");
        else outline.set("grey", { why: repeats ? "page moved" : (result.reasons[0] ?? "rejected") });
        const pts = result.outline ? result.outline.corners.map((c) => cropToScreen(video, rect, image.width, c)) : null;
        drawPolygon(overlayRef.current, video, pts, OUTLINE_COLOUR[outline.get()]);
        previous = result;
        if (repeats >= STABLE_READS) {
          await capture(rect, image.width, result);
          return;
        }
      } catch (e) {
        if (!mounted) return;
        session.fail(e);
        setError(String(e));
        stopped = true;
        release();
        return;
      }
      requestAnimationFrame(loop);
    }

    openCamera(window.innerHeight > window.innerWidth)
      .then((s) => {
        stream = s;
        // Left before the camera opened (Back to home): release it at once.
        if (stopped) return release();
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          void videoRef.current.play();
        }
        requestAnimationFrame(loop);
      })
      .catch((e) => {
        session.fail(e);
        if (mounted) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      mounted = false;
      stopped = true;
      release();
      // Left mid-read (Back to home): the operation ends cancelled. A no-op
      // once it completed or failed.
      session.cancel();
    };
  }, [client, captureClient, title, scanner, onRead, attempt]);

  if (stage && error) {
    return (
      <main className="processing-panel" data-testid="capture-error" role="alert">
        <h1>{title}</h1>
        <p>The page could not be read: {error}</p>
        <button type="button" className="primary" data-testid="capture-again" onClick={() => setAttempt((a) => a + 1)}>Capture again</button>
      </main>
    );
  }
  if (stage) return <ProcessingView title={title} stage={stage} />;

  return (
    <div className="capture">
      <div className="viewport">
        <video ref={videoRef} playsInline muted />
        <canvas ref={overlayRef} className="overlay outline" />
        <div ref={guideRef} className={`guide ${outlineUi !== "grey" ? "guide-found" : ""}`} style={{ "--aspect": String(A4) } as React.CSSProperties} />
        <div className="step-label" data-testid="step">{title}</div>
        <div className="capture-foot">
          <div className="hint" data-testid="hint">
            {error ?? hint(last)}
          </div>
          <div className="stats">
            {fps} analyses/s · sharp {last?.quality.sharpness.toFixed(0) ?? "–"} · glare {((last?.quality.glare ?? 0) * 100).toFixed(1)}% ·{" "}
            {last?.shape ?? "no page"}
            {last?.size ? ` ${last.size[0]}×${last.size[1]}` : ""}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * The page cut out of `full` (the frame `page` was found in, `k` times the
 * analysed size) and squared up, for OCR; and a smaller colour JPEG of it to
 * keep and show, made before the page is handed to the worker.
 */
export async function flattenPage(client: ScannerClient, full: ImageData, k: number, page: PageAnalysis) {
  const corners = page.outline!.corners.flatMap(([x, y]) => [x * k, y * k]);
  const [pw, ph] = page.size!;
  const scale = Math.min(k, FLAT_MAX_LONG / Math.max(pw, ph));
  const [w, h] = [Math.round(pw * scale), Math.round(ph * scale)];
  const { result: flat } = await client.run<ImageData>({ kind: "flatten", image: full, corners, width: w, height: h });
  const blob = await toJpeg(downscale(flat, COLOUR_LONG));
  return { flat, blob, imageUrl: URL.createObjectURL(blob) };
}

/** An image scaled so its long side is at most `long`. */
export function downscale(image: ImageData, long: number): ImageData {
  const k = Math.min(1, long / Math.max(image.width, image.height));
  if (k === 1) return image;
  const src = new OffscreenCanvas(image.width, image.height);
  src.getContext("2d")!.putImageData(image, 0, 0);
  const dst = new OffscreenCanvas(Math.round(image.width * k), Math.round(image.height * k));
  const ctx = dst.getContext("2d")!;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(src, 0, 0, dst.width, dst.height);
  return ctx.getImageData(0, 0, dst.width, dst.height);
}

