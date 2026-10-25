import {readerRoute} from "./reader-routing";
import { FAST_LABEL_LIMITATION, type LabelEngine } from "./label-engine";
// The home screen: one large card per scanner, with whether it is ready and
// the model it uses, a model choice for proof of address, and on each card a
// small "Test with a photo" action that runs the same scanner on an image.
import type { TextEngine } from "./text-engine";
import { FACE_DOWNLOAD_MB } from "./face-models";
import { catalogueEntry, chooseExtractor, type Extractor } from "./models";
import type { ReadyInfo } from "./outcome";
import { SCANNERS, type ScannerId, type ScannerInfo } from "./scanners";

interface Props {
  ready: ReadyInfo | null;
  status: string;
  modelsState: "loading" | "idle" | "failed" | "ready";
  paddleState: "loading" | "idle" | "failed" | "ready";
  failed: boolean;
  method: Extractor | "auto";
  financialEngine: TextEngine;
  onFinancialEngine: (engine: TextEngine) => void;
  labelEngine: LabelEngine;
  onLabelEngine: (engine: LabelEngine) => void;
  textEngine: TextEngine;
  onTextEngine: (engine: TextEngine) => void;
  onMethod: (m: Extractor | "auto") => void;
  onOpen: (id: ScannerId) => void;
  onPhoto: (id: ScannerId, files: File[]) => void;
  /** The scanner reading a photo now, and the last photo error. */
  busy: ScannerId | null;
  photoError: { id: ScannerId; message: string } | null;
}

function modelLine(s: ScannerInfo, ready: ReadyInfo | null, method: Extractor | "auto", textEngine: TextEngine, labelEngine: LabelEngine): string {
  if (s.id === "labels" && labelEngine === "fast") return "Barcodes + PP-OCRv6 tiny · experimental";
  if ((s.id === "text" || s.id === "tables") && textEngine !== "ocrs") return "PP-OCRv6 tiny · ~6.3 MB · loaded when used";
  const ocr = `ocrs OCR · ${catalogueEntry("ocrs").downloadMb} MB`;
  if (s.needs === "none") return "Barcode decoder · no model";
  if (s.needs === "face") return s.id === "facedoc" ? `Face models · ${FACE_DOWNLOAD_MB.toFixed(1)} MB + ${ocr}` : `Face models · ${FACE_DOWNLOAD_MB.toFixed(1)} MB, loaded when opened`;
  if (s.needs === "ocr") return s.id === "labels" ? `Barcodes + tiled ${ocr}` : ocr;
  if (!ready) return `${ocr} + extractor`;
  const used = chooseExtractor(ready.tagger, method);
  return used === "tagger" ? `${ocr} + tagger · ${catalogueEntry("poa-tagger").downloadMb} MB` : `${ocr} + layout rules`;
}

export function Home({ ready, status, modelsState, paddleState, failed, method, financialEngine, onFinancialEngine, labelEngine, onLabelEngine, textEngine, onTextEngine, onMethod, onOpen, onPhoto, busy, photoError }: Props) {
  const documentReady = modelsState === "ready" ? ready : null;
  const state = failed ? "failed" : ready ? "ready" : "loading";
  return (
    <main className="home" data-testid="home">
      <header className="home-head">
        <h1>docscan</h1>
        <p className="muted">Scanned on this device: no image leaves the phone.</p>
        <p className={`status status-${state}`} data-testid="status">
          {status}
        </p>
      </header>
      <ul className="cards">
        {SCANNERS.map((s) => {
          const needsDocuments = s.needs === "ocr" || s.needs === "address" || s.id === "facedoc";
          const route=readerRoute(s.id,textEngine,financialEngine,labelEngine);
          const cardState = route === "paddle" ? paddleState : needsDocuments && ready ? modelsState : state;
          const cardLabel = cardState === "ready" ? "Ready" : cardState === "failed" ? "Retry models" : cardState === "idle" ? "Load when used" : "Loading…";
          return (
          <li key={s.id} className="card" data-card={s.id}>
            <button type="button" className="card-main" data-scanner={s.id} onClick={() => onOpen(s.id)}>
              <span className="card-icon" aria-hidden="true">
                {s.icon}
              </span>
              <span className="card-text">
                <span className="card-title">{s.title}</span>
                <span className="card-desc">{s.description}</span>
                <span className="card-meta">
                  <span className={`pill pill-${cardState}`}>{cardLabel}</span>
                  <span className="muted">{modelLine(s, s.id === "address" ? documentReady : ready, method, s.id === "tables" ? financialEngine : textEngine, labelEngine)}</span>
                </span>
              </span>
              <span className="card-go" aria-hidden="true">
                ›
              </span>
            </button>
            <div className="card-actions">
              {(s.id === "labels" || s.id === "barcodes" || s.id === "items") && <label className="model-select">
                <span>Printed label reader</span>
                <select data-testid={`label-engine-${s.id}`} value={labelEngine} onChange={e=>onLabelEngine(e.target.value as LabelEngine)} disabled={busy !== null}>
                  <option value="detailed">Detailed · existing reader</option>
                  <option value="fast">Fast · PP-OCRv6 tiny (experimental)</option>
                </select>
                {labelEngine === "fast" && <small>{FAST_LABEL_LIMITATION}</small>}
              </label>}
              {(s.id === "text" || s.id === "tables") && (
                <label className="model-select">
                  <span>{s.id === "tables" ? "Table text reader" : "Text reader"}</span>
                  <select data-testid={s.id === "tables" ? "financial-engine" : "text-engine"} value={s.id === "tables" ? financialEngine : textEngine} onChange={(e) => (s.id === "tables" ? onFinancialEngine : onTextEngine)(e.target.value as TextEngine)} disabled={busy !== null}>
                    <option value="ocrs">ocrs · text and word positions</option>
                    <option value="ppocr_v6_tiny">PP-OCRv6 tiny · multilingual, line positions · ~6.3 MB extra</option>
                    <option value="ppocr_v6_tiny_detail">PP-OCRv6 tiny · small print (slower, more memory)</option>
                    {s.id === "text" && <option value="ppocr_v6_tiny_exposure">PP-OCRv6 tiny · compare brighter reading (experimental, slower)</option>}
                  </select>
                </label>
              )}
              {s.id === "address" && (
                <label className="model-select">
                  <span>Model</span>
                  <select data-testid="address-method" value={method} onChange={(e) => onMethod(e.target.value as Extractor | "auto")}>
                    <option value="auto">Automatic{documentReady ? ` (${chooseExtractor(documentReady.tagger, "auto") === "tagger" ? "tagger" : "rules"})` : ""}</option>
                    <option value="tagger" disabled={documentReady !== null && !documentReady.tagger}>
                      Trained tagger ({catalogueEntry("poa-tagger").downloadMb} MB){documentReady && !documentReady.tagger ? " — not loaded" : ""}
                    </option>
                    <option value="rules">Layout rules (no model)</option>
                  </select>
                </label>
              )}
              <label className={`photo-action ${busy === s.id ? "busy" : ""}`}>
                {busy === s.id
                  ? "Reading the document…"
                  : s.id === "smart_id"
                    ? "Import images or PDF (front, back)"
                    : s.id === "facedoc"
                      ? "Import ID image/PDF and selfie image"
                      : s.needs === "face" ? "Test with a photo" : "Import image or PDF"}
                <input
                  type="file"
                  accept={s.id === "liveness" || s.id === "faceid" ? "image/jpeg,image/png,image/webp" : "image/jpeg,image/png,image/webp,application/pdf"}
                  multiple={s.id !== "liveness" && s.id !== "faceid"}
                  disabled={busy !== null || !ready}
                  data-photo={s.id}
                  onChange={(e) => {
                    const files = [...(e.target.files ?? [])];
                    e.target.value = "";
                    if (files.length) onPhoto(s.id, files);
                  }}
                />
              </label>
            </div>
            {photoError?.id === s.id && <p className="card-error">{photoError.message}</p>}
          </li>
        ); })}
      </ul>
      <footer className="home-foot" data-testid="credits">
        <p>
          Code: MIT or Apache-2.0. Models and data are under their own terms:
          OCR models © Robert Knight (<a href="https://huggingface.co/robertknight/ocrs">ocrs</a>,{" "}
          <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>, trained on HierText; the page
          detector is a modified version, also CC BY-SA 4.0);
          optional PP-OCRv6 tiny models and adapted preprocessing © <a href="https://github.com/PaddlePaddle/PaddleOCR">PaddlePaddle</a> (Apache-2.0);
          BlazeFace and Face Mesh © Google (<a href="https://github.com/google-ai-edge/mediapipe">MediaPipe</a>, Apache-2.0);
          MiniFASNet © <a href="https://github.com/minivision-ai/Silent-Face-Anti-Spoofing">Minivision</a> (Apache-2.0);
          SFace © <a href="https://github.com/opencv/opencv_zoo">OpenCV</a> (Apache-2.0);
          GS1 parsing metadata © GS1 AISBL (<a href="https://github.com/gs1/gs1-syntax-dictionary">syntax dictionary</a>, <a href={`${import.meta.env.BASE_URL}licenses/gs1.txt`}>Apache-2.0</a>);{" "}
          barcodes by <a href="https://github.com/rxing-core/rxing">rxing</a>, a port of ZXing (Apache-2.0);
          place names from <a href="https://www.geonames.org">GeoNames</a>{" "}
          (<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>).
        </p>
        <p>
          <a href="https://github.com/danielblignaut/docscan#licence-and-attribution">Full attribution and licences</a>
          {" · "}
          <a href="https://github.com/danielblignaut/docscan/blob/main/NOTICE">NOTICE</a>
        </p>
      </footer>
    </main>
  );
}
