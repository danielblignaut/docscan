/** Reader choice is explicit: the faster candidate did not preserve every DEV field. */
export type LabelEngine = "detailed" | "fast";
export const FAST_LABEL_LIMITATION = "Experimental fast reading can miss or change fields. Check IMEI and serial numbers against the image; the detailed reader remains available.";
export function labelEngineFromUrl(search = location.search): LabelEngine {
  return new URLSearchParams(search).get("labelReader") === "fast" ? "fast" : "detailed";
}
export function labelRequest(engine: LabelEngine, image: ImageData) {
  return { kind: "labelled" as const, image, ...(engine === "fast" ? {profile: "fast" as const} : {}) };
}
