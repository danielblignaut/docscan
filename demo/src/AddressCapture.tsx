// Proof of address (?mode=address): hands-free capture of a bill, statement
// or lease, then the holder's name and address, the date and the issuer read
// from it on the device, each checked against the page.
//
// Like IdCapture: every frame is analysed (here only the page outline and its
// quality, docscan's `page`); once two consecutive frames show a whole,
// sharp page in the same place, the full-resolution frame is flattened, the
// camera is released, and the page is read (`address`: OCR, the trained
// tagger or the rules, then the checks).
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { cropToScreen, grab, grabFull, guideInVideo, openCamera, toJpeg } from "./camera";
import { chooseExtractor } from "./models";
import type { ScannerClient } from "./scanner-client";
import type { AddressResult, PageAnalysis } from "./types";

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

export interface AddressCaptured {
  result: AddressResult;
  imageUrl: string;
  blob: Blob;
  captureMs: number;
  readMs: number;
}

type Docscan = { events: unknown[]; frames: unknown[] };
const docscan = () => (window as unknown as { __docscan: Docscan }).__docscan;

/** The device's date as YYYY-MM-DD, for the document's age. `?today=` overrides (tests). */
export function today(): string {
  const asked = new URLSearchParams(location.search).get("today");
  if (asked) return asked;
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

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

export function AddressCapture({ client, onDone }: { client: ScannerClient; onDone: (c: AddressCaptured) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const [last, setLast] = useState<PageAnalysis | null>(null);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fps, setFps] = useState(0);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    let previous: PageAnalysis | null = null;
    let repeats = 0;
    let frames = 0;
    let since = performance.now();
    const t0 = performance.now();
    const release = () => {
      for (const t of stream?.getTracks() ?? []) t.stop();
    };

    async function capture(video: HTMLVideoElement, rect: ReturnType<typeof guideInVideo>, analysedWidth: number, page: PageAnalysis) {
      stopped = true;
      const captureMs = performance.now() - t0;
      setStage("Flattening the page…");
      const full = grabFull(video, rect);
      // The camera is no longer needed: release it before the slow part.
      release();
      const k = full.width / analysedWidth;
      const corners = page.outline!.corners.flatMap(([x, y]) => [x * k, y * k]);
      const [pw, ph] = page.size!;
      const scale = Math.min(k, FLAT_MAX_LONG / Math.max(pw, ph));
      const [w, h] = [Math.round(pw * scale), Math.round(ph * scale)];
      const flat = await client.run<ImageData>({ kind: "flatten", image: full, corners, width: w, height: h });
      // A smaller colour copy to keep and show (before the page is handed to the worker).
      const blob = await toJpeg(downscale(flat.result, COLOUR_LONG));
      const imageUrl = URL.createObjectURL(blob);
      window.dispatchEvent(new CustomEvent("docscan:captured", { detail: { step: "proof of address", imageUrl, blob, page } }));
      docscan().events.push({ type: "page_captured", sinceStartMs: Math.round(captureMs), page });

      setStage("Reading the page (OCR)…");
      const tRead = performance.now();
      const method = chooseExtractor((await client.ready).tagger);
      const { result, memoryBytes } = await client.run<AddressResult>({ kind: "address", image: flat.result, today: today(), method });
      const readMs = performance.now() - tRead;
      const entry: AddressCaptured = { result, imageUrl, blob, captureMs, readMs };
      docscan().events.push({ type: "captured", kind: "proof_of_address", stepMs: Math.round(captureMs), sinceStartMs: Math.round(performance.now() - t0), readMs: Math.round(readMs), wasmMemoryMb: Math.round(memoryBytes / 2 ** 20), result });
      // For a host page: the whole reading, then completion (the camera is already off).
      window.dispatchEvent(new CustomEvent("docscan:address", { detail: entry }));
      window.dispatchEvent(new CustomEvent("docscan:complete", { detail: { captured: [entry] } }));
      onDone(entry);
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
      try {
        const { result, ms } = await client.run<PageAnalysis>({ kind: "page", image });
        if (stopped) return;
        docscan().frames.push({ ms, size: [image.width, image.height], accepted: result.accepted, reasons: result.reasons, shape: result.shape, quality: result.quality });
        frames++;
        const now = performance.now();
        if (now - since > 1000) {
          setFps(Math.round((frames * 1000) / (now - since)));
          frames = 0;
          since = now;
        }
        setLast(result);
        drawOutline(overlayRef.current, video, rect, image.width, result);
        if (result.accepted && previous?.accepted && similar(result, previous)) repeats++;
        else repeats = result.accepted ? 1 : 0;
        previous = result;
        if (repeats >= STABLE_READS) {
          await capture(video, rect, image.width, result);
          return;
        }
      } catch (e) {
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
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          void videoRef.current.play();
        }
        requestAnimationFrame(loop);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    return () => {
      stopped = true;
      release();
    };
  }, [client, onDone]);

  return (
    <div className="capture">
      <div className="viewport">
        <video ref={videoRef} playsInline muted />
        <canvas ref={overlayRef} className="overlay outline" />
        <div ref={guideRef} className={`guide ${last?.accepted ? "guide-found" : ""}`} style={{ "--aspect": String(A4) } as React.CSSProperties} />
        <div className="step-label">Proof of address — a bill, statement or lease</div>
        <div className="hint" data-testid="hint">
          {error ?? stage ?? hint(last)}
        </div>
      </div>
      <div className="stats">
        {fps} analyses/s · sharp {last?.quality.sharpness.toFixed(0)} · glare {((last?.quality.glare ?? 0) * 100).toFixed(1)}% · {last?.shape ?? "no page"}
        {last?.size ? ` ${last.size[0]}×${last.size[1]}` : ""}
      </div>
    </div>
  );
}

/** An image scaled so its long side is at most `long`. */
function downscale(image: ImageData, long: number): ImageData {
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

function drawOutline(canvas: HTMLCanvasElement | null, video: HTMLVideoElement, rect: ReturnType<typeof guideInVideo>, analysedWidth: number, p: PageAnalysis) {
  if (!canvas) return;
  const box = video.getBoundingClientRect();
  canvas.width = box.width * devicePixelRatio;
  canvas.height = box.height * devicePixelRatio;
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  if (!p.outline) return;
  const pts = p.outline.corners.map((c) => cropToScreen(video, rect, analysedWidth, c));
  ctx.strokeStyle = p.accepted ? "#22c55e" : "#facc15";
  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.beginPath();
  pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
  ctx.stroke();
}

const LABELS: [string, string][] = [
  ["holder_name", "Holder"],
  ["street", "Street"],
  ["suburb", "Suburb"],
  ["city", "City"],
  ["province", "Province"],
  ["postal_code", "Postal code"],
  ["document_date", "Document date"],
  ["period_from", "Period from"],
  ["period_to", "Period to"],
  ["issuer", "Issuer"],
  ["account_number", "Account number"],
];

/** The fields, each with whether it was found printed on the page; the age; the OCR text. */
export function AddressView({ captured }: { captured: AddressCaptured }) {
  const r = captured.result;
  const f = r.fields;
  const values: Record<string, string | null> = {
    holder_name: f.holder_name,
    street: f.address.street,
    suburb: f.address.suburb,
    city: f.address.city,
    province: f.address.province,
    postal_code: f.address.postal_code,
    document_date: f.document_date,
    period_from: f.statement_period?.from ?? null,
    period_to: f.statement_period?.to ?? null,
    issuer: f.issuer,
    account_number: f.account_number,
  };
  const check = (k: string) => r.verification.fields.find((c) => c.field === k);
  const age = r.verification.age;
  return (
    <section className="done" data-testid="address">
      <p className={r.verification.accepted ? "check ok" : "check mismatch"} data-testid="address-verdict">
        {r.verification.accepted ? "Accepted as proof of address" : `Not accepted: ${r.verification.reasons.join("; ")}`}
      </p>
      <img src={captured.imageUrl} alt="captured page" />
      <dl className="fields">
        {LABELS.map(([k, label]) => {
          const v = values[k];
          const c = check(k);
          let status = "—";
          if (v && k === "province" && f.province_inferred) status = "inferred from the postal code";
          else if (v && c) status = c.found ? "✓ on the page" : `✗ not found on the page (${Math.round(c.match_score * 100)}%)`;
          return (
            <div key={k} data-field={k}>
              <dt>{label}</dt>
              <dd>
                {v ?? <small>not found</small>} {v ? <small data-status={c?.found ? "found" : "missing"}>{status}</small> : null}
              </dd>
            </div>
          );
        })}
        <div>
          <dt>Document type</dt>
          <dd>{f.document_type.replaceAll("_", " ")}</dd>
        </div>
        <div>
          <dt>Postal code ↔ province</dt>
          <dd>{r.verification.postal_code}</dd>
        </div>
        <div>
          <dt>Age</dt>
          <dd data-testid="age">
            {age ? `${age.age_days} days (${age.recent ? "within three months" : age.future ? "dated in the future" : "older than three months"})` : "no date"}
          </dd>
        </div>
      </dl>
      <p className="stats">
        Read by the {r.method === "tagger" ? "trained tagger" : "rules"} · {r.words} words · OCR {Math.round(r.timings_ms.ocr)} ms · extract{" "}
        {Math.round(r.timings_ms.extract)} ms · captured after {(captured.captureMs / 1000).toFixed(1)} s
      </p>
      <details>
        <summary>Page text (OCR)</summary>
        <pre>{r.text}</pre>
      </details>
    </section>
  );
}
