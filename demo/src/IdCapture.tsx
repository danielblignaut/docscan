// Hands-free identity document capture, in two halves (docs/capture-processing.md):
//
// - acquisition, while the camera is live: model-free fast passes (no OCR) on
//   `captureClient` find a sharp, whole, steady document and keep a short
//   burst of separate camera frames; a barcode-only reading (the smart ID
//   back) is confirmed here, from two separate frames, as it always was;
// - validation, after `docscan:capture-ready`: each kept frame is read with
//   OCR on `client`, and the step is accepted only by the same rule the live
//   loop used, two identical accepted readings from different frames. A burst
//   that never agrees asks for that step to be captured again; nothing is
//   completed on geometry alone.
//
// A later step's acquisition runs while an earlier step validates (turn the
// card over while the front is read); the camera is released once every step
// is acquired, and the processing view stays until every step is accepted.
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { cropToScreen, grab, grabFull, guideInVideo, openCamera, snapshot, toJpeg } from "./camera";
import { drawPolygon, OUTLINE_COLOUR, type OutlineState, outlineState } from "./outline";
import { type CaptureMeta, median } from "./outcome";
import { createProcessingSession, type ProcessingSession } from "./processing";
import { ProcessingView } from "./ProcessingView";
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
export const STABLE_READS = 2;
export const STABLE_WINDOW_MS = 12000;
/**
 * Separate camera frames kept for an OCR step: one more than the readings
 * needed, so one misread frame does not cost a recapture.
 */
export const BURST_FRAMES = 3;
/** A burst is a steady hold: every kept frame within this long of the first. */
export const BURST_WINDOW_MS = 2000;
/** Consecutive kept frames' corners within this fraction of the analysed crop. */
export const BURST_TOLERANCE = 0.04;
/**
 * After a futile burst (OCR named a document this step cannot accept from
 * print), the same hold is not burst again for this long: a document within
 * `HELD_TOLERANCE` of where it was is the same document, read the same way.
 * Moving it (closer, or another document) starts a burst at once.
 */
export const FUTILE_HOLD_MS = 10000;
export const HELD_TOLERANCE = 0.1;

/** The run of identical readings so far (the live loop's rule, unchanged). */
export interface ReadingRun {
  key: string | null;
  at: number;
  repeats: number;
}
export const NO_RUN: ReadingRun = { key: null, at: 0, repeats: 0 };

/**
 * One frame's reading folded into the run: the same key again counts, a
 * different one starts over, no key changes nothing until the window lapses.
 * `outline` is the colour change the frame causes, if any.
 */
export function nextRun(run: ReadingRun, key: string | null, at: number): { run: ReadingRun; outline: "green" | "different reading" | "no reading for too long" | null } {
  const live = run.key !== null && at - run.at < STABLE_WINDOW_MS;
  if (key) {
    const sameRun = live && key === run.key;
    return { run: { key, at, repeats: sameRun ? run.repeats + 1 : 1 }, outline: sameRun || !live ? "green" : "different reading" };
  }
  if (run.key !== null && !live) return { run: NO_RUN, outline: "no reading for too long" };
  return { run, outline: null };
}

/** A complete reading of a document this step accepts, or null: unknown kinds and outlines alone never count. */
export function frameKey(step: Pick<Step, "accepts">, result: DocumentResult, fallback: boolean): string | null {
  const readable = step.accepts.includes(result.kind) && result.document !== null;
  if (!readable) return null;
  return fallback ? `back39:${result.id_barcode!.value}` : readingKey(result);
}

/** After `fallbackAfterMs` on the step, a smart ID back whose PDF417 will not read settles for its Code 39. */
export function fallbackAllowed(step: Pick<Step, "fallbackAfterMs">, result: DocumentResult, onStepMs: number): boolean {
  return step.fallbackAfterMs !== undefined && onStepMs > step.fallbackAfterMs && result.kind === "za_smart_id_back" && !result.smart_id_barcode && result.id_barcode !== null;
}

/**
 * A fast-pass frame worth keeping for OCR: the old live loop's test for
 * spending an OCR pass (sharp, the whole document in view), on a step that
 * reads print, of a document the fast pass could not name or named as one
 * this step reads from print. A smart ID back (its PDF417, or its Code 39 on
 * a card-shaped outline) is never kept for OCR: OCR cannot recover its
 * barcodes, so it is read from them on the fast pass, the Code 39 fallback
 * included. Nor is a document this step does not accept (the wrong side).
 */
export function ocrCandidate(step: Pick<Step, "ocr" | "accepts">, fast: DocumentResult): boolean {
  const q = fast.quality;
  const named = fast.kind !== "unknown";
  if (fast.smart_id_barcode || fast.kind === "za_smart_id_back" || (named && !step.accepts.includes(fast.kind))) return false;
  return step.ocr && q.sharpness >= SHARPNESS_MIN && q.edge_density >= 0.01 && fast.document !== null;
}

/**
 * Time on each step since it was first shown. A recapture, or a detour to
 * recapture an earlier step, does not restart it, so the Code 39 fallback
 * deadline (`fallbackAfterMs`) is still reached on a step shown again.
 */
export function stepClock(count: number) {
  const first: (number | undefined)[] = Array.from({ length: count }, () => undefined);
  return {
    show(i: number, now: number) { first[i] ??= now; },
    elapsed: (i: number, now: number) => now - (first[i] ?? now),
  };
}

/** Where each step stands: still to acquire, acquired and being read, or accepted. */
export type SlotStatus = "needed" | "validating" | "done";

/**
 * What the screen does next, from the steps' statuses alone (never from
 * whether a camera stream happens to be open at that moment): the camera on
 * the earliest step still needed, else the processing view while any step is
 * read, else finished.
 */
export function plan(statuses: SlotStatus[]): { view: "camera"; step: number } | { view: "processing" } | { view: "finished" } {
  const step = statuses.indexOf("needed");
  if (step >= 0) return { view: "camera", step };
  return statuses.includes("validating") ? { view: "processing" } : { view: "finished" };
}

/**
 * The camera, by intent. `want()` opens it unless it is open or opening;
 * `drop()` releases it, and a stream that arrives after it was dropped (or
 * superseded by a later opening) is stopped at once and never handed on.
 * `live(generation)` tells a frame loop whether it still belongs to the open
 * camera, so a loop from an earlier opening ends.
 */
export function cameraGate(
  open: () => Promise<MediaStream>,
  onOpen: (stream: MediaStream, generation: number) => void,
  onError: (error: unknown) => void,
) {
  let generation = 0;
  let wanted = false;
  let stream: MediaStream | null = null;
  const stop = (s: MediaStream | null) => { for (const t of s?.getTracks() ?? []) t.stop(); };
  return {
    get wanted() { return wanted; },
    get stream() { return stream; },
    live: (g: number) => wanted && g === generation && stream !== null,
    want() {
      if (wanted) return;
      wanted = true;
      const mine = ++generation;
      open().then(
        (s) => {
          if (mine !== generation) return stop(s);
          stream = s;
          onOpen(s, mine);
        },
        (e) => {
          if (mine !== generation) return;
          wanted = false;
          onError(e);
        },
      );
    },
    drop() {
      wanted = false;
      generation++;
      stop(stream);
      stream = null;
    },
  };
}

/** A request abandoned because the screen went away: a cancel, never a failed reading. */
export function isAbort(e: unknown): boolean {
  return e instanceof Error && e.name === "AbortError";
}

/** The same document outline, held steady: every corner within `tolerance` of the crop's long side. */
export function sameOutline(a: [number, number][], b: [number, number][], size: [number, number], tolerance = BURST_TOLERANCE): boolean {
  const tol = tolerance * Math.max(...size);
  return a.length === b.length && a.every(([x, y], i) => Math.hypot(x - b[i][0], y - b[i][1]) < tol);
}

/**
 * An OCR reading that says more OCR of this hold cannot be accepted: a
 * document this step does not accept (the wrong side), or a smart ID back
 * whose PDF417 did not read (a back is read from its barcodes, which OCR
 * cannot recover). It is never accepted; it only ends the burst early and
 * says what to tell the holder.
 */
export function futileReading(step: Pick<Step, "accepts">, result: DocumentResult): boolean {
  if (result.kind === "unknown") return false;
  if (!step.accepts.includes(result.kind)) return true;
  return result.kind === "za_smart_id_back" && !result.smart_id_barcode;
}

export type BurstOutcome =
  | { confirmed: true; index: number; result: DocumentResult }
  /** `guide`: the reading that best explains the failure (the futile one, else the last that named a kind, else the last). */
  | { confirmed: false; cancelled: boolean; futile: boolean; guide: DocumentResult | null };

/**
 * The kept frames' OCR results, in capture order, folded by `nextRun`: the
 * index of the frame that confirms the reading, or why none did. A camera
 * frame kept twice (same `frame` id) is read once: a second read of one frame
 * is not independent. `read` is called lazily, frame by frame, and stops early
 * once the reading is confirmed, can no longer be, or is futile; `read`
 * answering null means the work was abandoned.
 */
export async function confirmBurst<F extends { at: number; frame: number }>(
  step: Pick<Step, "accepts">,
  kept: F[],
  read: (frame: F) => Promise<DocumentResult | null>,
): Promise<BurstOutcome> {
  const ids = new Set<number>();
  const frames = kept.filter((k) => !ids.has(k.frame) && ids.add(k.frame));
  let run = NO_RUN;
  let guide: DocumentResult | null = null;
  const failed = (futile: boolean, cancelled = false): BurstOutcome => ({ confirmed: false, cancelled, futile, guide });
  for (let i = 0; i < frames.length; i++) {
    const result = await read(frames[i]);
    if (!result) return failed(false, true);
    if (!guide || result.kind !== "unknown" || guide.kind === "unknown") guide = result;
    if (futileReading(step, result)) return failed(true);
    run = nextRun(run, frameKey(step, result, false), frames[i].at).run;
    if (run.key && run.repeats >= STABLE_READS) return { confirmed: true, index: kept.indexOf(frames[i]), result };
    const remaining = frames.length - i - 1;
    if ((run.key ? run.repeats : 0) + remaining < STABLE_READS) return failed(false);
  }
  return failed(false);
}

/** What a failed reading should tell the holder, or null when it says nothing beyond "reading". */
export function guidance(step: Step, result: DocumentResult | null): string | null {
  const text = hint(result, step);
  return /^(Starting|Reading)…$|^Reading… hold steady$/.test(text) ? null : text;
}

export interface Captured {
  input?: import("./document-review").InputReference;
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

/** A separate camera frame kept for validation: the analysed crop (for OCR) and the full-resolution crop (for the saved image). */
interface Kept {
  at: number;
  /** The camera frame (presented-frame count): separate frames have separate ids. */
  frame: number;
  image: ImageData;
  /** The analysed crop's size, which the outline's corners are in. */
  size: [number, number];
  full: ImageData;
  fast: DocumentResult;
}

/** What acquisition hands to validation for one step. */
interface Acquired {
  /** Confirmed from barcodes on the fast pass: the result and the frame it was read in. */
  confirmed: { result: DocumentResult; frame: Kept; fallback: boolean } | null;
  /** Otherwise the burst to read with OCR. */
  burst: Kept[];
  stepMs: number;
  frames: number;
}

interface Slot {
  status: "needed" | "validating" | "done";
  session: ProcessingSession | null;
  entry: Captured | null;
  blob: Blob | null;
}

/** The live hint, unless it only says "reading": then a failed reading's advice (a live problem, too dark or the wrong side, still wins). */
export function shownHint(step: Step, last: DocumentResult | null, advice: string | null): string {
  return advice && !guidance(step, last) ? advice : hint(last, step);
}

export function IdCapture({
  client,
  captureClient,
  docType,
  scanner = docType,
  emitEvents = true,
  onDone,
}: {
  /** Reads the kept frames (OCR) and flattens the saved image. */
  client: ScannerClient;
  /** Analyses the live frames (`document`, no OCR); a model-free worker answers at once. Defaults to `client`. */
  captureClient?: ScannerClient;
  docType: DocType;
  /** The scanner id published in the processing events. */
  scanner?: string;
  /** Nested verification flows publish their own completion event. */
  emitEvents?: boolean;
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
  const [processing, setProcessing] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [holding, setHolding] = useState(false);
  /** A failed reading's advice for this step, kept over the generic live hint. */
  const [advice, setAdvice] = useState<string | null>(null);
  const captured = useRef<Captured[]>([]);
  const step = steps[stepIndex];

  useEffect(() => {
    const live = captureClient ?? client;
    let stopped = false;
    let finished = false;
    let run = NO_RUN;
    let burst: Kept[] = [];
    let frames = 0;
    let since = performance.now();
    let current = 0;
    let stepStart = performance.now();
    /** Since each step was first shown: its Code 39 fallback deadline survives a recapture. */
    const shown = stepClock(steps.length);
    let stepFrames = 0;
    let lastAcquiredAt = 0;
    let emitted = 0;
    const fastMs: number[] = [];
    const ocrMs: number[] = [];
    const t0 = performance.now();
    const outline = outlineState(setOutlineUi);
    const slots: Slot[] = steps.map(() => ({ status: "needed", session: null, entry: null, blob: null }));
    /** The last outline drawn, kept on screen through a frame that finds none while capturing. */
    let lastPts: [number, number][] | null = null;
    const frame = document.createElement("canvas");
    /** Camera frames presented (requestVideoFrameCallback), so no frame is analysed twice. */
    let presented = 0;
    let analysedAt = -1;
    /** Without requestVideoFrameCallback, each analysis is its own frame. */
    let analyses = 0;
    let counted: HTMLVideoElement | null = null;
    captured.current = [];

    const sessionFor = (i: number) => (slots[i].session ??= createProcessingSession(scanner, "camera"));
    const showProcessing = () => {
      const i = slots.findIndex((s) => s.status === "validating");
      setProcessing(i < 0 ? "Checking the reading…" : `Reading and checking: ${steps[i].label}`);
    };
    /** Why a step is being shown again, until it is acquired again. */
    let retry: { step: number; note: string } | null = null;
    /** Per step: a failed reading's advice, and the hold that gave a futile one (not burst again while held). */
    const advised: (string | null)[] = steps.map(() => null);
    const held: ({ corners: [number, number][]; size: [number, number]; at: number } | null)[] = steps.map(() => null);
    /** Over the camera: a recapture's reason, and what is being read in the background. */
    const refreshNotice = () => {
      const pending = slots.flatMap((s, i) => (s.status === "validating" ? [steps[i].label] : []));
      const notes = [retry?.note, pending.length ? `${pending.join(", ")} captured · reading it in the background` : null].filter(Boolean);
      setNotice(camera.wanted && notes.length ? notes.join(" ") : null);
    };
    const camera = cameraGate(
      () => openCamera(),
      (_, generation) => requestAnimationFrame(() => loop(generation)),
      (e) => {
        if (stopped) return;
        slots[current].session?.fail(e);
        slots[current].session = null;
        setError(e instanceof Error ? e.message : String(e));
      },
    );

    function startStep(i: number) {
      current = i;
      setStepIndex(i);
      stepStart = performance.now();
      shown.show(i, stepStart);
      stepFrames = 0;
      run = NO_RUN;
      burst = [];
      setHolding(false);
      setAdvice(advised[i]);
      lastPts = null;
      sessionFor(i);
    }

    /**
     * Brings the screen in line with `plan`: the camera on the earliest step
     * still needed (kept open, or reopened), else the processing view, else
     * the end. Whether a stream is open yet plays no part: a reopening camera
     * still means the camera view.
     */
    function follow() {
      const next = plan(slots.map((s) => s.status));
      if (next.view === "camera") {
        if (next.step !== current || !camera.wanted) startStep(next.step);
        setProcessing(null);
        camera.want();
      } else {
        camera.drop();
        if (next.view === "processing") showProcessing();
        else finish();
      }
      refreshNotice();
    }

    /** One step's acquisition is over: it validates in the background, and the next needed step (if any) starts. */
    function acquired(i: number, a: Acquired) {
      const slot = slots[i];
      slot.status = "validating";
      lastAcquiredAt = performance.now();
      const session = sessionFor(i);
      const inputCount = a.confirmed ? 1 : a.burst.length;
      session.captured({ step: steps[i].label, inputCount });
      docscan().events.push({ type: "capture_ready", step: steps[i].label, operationId: session.id, inputCount, sinceStartMs: Math.round(lastAcquiredAt - t0) });
      session.stage(a.confirmed ? "save" : "read");
      void validate(i, a).then(
        (r) => {
          if ("entry" in r) return accept(i, r);
          if (r.cancelled || stopped) return slots[i].session?.cancel();
          const advice = guidance(steps[i], r.guide);
          advised[i] = advice;
          // A futile reading of this hold: not burst again while it is held there.
          const last = a.burst.at(-1);
          held[i] = r.futile && last?.fast.document ? { corners: last.fast.document.corners, size: last.size, at: performance.now() } : null;
          if (r.guide) setLast(r.guide);
          recapture(i, r.futile ? `futile reading: ${r.guide?.kind}` : "no two frames gave the same complete reading", advice);
        },
        (e) => {
          // Left mid-read: the operation is cancelled, and nothing reopens.
          if (stopped || isAbort(e)) slots[i].session?.cancel();
          else recapture(i, e instanceof Error ? e.message : String(e));
        },
      );
      if (retry?.step === i) retry = null;
      advised[i] = null;
      setAdvice(null);
      // The camera stays open for the next side, read while this one is
      // checked; or, every side acquired, it is released.
      const next = plan(slots.map((s) => s.status));
      if (next.view === "camera") outline.set("grey", { step: next.step });
      follow();
    }

    /** OCR on each kept frame (unless the barcodes already confirmed it), then the saved image. */
    async function validate(i: number, a: Acquired): Promise<{ entry: Captured; blob: Blob } | Extract<BurstOutcome, { confirmed: false }>> {
      const s = steps[i];
      const cancelled = { confirmed: false, cancelled: true, futile: false, guide: null } as const;
      const outcome: BurstOutcome | null = a.confirmed ? null : await confirmBurst(s, a.burst, async (k) => {
        if (stopped) return null;
        const { result, ms } = await client.run<DocumentResult>({ kind: "document", image: k.image, runOcr: true, expected: s.expect });
        ocrMs.push(ms);
        setFps((f) => ({ ...f, ocrMs: Math.round(ms) }));
        docscan().frames.push({ step: i, ocr: true, background: true, ms, kind: result.kind, accepted: result.accepted, document: result.document !== null, reading: readingKey(result), reasons: result.reasons, passes: result.ocr_passes, turns: result.quarter_turns, timings: result.timings_ms });
        return result;
      });
      if (outcome && !outcome.confirmed) return outcome;
      const chosen = a.confirmed ?? { result: outcome!.result, frame: a.burst[outcome!.index], fallback: false };
      if (stopped) return cancelled;
      // The saved image is the document itself: flattened from the
      // full-resolution frame with the outline found in that frame.
      const { result, frame: k, fallback } = chosen;
      const scale = k.full.width / k.image.width;
      const corners = result.document!.corners.flatMap(([x, y]) => [x * scale, y * scale]);
      const [aw, ah] = result.analysed_size;
      const outW = Math.min(2000, Math.round(aw * scale));
      const outH = Math.round((outW * ah) / aw);
      const flat = await client.run<ImageData>({ kind: "flatten", image: k.full, corners, width: outW, height: outH });
      if (stopped) return cancelled;
      const blob = await toJpeg(flat.result);
      if (stopped) return cancelled;
      return { entry: { step: s.label, result, imageUrl: URL.createObjectURL(blob), fallback, stepMs: a.stepMs, frames: a.frames }, blob };
    }

    function accept(i: number, { entry, blob }: { entry: Captured; blob: Blob }) {
      if (stopped) { URL.revokeObjectURL(entry.imageUrl); return; }
      Object.assign(slots[i], { status: "done", entry, blob });
      slots[i].session!.complete();
      // Published in step order, whichever side finished reading first.
      while (emitted < steps.length && slots[emitted].status === "done") {
        const { entry: e, blob: b } = slots[emitted];
        captured.current.push(e!);
        docscan().events.push({ type: "captured", step: e!.step, kind: e!.result.kind, fallback: e!.fallback, stepMs: Math.round(e!.stepMs ?? 0), sinceStartMs: Math.round(performance.now() - t0), result: e!.result });
        // For a host page: one event per captured side, with the reading and
        // the flattened JPEG (`blob`, and `imageUrl` for an <img>).
        if (emitEvents) window.dispatchEvent(new CustomEvent("docscan:captured", { detail: { ...e!, blob: b } }));
        emitted++;
      }
      follow();
    }

    function finish() {
      if (finished) return;
      finished = true;
      stopped = true;
      outline.set("done");
      const check = crossCheck(captured.current);
      if (check) docscan().events.push({ type: "crosscheck", ...check });
      if (emitEvents) window.dispatchEvent(new CustomEvent("docscan:complete", { detail: { captured: captured.current, crossCheck: check } }));
      onDone(captured.current, {
        source: "camera",
        captureMs: lastAcquiredAt - t0,
        frames: fastMs.length + ocrMs.length,
        ocrFrames: ocrMs.length,
        fastMs: median(fastMs),
        ocrMs: median(ocrMs),
      });
    }

    /** The kept frames did not confirm a reading: that step is captured again, never completed. */
    function recapture(i: number, why: string, advice: string | null = null) {
      if (stopped) return;
      slots[i].session?.fail(new Error(`recapture requested: ${why}`));
      Object.assign(slots[i], { status: "needed", session: null });
      docscan().events.push({ type: "recapture", step: steps[i].label, why });
      // Never "captured": the step says what went wrong, when the reading said.
      retry = { step: i, note: `${steps[i].label}: not captured. ${advice ?? "The reading could not be confirmed. Show it again, held steady."}` };
      const before = camera.wanted ? current : -1;
      follow();
      if (current === i) setAdvice(advice);
      if (current !== before) outline.set("grey", { step: current, why: "recapture" });
    }

    /** The document is where the futile burst found it: the same reading would come back. */
    function stillHeld(i: number, result: DocumentResult, image: ImageData, now: number): boolean {
      const h = held[i];
      if (!h || now - h.at >= FUTILE_HOLD_MS) return false;
      return sameOutline(h.corners, result.document!.corners, [image.width, image.height], HELD_TOLERANCE);
    }

    async function loop(mine: number) {
      const video = videoRef.current;
      const guide = guideRef.current;
      const stream = camera.stream;
      if (stopped || !camera.live(mine) || !stream) return;
      if (video && video.srcObject !== stream) {
        video.srcObject = stream;
        void video.play();
      }
      if (video && counted !== video && "requestVideoFrameCallback" in video) {
        counted = video;
        const tick = () => {
          if (counted !== video || stopped) return;
          presented++;
          video.requestVideoFrameCallback(tick);
        };
        video.requestVideoFrameCallback(tick);
      }
      // Only a new camera frame: one frame never counts twice.
      const fresh = counted !== video || presented !== analysedAt;
      if (!video || !guide || video.readyState < 2 || live.busy || !fresh) {
        requestAnimationFrame(() => loop(mine));
        return;
      }
      analysedAt = presented;
      const frameId = counted === video ? presented : 1e9 + ++analyses;
      const i = current;
      const s = steps[i];
      const rect = guideInVideo(video, guide);
      // The analysed frame, for OCR later and for the saved image.
      snapshot(video, frame);
      const image = grab(frame, rect);
      try {
        const { result, ms } = await live.run<DocumentResult>({ kind: "document", image, runOcr: false, expected: s.expect });
        if (stopped || !camera.live(mine) || i !== current) {
          requestAnimationFrame(() => loop(mine));
          return;
        }
        docscan().frames.push({
          step: i,
          ocr: false,
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
        fastMs.push(ms);
        const now = performance.now();
        if (now - since > 1000) {
          // Computed now: the updater runs later, after the counters reset.
          const fast = Math.round((frames * 1000) / (now - since));
          setFps((f) => ({ ...f, fast }));
          frames = 0;
          since = now;
        }
        setLast(result);

        // A reading from barcodes alone (the smart ID back): confirmed here,
        // by two identical readings from separate frames, as before.
        const fallback = fallbackAllowed(s, result, shown.elapsed(i, now));
        const key = frameKey(s, result, fallback);
        const next = nextRun(run, key, now);
        run = next.run;
        if (next.outline === "green") outline.set("green", { step: i });
        else if (next.outline) outline.set("grey", { step: i, why: next.outline });
        const keep = () => ({ at: now, frame: frameId, size: [image.width, image.height] as [number, number], image: grab(frame, rect), full: grabFull(frame, rect), fast: result });
        let done: Acquired | null = null;
        if (key && run.repeats >= STABLE_READS) {
          done = { confirmed: { result, frame: keep(), fallback }, burst: [], stepMs: now - stepStart, frames: stepFrames };
        } else if (!key && ocrCandidate(s, result) && !stillHeld(i, result, image, now)) {
          // A print-read step: keep separate steady frames for OCR.
          const prev = burst.at(-1);
          const steady = prev && now - burst[0].at < BURST_WINDOW_MS && sameOutline(prev.fast.document!.corners, result.document!.corners, [image.width, image.height]);
          if (!steady && burst.length) outline.set("grey", { step: i, why: "document moved" });
          burst = steady ? [...burst, keep()] : [keep()];
          outline.set("green", { step: i });
          setHolding(true);
          if (burst.length >= BURST_FRAMES) done = { confirmed: null, burst, stepMs: now - stepStart, frames: stepFrames };
        } else if (burst.length && now - burst[0].at >= BURST_WINDOW_MS) {
          burst = [];
          setHolding(false);
          if (run.key === null) outline.set("grey", { step: i, why: "document lost" });
        }
        const green = outline.get() !== "grey";
        const pts = result.document ? result.document.corners.map((p) => cropToScreen(video, rect, image.width, p)) : green ? lastPts : null;
        lastPts = pts;
        drawPolygon(overlayRef.current, video, pts, OUTLINE_COLOUR[outline.get()]);
        if (done) {
          acquired(i, done);
          if (!camera.live(mine)) return;
        }
      } catch (e) {
        if (stopped || isAbort(e)) return;
        setError(String(e));
        // A persistent worker-start failure must not create a new worker on
        // every animation frame. Leaving and reopening explicitly retries it.
        return;
      }
      requestAnimationFrame(() => loop(mine));
    }

    follow();
    return () => {
      stopped = true;
      camera.drop();
      // Left before the end (Back to home): every open operation is
      // cancelled, and images nobody was handed are released.
      for (const slot of slots) {
        slot.session?.cancel();
        if (!finished && slot.entry) URL.revokeObjectURL(slot.entry.imageUrl);
      }
    };
  }, [client, captureClient, steps, scanner, onDone, emitEvents]);

  if (processing) return <ProcessingView title={steps.length > 1 ? "Identity document" : step.label} stage={error ?? processing} />;

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
          {notice ? <div className="muted" data-testid="capture-notice">{notice}</div> : null}
        </div>
        <div className="capture-foot">
          <div className="hint" data-testid="hint">
            {error ?? (holding ? "Hold still — capturing…" : shownHint(step, last, advice))}
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
