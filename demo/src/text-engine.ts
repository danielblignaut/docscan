export type TextEngine = "ocrs" | "ppocr_v6_tiny" | "ppocr_v6_tiny_detail" | "ppocr_v6_tiny_exposure";

export function textEngineFromUrl(search = location.search): TextEngine {
  const engine = new URLSearchParams(search).get("textEngine");
  return engine === "ppocr_v6_tiny" || engine === "ppocr_v6_tiny_detail" || engine === "ppocr_v6_tiny_exposure" ? engine : "ocrs";
}

export function textRequest(engine: TextEngine, image: ImageData) {
  return engine === "ocrs"
    ? { kind: "text_page" as const, image }
    : { kind: "text_v6" as const, image, detail: engine === "ppocr_v6_tiny_detail", ...(engine === "ppocr_v6_tiny_exposure" ? { exposureCompare: true } : {}) };
}

/** New financial-table flow defaults to the reader that preserved punctuation in its browser fixtures. */
export function financialEngineFromUrl(search = location.search): TextEngine {
  const value = new URLSearchParams(search).get("textEngine");
  return value === "ocrs" || value === "ppocr_v6_tiny_detail" ? value : "ppocr_v6_tiny";
}
