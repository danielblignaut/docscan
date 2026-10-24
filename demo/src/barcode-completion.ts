// When a live barcode scan is complete, and how its captured frames are
// finished into a result. Pure: no DOM, no camera, no worker; MultiBarcode.tsx
// supplies those as arguments.
import type { SeenCode } from "./outcome";
import type { LabelledField } from "./types";

/**
 * A code is listed once read in this many frames. rxing occasionally reports
 * a spurious short code (a UPC-E inside a dense symbol) in a single frame; a
 * real code in view is read again in the next.
 */
export const CONFIRM_FRAMES = 2;

/**
 * The scan finishes on its own once at least one code is confirmed and,
 * since the last novelty (a code read for the first time, or one newly
 * confirmed), both QUIET_MS have passed and QUIET_FRAMES more frames have
 * been analysed. Time alone is not enough: a phone pass at 1920 px can take
 * 400 ms, so 750 ms is two frames there, and a code first read in the last of
 * them would never get the second read that lists it. Frames alone are not
 * enough either: a 40 ms desktop pass would end the scan before staff have
 * swept the sheet.
 */
export const QUIET_MS = 750;
export const QUIET_FRAMES = 2;
/**
 * A code read once and never again (a spurious read, a code at the edge of
 * view) does not hold the scan open for ever: novelty from codes read only
 * once stops counting this long, and this many frames, after the last
 * confirmation. A run of fresh spurious reads therefore finishes at most this
 * long after the set stopped growing.
 */
export const PENDING_CAP_MS = 2500;
export const PENDING_CAP_FRAMES = 6;

/**
 * Device labels: how many distinct acquired frames (the one that read the
 * most codes, and the latest other one) are OCR'd once the camera is off.
 */
export const STABLE_PASSES = 2;

export interface QuietClock {
  /** Frames analysed so far. */
  frame: number;
  /** When, and in which frame, a code was last newly confirmed (-1: none). */
  confirmedAt: number;
  confirmedFrame: number;
  /** When, and in which frame, a code was last read for the first time. */
  novelAt: number;
  novelFrame: number;
}

export function quietClock(): QuietClock {
  return { frame: 0, confirmedAt: -1, confirmedFrame: -1, novelAt: -1, novelFrame: -1 };
}

/**
 * Counts one analysed frame's codes into `all` and advances the clock.
 * Returns the codes that reached CONFIRM_FRAMES in this frame.
 */
export function countFrame(all: Map<string, SeenCode>, clock: QuietClock, codes: readonly { format: string; text: string }[], now: number): SeenCode[] {
  clock.frame++;
  const fresh: SeenCode[] = [];
  // A frame can report the same code twice (two copies on one sheet): one frame, one read.
  const keys = new Set<string>();
  for (const b of codes) {
    const key = `${b.format}|${b.text}`;
    if (keys.has(key)) continue;
    keys.add(key);
    const s = all.get(key) ?? { format: b.format, text: b.text, count: 0 };
    s.count++;
    all.set(key, s);
    if (s.count === 1) {
      clock.novelAt = now;
      clock.novelFrame = clock.frame;
    }
    if (s.count === CONFIRM_FRAMES) fresh.push(s);
  }
  if (fresh.length) {
    clock.confirmedAt = now;
    clock.confirmedFrame = clock.frame;
  }
  return fresh;
}

const quietSince = (clock: QuietClock, at: number, frame: number, now: number) =>
  now - at >= QUIET_MS && clock.frame - frame >= QUIET_FRAMES;

/**
 * Whether the quiet rule fires now. Needs a confirmed code, quiet since the
 * last confirmation, and quiet since the last first read unless that wait has
 * run past the pending cap.
 */
export function quietDone(clock: QuietClock, now: number): boolean {
  if (clock.confirmedFrame < 0) return false;
  if (!quietSince(clock, clock.confirmedAt, clock.confirmedFrame, now)) return false;
  if (clock.novelFrame <= clock.confirmedFrame) return true;
  if (quietSince(clock, clock.novelAt, clock.novelFrame, now)) return true;
  return now - clock.confirmedAt >= PENDING_CAP_MS && clock.frame - clock.confirmedFrame >= PENDING_CAP_FRAMES;
}

/** Milliseconds until the quiet rule could fire on time alone; null before the first confirmation. */
export function quietLeft(clock: QuietClock, now: number): number | null {
  if (clock.confirmedFrame < 0) return null;
  const pending = clock.novelFrame > clock.confirmedFrame;
  const from = pending ? Math.min(clock.novelAt, clock.confirmedAt + PENDING_CAP_MS - QUIET_MS) : clock.confirmedAt;
  return Math.max(0, from + QUIET_MS - now);
}

export type ReadField = LabelledField & { seen: number };

export interface LabelMerge {
  fields: ReadField[];
  /** Set when a value is listed on weaker evidence than the reader would like. */
  warning?: string;
}

/**
 * Merges the OCR reads of `reads` frames, as the photo flow lists one read:
 * every field whose check digit did not fail (`check_digit_valid !== false`),
 * so a serial number (no check digit) read once is kept, not dropped. A label
 * read as two different values is not resolved: both are listed, and the
 * warning says so. A value without a check digit that not every frame read is
 * listed, and the warning says it is unconfirmed.
 */
export function mergeLabelReads(perFrame: readonly (readonly LabelledField[])[]): LabelMerge {
  const reads = perFrame.length;
  const byValue = new Map<string, ReadField>();
  for (const fields of perFrame) {
    const once = new Set<string>();
    for (const f of fields) {
      if (f.check_digit_valid === false) continue;
      // One value of one label, however it was read (bars, print or both).
      const key = `${f.label ?? ""}|${f.value}`;
      if (once.has(key)) continue;
      once.add(key);
      const prev = byValue.get(key);
      // Keep the strongest evidence for the value: a decoded bar beats print alone.
      const best = prev && (prev.source !== "text" || f.source === "text") ? prev : f;
      byValue.set(key, { ...best, seen: (prev?.seen ?? 0) + 1 });
    }
  }
  const byLabel = new Map<string, ReadField[]>();
  for (const f of byValue.values()) {
    const key = f.label ?? `${f.barcode_format}|${f.value}`;
    byLabel.set(key, [...(byLabel.get(key) ?? []), f]);
  }
  const conflicts = [...byLabel.entries()].filter(([, fs]) => fs.length > 1).map(([label]) => label);
  let number = 0;
  const fields = [...byValue.values()]
    .sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0])
    .map((f) => ({ ...f, name: f.label ?? `Barcode ${++number}` }));
  const unconfirmed = fields.filter((f) => f.check_digit_valid === null && f.seen < reads && !conflicts.includes(f.label ?? ""));
  const single = reads === 1 ? fields.filter((f) => f.check_digit_valid === null) : [];
  const notes: string[] = [];
  if (conflicts.length) notes.push(`${conflicts.join(", ")} read as different values in different frames; every reading is listed — check against the label.`);
  if (single.length) notes.push(`${single.length} value${single.length === 1 ? "" : "s"} without a check digit read from a single frame; not confirmed by a second read.`);
  else if (unconfirmed.length) notes.push(`${unconfirmed.length} value${unconfirmed.length === 1 ? "" : "s"} without a check digit read in only one of ${reads} frames.`);
  return notes.length ? { fields, warning: notes.join(" ") } : { fields };
}

export interface Finished {
  blob: Blob | null;
  fields: ReadField[];
  ocrMs: number[];
  labelReadError?: string;
  labelReadWarning?: string;
}

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

/**
 * Finishes a capture once the camera is off: encodes the still while the
 * label frames are read, one after another. Neither is allowed to lose the
 * confirmed barcodes: a still that fails to encode leaves `blob` null, and a
 * label read that fails stops reading and sets `labelReadError`, keeping what
 * earlier frames read. Returns null once `cancelled()` is true, so nothing
 * from a disposed scan is published; `onFields` is not called after that.
 */
export async function finishCapture<I>(args: {
  encodeStill: () => Promise<Blob>;
  labelFrames: readonly I[];
  readLabel: (image: I) => Promise<{ result: { fields: LabelledField[] }; ms: number }>;
  onFields?: (fields: ReadField[]) => void;
  cancelled: () => boolean;
}): Promise<Finished | null> {
  const encoding = args.encodeStill().then((blob) => blob, () => null);
  const reads: LabelledField[][] = [];
  const ocrMs: number[] = [];
  let merged: LabelMerge = { fields: [] };
  let labelReadError: string | undefined;
  for (const image of args.labelFrames) {
    try {
      const { result, ms } = await args.readLabel(image);
      if (args.cancelled()) return null;
      ocrMs.push(ms);
      reads.push(result.fields);
      merged = mergeLabelReads(reads);
      args.onFields?.(merged.fields);
    } catch (error) {
      if (args.cancelled()) return null;
      labelReadError = message(error);
      break;
    }
  }
  const blob = await encoding;
  if (args.cancelled()) return null;
  return {
    blob,
    fields: merged.fields,
    ocrMs,
    ...(labelReadError ? { labelReadError } : {}),
    ...(merged.warning ? { labelReadWarning: merged.warning } : {}),
  };
}
