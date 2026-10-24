// The active liveness capture: the front camera, mirrored, an oval guide and
// a ring of segments around it. First the face is centred; then turning the
// head round the circle lights each segment it points at; then the face
// looks straight again. The Rust session (docscan/src/face/liveness.rs) runs
// in the face worker on every frame it can take, and decides; this screen
// adds the browser's own capture-integrity signals (a virtual camera's name,
// frames that stop arriving or arrive out of order) and hands the outcome on.
//
// Outline state (src/outline.ts): grey while centring, green from the moment
// the face is centred (the session is now counting) through the sweep, done
// when the session finishes. Each lit segment is pushed to
// `window.__docscan.events` as `{ type: "segment", index }`.
//
// Processing (src/processing.ts, docs/capture-processing.md): the challenge
// itself is never shortened. Only when the session reaches `done`, every pose
// seen live, does `docscan:capture-ready` fire; the camera is then released
// and the processing view shows while the result and its checks are built. A
// session that fails (time limit) completes with its failing result and
// fires no capture-ready.
import type React from "react";
import { useEffect, useRef, useState } from "react";
import type { FaceClient } from "./face-client";
import type { Check, LivenessProgress, LivenessResult } from "./face-types";
import { type OutlineState, outlineState } from "./outline";
import { median } from "./outcome";
import { createProcessingSession } from "./processing";
import { ProcessingView } from "./ProcessingView";

/** Session presets: the full enrolment ring, and a quicker pass for returning users. */
export const LIVENESS_PRESETS = {
  full: { segments: 12, coverage: 1.0 },
  quick: { segments: 8, coverage: 1.0 },
} as const;

/** Camera names of virtual cameras and stream injectors (a heuristic, see face/RESEARCH.md). */
const VIRTUAL_CAMERA = /virtual|obs|manycam|snap camera|xsplit|droidcam|epoccam|camtwist|e2esoft|youcam|v4l2loopback|splitcam|fake|iriun|ndi/i;

export interface CaptureIntegrity {
  cameraLabel: string;
  virtualCamera: boolean;
  /** `?allowVirtualCamera=1` (the e2e suite's fake camera): recorded, not failed. */
  virtualAllowed: boolean;
  frameRate: number | null;
  /** Camera frames presented, and how many the session analysed. */
  presented: number;
  analysed: number;
  /** Longest time without a new camera frame, ms. */
  longestStallMs: number;
  /** Frames whose presentation counter or media time went backwards. */
  outOfOrder: number;
  check: Check;
}

export interface LivenessOutcome {
  result: LivenessResult;
  integrity: CaptureIntegrity;
  /** Pass or fail including the browser's capture-integrity check. */
  passed: boolean;
  bestFrameUrl: string | null;
  alignedUrl: string | null;
  captureMs: number;
  frames: number;
  msPerFrame: number | null;
  fps: number;
  memoryBytes: number;
}

type Docscan = { events: unknown[]; frames: unknown[] };
const docscan = () => (window as unknown as { __docscan: Docscan }).__docscan;

async function openFrontCamera(): Promise<MediaStream> {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) throw new Error("The camera needs https or localhost.");
  // The sensor's own 4:3 mode, uncropped. Asking for a portrait 720 × 960
  // frame made the browser crop the middle of the (landscape) sensor image,
  // which looked like a 2× zoom; `resizeMode: "none"` keeps native modes only,
  // so the field of view is the phone camera's own.
  const video = { facingMode: { ideal: "user" }, width: { ideal: 1280 }, height: { ideal: 960 }, resizeMode: "none" } as MediaTrackConstraints;
  return navigator.mediaDevices.getUserMedia({ audio: false, video });
}

const work = document.createElement("canvas");
const workCtx = work.getContext("2d", { willReadFrequently: true })!;

/** The whole camera frame, scaled to at most 480 px on its shorter side. */
function grabFrame(video: HTMLVideoElement): ImageData {
  const k = Math.min(1, 480 / Math.min(video.videoWidth, video.videoHeight));
  work.width = Math.round(video.videoWidth * k);
  work.height = Math.round(video.videoHeight * k);
  workCtx.drawImage(video, 0, 0, work.width, work.height);
  return workCtx.getImageData(0, 0, work.width, work.height);
}

/**
 * The oval's centre and half-width in the analysed frame, as fractions. The
 * preview is mirrored and letterboxed (`object-fit: contain`, the camera's
 * whole field of view, as its own app shows it): the offsets below come out
 * negative for the bars, which the same arithmetic handles.
 */
function guideFraction(video: HTMLVideoElement, guide: HTMLElement): [number, number, number] {
  const box = video.getBoundingClientRect();
  const g = guide.getBoundingClientRect();
  const scale = Math.min(box.width / video.videoWidth, box.height / video.videoHeight);
  const offX = (video.videoWidth * scale - box.width) / 2;
  const offY = (video.videoHeight * scale - box.height) / 2;
  const cxScreen = g.left + g.width / 2 - box.left;
  const cyScreen = g.top + g.height / 2 - box.top;
  // Mirrored: screen x maps to video x from the right.
  const cx = video.videoWidth - (cxScreen + offX) / scale;
  const cy = (cyScreen + offY) / scale;
  const r = g.width / 2 / scale;
  return [cx / video.videoWidth, cy / video.videoHeight, r / Math.min(video.videoWidth, video.videoHeight)];
}

function Ring({ segments, pointing }: { segments: boolean[]; pointing: number | null }) {
  const n = segments.length;
  const gap = 4;
  const arcs = segments.map((on, i) => {
    const a0 = ((i * 360) / n - 180 / n + gap / 2) * (Math.PI / 180);
    const a1 = (((i + 1) * 360) / n - 180 / n - gap / 2) * (Math.PI / 180);
    // Clockwise from the top: x = sin, y = -cos (an ellipse matching the oval).
    const p = (a: number, rx: number, ry: number) => `${50 + rx * Math.sin(a)} ${50 - ry * Math.cos(a)}`;
    const [rx, ry] = [47, 47];
    const d = `M ${p(a0, rx, ry)} A ${rx} ${ry} 0 0 1 ${p(a1, rx, ry)}`;
    return <path key={i} d={d} className={`seg ${on ? "on" : ""} ${pointing === i ? "pointing" : ""}`} data-segment={i} data-on={on} />;
  });
  return (
    <svg className="ring" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      {arcs}
    </svg>
  );
}

export function FaceLiveness({
  face,
  preset,
  label,
  stepNote,
  scanner = "liveness",
  onDone,
}: {
  face: FaceClient;
  preset: keyof typeof LIVENESS_PRESETS;
  label: string;
  stepNote?: string;
  /** The scanner id published in the processing events. */
  scanner?: string;
  onDone: (o: LivenessOutcome) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const guideRef = useRef<HTMLDivElement>(null);
  const [progress, setProgress] = useState<LivenessProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outlineUi, setOutlineUi] = useState<OutlineState>("grey");
  const [stats, setStats] = useState({ fps: 0, ms: 0 });
  const [processing, setProcessing] = useState(false);
  /** Bumped by "Try again": a fresh camera, session and challenge. */
  const [attempt, setAttempt] = useState(0);
  const n = LIVENESS_PRESETS[preset].segments;

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    let started = false;
    const session = createProcessingSession(scanner, "camera");
    setProcessing(false);
    setError(null);
    setProgress(null);
    const t0 = performance.now();
    const outline = outlineState(setOutlineUi);
    const lit = new Set<number>();
    const msList: number[] = [];
    let analysed = 0;
    let presented = 0;
    let lastPresented = -1;
    let lastMediaTime = -1;
    let lastFrameAt = 0;
    let longestStall = 0;
    let outOfOrder = 0;
    let memoryBytes = 0;
    let processing = false;
    let since = performance.now();
    let framesInSecond = 0;
    const allowVirtual = new URLSearchParams(location.search).get("allowVirtualCamera") === "1";
    let camLabel = "";
    let frameRate: number | null = null;

    function integrity(): CaptureIntegrity {
      const virtualCamera = VIRTUAL_CAMERA.test(camLabel);
      const ok = (!virtualCamera || allowVirtual) && outOfOrder === 0 && longestStall <= 1500;
      return {
        cameraLabel: camLabel,
        virtualCamera,
        virtualAllowed: allowVirtual,
        frameRate,
        presented,
        analysed,
        longestStallMs: Math.round(longestStall),
        outOfOrder,
        check: {
          name: "capture_integrity",
          passed: ok,
          required: true,
          score: ok ? 1 : 0,
          threshold: 1,
          detail: `camera "${camLabel || "unnamed"}"${virtualCamera ? (allowVirtual ? " (a virtual or test camera, allowed by ?allowVirtualCamera=1)" : " looks like a virtual camera") : ""}; ${presented} frames, longest stall ${Math.round(longestStall)} ms, ${outOfOrder} out of order`,
        },
      };
    }

    async function finish(completed: boolean) {
      stopped = true;
      // Every frame the session needed has been analysed: the camera is
      // released now, before the result is built.
      for (const t of stream?.getTracks() ?? []) t.stop();
      if (completed) {
        session.captured({ step: label, inputCount: analysed });
        docscan().events.push({ type: "capture_ready", operationId: session.id, frames: analysed, sinceStartMs: Math.round(performance.now() - t0) });
      }
      session.stage("result");
      setProcessing(true);
      let result: LivenessResult;
      try {
        ({ result } = await face.run<LivenessResult>({ kind: "liveness_result" }));
      } catch (e) {
        session.fail(e);
        setError(e instanceof Error ? e.message : String(e));
        return;
      }
      // Left while the result was built: nothing is handed on.
      if (!session.active()) return;
      const integ = integrity();
      const passed = result.passed && integ.check.passed;
      const { portraitUrl } = await import("./face-types");
      const outcome: LivenessOutcome = {
        result,
        integrity: integ,
        passed,
        bestFrameUrl: result.best_frame ? portraitUrl(result.best_frame) : null,
        alignedUrl: result.aligned ? portraitUrl(result.aligned) : null,
        captureMs: performance.now() - t0,
        frames: analysed,
        msPerFrame: median(msList),
        fps: analysed / Math.max(0.001, (performance.now() - t0) / 1000),
        memoryBytes,
      };
      outline.set("done");
      docscan().events.push({
        type: "liveness",
        passed,
        completed: result.completed,
        checks: [...result.checks, integ.check],
        segments: result.segments,
        durationMs: Math.round(result.duration_ms),
        sinceStartMs: Math.round(outcome.captureMs),
        frames: analysed,
        msPerFrame: outcome.msPerFrame,
        wasmMemoryMb: Math.round(memoryBytes / 1048576),
      });
      // The verdict, pass or fail, is the result: the operation completed.
      session.complete();
      window.dispatchEvent(
        new CustomEvent("docscan:liveness", {
          detail: { passed, result: { ...result, checks: [...result.checks, integ.check] }, integrity: integ, template: result.template, model: result.model, bestFrameUrl: outcome.bestFrameUrl },
        }),
      );
      onDone(outcome);
    }

    async function onFrame(now: number, meta: VideoFrameCallbackMetadata) {
      const video = videoRef.current;
      const guide = guideRef.current;
      if (stopped || !video || !guide) return;
      // Capture integrity: frames keep coming, in order.
      presented++;
      if (meta.presentedFrames <= lastPresented || meta.mediaTime < lastMediaTime) outOfOrder++;
      lastPresented = meta.presentedFrames;
      lastMediaTime = meta.mediaTime;
      if (lastFrameAt) longestStall = Math.max(longestStall, now - lastFrameAt);
      lastFrameAt = now;
      // Keep counting camera frames while this one is analysed.
      video.requestVideoFrameCallback(onFrame);
      if (!face.busy && !processing) {
        processing = true;
        if (!started) {
          started = true;
          const guideFrac = guideFraction(video, guide);
          // `?timeout=<s>` shortens the session's time limit (the e2e attack cases).
          const timeout = Number(new URLSearchParams(location.search).get("timeout"));
          await face.run({ kind: "liveness_start", config: { ...LIVENESS_PRESETS[preset], mirrored: true, guide: guideFrac, ...(timeout > 0 ? { max_ms: timeout * 1000 } : {}) } });
        }
        const image = grabFrame(video);
        try {
          const r = await face.run<LivenessProgress>({ kind: "liveness_frame", image, ts: now });
          if (stopped) return;
          analysed++;
          framesInSecond++;
          msList.push(r.ms);
          memoryBytes = r.memoryBytes;
          const p = r.result;
          docscan().frames.push({ ms: Math.round(r.ms), phase: p.phase, found: p.found, coverage: p.coverage, size: [image.width, image.height] });
          setProgress(p);
          p.segments.forEach((on, i) => {
            if (on && !lit.has(i)) {
              lit.add(i);
              docscan().events.push({ type: "segment", index: i, sinceStartMs: Math.round(performance.now() - t0) });
            }
          });
          if (p.phase === "sweep" || p.phase === "finish") outline.set("green");
          if (performance.now() - since > 1000) {
            const fps = Math.round((framesInSecond * 1000) / (performance.now() - since));
            setStats({ fps, ms: Math.round(r.ms) });
            since = performance.now();
            framesInSecond = 0;
          }
          if (p.phase === "done" || p.phase === "failed") {
            await finish(p.phase === "done");
            return;
          }
        } catch (e) {
          // Building the result failed: the operation ends failed.
          if (stopped) session.fail(e);
          setError(String(e));
        }
        processing = false;
      }
    }

    openFrontCamera()
      .then((s) => {
        stream = s;
        if (stopped) {
          for (const t of s.getTracks()) t.stop();
          return;
        }
        const [track] = s.getVideoTracks();
        camLabel = track?.label ?? "";
        frameRate = (track?.getSettings().frameRate as number | undefined) ?? null;
        const video = videoRef.current!;
        video.srcObject = s;
        void video.play();
        video.requestVideoFrameCallback(onFrame);
      })
      .catch((e) => {
        session.fail(e);
        if (!stopped) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      stopped = true;
      for (const t of stream?.getTracks() ?? []) t.stop();
      session.cancel();
    };
  }, [face, preset, label, scanner, onDone, attempt]);

  if (processing && error) {
    return (
      <main className="processing-panel" data-testid="capture-error" role="alert">
        <h1>{label}</h1>
        <p>The liveness result could not be built: {error}</p>
        <button type="button" className="primary" data-testid="capture-again" onClick={() => setAttempt((a) => a + 1)}>Try again</button>
      </main>
    );
  }
  if (processing) return <ProcessingView title={label} stage="Checking liveness…" />;

  const segments = progress?.segments ?? Array.from({ length: n }, () => false);
  const phaseLabel = !progress ? "Starting the camera…" : progress.phase === "centre" ? "Centre your face" : progress.phase === "sweep" ? "Turn your head round the circle" : progress.phase === "finish" ? "Look straight ahead" : "Done";
  return (
    <div className="capture face-capture">
      <div className="viewport">
        <video ref={videoRef} playsInline muted className="mirrored whole" />
        <div className="face-mask" />
        <div ref={guideRef} className={`face-guide ${outlineUi !== "grey" ? "guide-found" : ""}`} data-testid="face-guide" style={{ "--n": String(n) } as React.CSSProperties}>
          <Ring segments={segments} pointing={progress?.pointing ?? null} />
        </div>
        <div className="step-label" data-testid="step">
          {label}
          {stepNote ? <span className="step-count"> {stepNote}</span> : null}
          <div className="muted face-phase">{phaseLabel}</div>
        </div>
        <div className="capture-foot">
          <div className="hint" data-testid="hint">
            {error ?? (progress?.hint || "Show your face in the oval")}
          </div>
          <div className="stats" data-testid="face-stats">
            {stats.fps} frames/s · {stats.ms} ms · ring {Math.round((progress?.coverage ?? 0) * 100)}% · yaw {progress?.pose.yaw.toFixed(0) ?? "–"}° pitch{" "}
            {progress?.pose.pitch.toFixed(0) ?? "–"}°
          </div>
        </div>
      </div>
    </div>
  );
}
