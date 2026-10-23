// Shared hands-free page capture. Releases the camera before OCR starts.
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { cropToScreen, grab, grabFull, guideInVideo, openCamera, snapshot, toJpeg } from "./camera";
import { drawPolygon, OUTLINE_COLOUR, type OutlineState, outlineState } from "./outline";
import { type CaptureMeta, median } from "./outcome";
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

export function PageCapture({ client, title, onRead }: {
  client: ScannerClient;
  title: string;
  onRead: (page: CapturedPage, meta: CaptureMeta, active: () => boolean) => Promise<void>;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const [last, setLast] = useState<PageAnalysis | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fps, setFps] = useState(0);
  const [outlineUi, setOutlineUi] = useState<OutlineState>("grey");

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    let mounted = true;
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
      setStage("Flattening the page…");
      const full = grabFull(frame, rect);
      // The camera is no longer needed: release it before the slow part.
      release();
      const { flat, blob, imageUrl } = await flattenPage(client, full, full.width / analysedWidth, page);
      if (!mounted) { URL.revokeObjectURL(imageUrl); return; }
      window.dispatchEvent(new CustomEvent("docscan:captured", { detail: { step: title.toLowerCase(), imageUrl, blob, page } }));
      docscan().events.push({ type: "page_captured", sinceStartMs: Math.round(captureMs), page });

      setStage("Reading the page (OCR)…");
      await onRead({ flat, imageUrl, blob, captureMs }, { source: "camera", captureMs, frames: pageMs.length, fastMs: median(pageMs) }, () => mounted);
      if (mounted) outline.set("done");
    }

    async function loop() {
      const video = videoRef.current;
      const guide = guideRef.current;
      if (stopped) return;
      if (!video || !guide || video.readyState < 2 || client.busy) {
        requestAnimationFrame(loop);
        return;
      }
      // A generous margin round the guide: a page is large, and held a little
      // low or high it should still be found whole.
      const rect = guideInVideo(video, guide, GUIDE_MARGIN);
      const image = grab(video, rect);
      snapshot(video, frame);
      try {
        const { result, ms } = await client.run<PageAnalysis>({ kind: "page", image });
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
      .catch((e) => { if (mounted) setError(e instanceof Error ? e.message : String(e)); });
    return () => {
      mounted = false;
      stopped = true;
      release();
    };
  }, [client, title, onRead]);

  return (
    <div className="capture">
      <div className="viewport">
        <video ref={videoRef} playsInline muted />
        <canvas ref={overlayRef} className="overlay outline" />
        <div ref={guideRef} className={`guide ${outlineUi !== "grey" ? "guide-found" : ""}`} style={{ "--aspect": String(A4) } as React.CSSProperties} />
        <div className="step-label" data-testid="step">{title}</div>
        <div className="capture-foot">
          <div className={`hint ${stage ? "hint-busy" : ""}`} data-testid="hint">
            {error ?? stage ?? hint(last)}
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

