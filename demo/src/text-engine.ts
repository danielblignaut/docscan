export type TextEngine = "ocrs" | "ppocr_v6_tiny";

export function textEngineFromUrl(search = location.search): TextEngine {
  return new URLSearchParams(search).get("textEngine") === "ppocr_v6_tiny" ? "ppocr_v6_tiny" : "ocrs";
}
