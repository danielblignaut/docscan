import type { PaddlePageText } from "./TextCapture";

/** The WASM object owns only a derived buffer; the input and primary read stay intact. */
interface Correction {
  version: string;
  applied: boolean;
  changed: boolean;
  gain: number;
  background_p90: number;
  take_rgba(): Uint8Array;
  free(): void;
}
export function compareExposure(
  original: PaddlePageText,
  correct: () => Correction,
  read: (pixels: Uint8Array) => PaddlePageText,
  clock: () => number = () => performance.now(),
): PaddlePageText {
  const start = clock();
  const exposure: NonNullable<PaddlePageText["exposure"]> = {
    version: "frozen-global-exposure-v1", status: "failed", applied: false,
    gain: null, backgroundP90: null, alternative: null, error: null, elapsedMs: 0, ocrPasses: 1,
  };
  try {
    const correction = correct();
    try {
      if (correction.version !== exposure.version) throw new Error("Exposure implementation version mismatch");
      if (!Number.isFinite(correction.gain) || correction.gain < 1 || correction.gain > 4 ||
        !Number.isFinite(correction.background_p90) || correction.background_p90 < 0 || correction.background_p90 > 1)
        throw new Error("Invalid exposure diagnostics");
      exposure.applied = correction.applied;
      exposure.gain = correction.gain;
      exposure.backgroundP90 = correction.background_p90;
      if (correction.changed) {
        const pixels = correction.take_rgba();
        exposure.ocrPasses++;
        exposure.alternative = read(pixels);
        exposure.status = "compared";
      } else exposure.status = "unchanged";
    } finally { correction.free(); }
  } catch (error) {
    exposure.status = "failed";
    exposure.alternative = null;
    exposure.error = String(error);
  }
  exposure.elapsedMs = clock() - start;
  return { ...original, exposure };
}
