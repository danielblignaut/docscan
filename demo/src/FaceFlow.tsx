// The three face flows, each ending on the results screen:
//
// - liveness (`?mode=liveness`): the full ring; the result can then be
//   enrolled for Face ID (demo storage in this browser);
// - faceid (`?mode=faceid`): a quicker ring, then the template matched
//   against the enrolled ones;
// - facedoc (`?mode=facedoc`): a quicker ring, then an identity document's
//   photo page captured with the rear camera (the document scanner's own
//   hands-free capture), the face found on it, and the two compared.
import { useCallback, useEffect, useRef, useState } from "react";
import type { FaceClient } from "./face-client";
import { readDocumentFace } from "./face-document";
import { DOC_THRESHOLD, RECOGNISER } from "./face-models";
import { type Enrolment, listEnrolments } from "./face-store";
import { documentMatch, matchEnrolments, type PhotoFace, portraitUrl, verificationPassed } from "./face-types";
import { FaceLiveness, type LivenessOutcome } from "./FaceLiveness";
import { type Captured, IdCapture } from "./IdCapture";
import type { CaptureMeta, Outcome } from "./outcome";
import type { ScannerClient } from "./scanner-client";

export type { FaceMatch } from "./face-types";

export type FaceFlowId = "liveness" | "faceid" | "facedoc";

export interface DocumentFace {
  copy_assessment: import("./types").CopyAssessment;
  imageUrl: string;
  kind: string;
  face: PhotoFace;
  alignedUrl: string | null;
}

type Docscan = { events: unknown[] };
const docscan = () => (window as unknown as { __docscan: Docscan }).__docscan;

/** Pixels of an image URL (the captured, flattened document). */
export async function imagePixels(url: string, maxSide = 1600): Promise<ImageData> {
  const blob = await (await fetch(url)).blob();
  const bmp = await createImageBitmap(blob);
  const k = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const c = new OffscreenCanvas(Math.round(bmp.width * k), Math.round(bmp.height * k));
  const ctx = c.getContext("2d")!;
  ctx.drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close();
  return ctx.getImageData(0, 0, c.width, c.height);
}

export function FaceFlow({ flow, face, scanner, onDone }: { flow: FaceFlowId; face: FaceClient; scanner: ScannerClient; onDone: (o: Outcome) => void }) {
  const [step, setStep] = useState<"live" | "document" | "reading">("live");
  const [readError, setReadError] = useState<string | null>(null);
  const captureSession = useRef<AbortController | null>(null);
  const [live, setLive] = useState<LivenessOutcome | null>(null);
  const [threshold, setThreshold] = useState<number | null>(null);
  const [enrolments, setEnrolments] = useState<Enrolment[] | null>(null);
  const [status, setStatus] = useState<string | null>("Loading the face models…");
  // Read by the liveness callback without re-creating it (which would restart the camera).
  const enrolRef = useRef<Enrolment[]>([]);
  const thresholdRef = useRef(0.5);
  const t0 = useState(() => performance.now())[0];

  useEffect(() => {
    let alive = true;
    const session = new AbortController();
    captureSession.current = session;
    setStatus("Loading the face models…");
    face.onProgress = (p) => {
      if (alive && !p.cached && p.total) setStatus(`Downloading ${p.file}: ${Math.round((100 * p.loaded) / p.total)}%`);
    };
    face.ready
      .then((r) => {
        if (!alive) return;
        thresholdRef.current = r.threshold;
        setThreshold(r.threshold);
        setStatus(null);
      })
      .catch((e) => alive && setStatus(`Face models failed: ${e}`));
    if (flow === "faceid")
      void listEnrolments().then(
        (e) => {
          if (!alive) return;
          enrolRef.current = e;
          setEnrolments(e);
        },
        () => alive && setEnrolments([]),
      );
    return () => {
      alive = false;
      session.abort();
    };
  }, [face, flow]);

  const meta = useCallback(
    (o: LivenessOutcome): CaptureMeta => ({ source: "camera", captureMs: performance.now() - t0, frames: o.frames, fastMs: o.msPerFrame }),
    [t0],
  );

  const onLive = useCallback(
    (o: LivenessOutcome) => {
      if (captureSession.current?.signal.aborted !== false) return;
      setLive(o);
      if (flow === "liveness") {
        window.dispatchEvent(new CustomEvent("docscan:complete", { detail: { liveness: o.result, passed: o.passed } }));
        onDone({ kind: "face", flow, liveness: o, meta: meta(o) });
      } else if (flow === "faceid") {
        const match = o.passed ? matchEnrolments(o.result.template, o.result.model, enrolRef.current, thresholdRef.current) : null;
        docscan().events.push({ type: "faceid", match });
        window.dispatchEvent(new CustomEvent("docscan:complete", { detail: { liveness: o.result, passed: verificationPassed(o.passed, match), match } }));
        onDone({ kind: "face", flow, liveness: o, match, meta: meta(o) });
      } else setStep("document");
    },
    [flow, onDone, meta],
  );

  const onDocument = useCallback(
    async (captured: Captured[], _m: CaptureMeta) => {
      const signal = captureSession.current?.signal;
      if (!live || !signal || signal.aborted) return;
      setReadError(null);
      setStep("reading");
      const c = captured[0];
      try {
        if (!c) throw new Error("No document was captured. Please try again.");
        const result = await readDocumentFace(c.imageUrl, imagePixels, async (image) => (await face.run<PhotoFace>({ kind: "photo", image })).result, signal);
        if (!result || signal.aborted) { URL.revokeObjectURL(c.imageUrl); return; }
        const doc: DocumentFace = { copy_assessment: c.result.copy_assessment, imageUrl: c.imageUrl, kind: c.result.kind, face: result, alignedUrl: result.found ? portraitUrl({ width: 112, height: 112, rgba: result.aligned }) : null };
        const match = live.passed ? documentMatch(live.result.template, live.result.model, result, DOC_THRESHOLD) : null;
        docscan().events.push({ type: "facedoc", found: result.found, match });
        window.dispatchEvent(new CustomEvent("docscan:complete", { detail: { liveness: live.result, passed: verificationPassed(live.passed, match), document: { copy_assessment: c.result.copy_assessment, kind: c.result.kind, found: result.found, quality: result.quality }, match } }));
        onDone({ kind: "face", flow, liveness: live, match, document: doc, meta: meta(live) });
      } catch (error) {
        if (c) URL.revokeObjectURL(c.imageUrl);
        if (!signal.aborted) setReadError(error instanceof Error ? error.message : String(error));
      }
    },
    [live, face, flow, onDone, meta],
  );

  if (status && threshold === null) {
    return (
      <div className="capture face-capture">
        <div className="capture-foot">
          <div className="hint" data-testid="hint">
            {status}
          </div>
        </div>
      </div>
    );
  }
  if (flow === "faceid" && enrolments !== null && enrolments.length === 0) {
    return (
      <div className="capture face-capture">
        <div className="face-empty" data-testid="faceid-empty">
          <h2>No face enrolled on this device</h2>
          <p>Run Face liveness first, then use Enrol on its results.</p>
        </div>
      </div>
    );
  }
  if (flow === "faceid" && enrolments === null) return null;
  if (step === "live") {
    const label = flow === "liveness" ? "Face liveness" : flow === "faceid" ? "Face ID" : "Face vs ID document";
    return <FaceLiveness face={face} preset={flow === "liveness" ? "full" : "quick"} label={label} stepNote={flow === "facedoc" ? "1 of 2" : undefined} onDone={onLive} />;
  }
  if (step === "document") return <IdCapture client={scanner} docType="photo_page" emitEvents={false} onDone={onDocument} />;
  return (
    <div className="capture face-capture">
      <div className="capture-foot">
        <div className="hint" data-testid="face-document-hint">{readError ?? "Finding the face on the document…"}</div>
        {readError && <button type="button" onClick={() => { setReadError(null); setStep("document"); }}>Capture document again</button>}
      </div>
    </div>
  );
}

export const RECOGNISER_NAME = RECOGNISER.name;
