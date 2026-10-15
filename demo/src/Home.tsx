// The home screen: one large card per scanner, with whether it is ready and
// the model it uses, a model choice for proof of address, and on each card a
// small "Test with a photo" action that runs the same scanner on an image.
import { catalogueEntry, chooseExtractor, type Extractor } from "./models";
import type { ReadyInfo } from "./outcome";
import { SCANNERS, type ScannerId, type ScannerInfo } from "./scanners";

interface Props {
  ready: ReadyInfo | null;
  status: string;
  failed: boolean;
  method: Extractor | "auto";
  onMethod: (m: Extractor | "auto") => void;
  onOpen: (id: ScannerId) => void;
  onPhoto: (id: ScannerId, files: File[]) => void;
  /** The scanner reading a photo now, and the last photo error. */
  busy: ScannerId | null;
  photoError: { id: ScannerId; message: string } | null;
}

function modelLine(s: ScannerInfo, ready: ReadyInfo | null, method: Extractor | "auto"): string {
  const ocr = `ocrs OCR · ${catalogueEntry("ocrs").downloadMb} MB`;
  if (s.needs === "none") return "Barcode decoder · no model";
  if (s.needs === "ocr") return s.id === "labels" ? `Barcodes + tiled ${ocr}` : ocr;
  if (!ready) return `${ocr} + extractor`;
  const used = chooseExtractor(ready.tagger, method);
  return used === "tagger" ? `${ocr} + tagger · ${catalogueEntry("poa-tagger").downloadMb} MB` : `${ocr} + layout rules`;
}

export function Home({ ready, status, failed, method, onMethod, onOpen, onPhoto, busy, photoError }: Props) {
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
        {SCANNERS.map((s) => (
          <li key={s.id} className="card" data-card={s.id}>
            <button type="button" className="card-main" data-scanner={s.id} onClick={() => onOpen(s.id)}>
              <span className="card-icon" aria-hidden="true">
                {s.icon}
              </span>
              <span className="card-text">
                <span className="card-title">{s.title}</span>
                <span className="card-desc">{s.description}</span>
                <span className="card-meta">
                  <span className={`pill pill-${state}`}>{state === "ready" ? "Ready" : state === "failed" ? "Failed" : "Loading…"}</span>
                  <span className="muted">{modelLine(s, ready, method)}</span>
                </span>
              </span>
              <span className="card-go" aria-hidden="true">
                ›
              </span>
            </button>
            <div className="card-actions">
              {s.id === "address" && (
                <label className="model-select">
                  <span>Model</span>
                  <select data-testid="address-method" value={method} onChange={(e) => onMethod(e.target.value as Extractor | "auto")}>
                    <option value="auto">Automatic{ready ? ` (${chooseExtractor(ready.tagger, "auto") === "tagger" ? "tagger" : "rules"})` : ""}</option>
                    <option value="tagger" disabled={ready !== null && !ready.tagger}>
                      Trained tagger ({catalogueEntry("poa-tagger").downloadMb} MB){ready && !ready.tagger ? " — not loaded" : ""}
                    </option>
                    <option value="rules">Layout rules (no model)</option>
                  </select>
                </label>
              )}
              <label className={`photo-action ${busy === s.id ? "busy" : ""}`}>
                {busy === s.id ? "Reading the photo…" : s.id === "smart_id" ? "Test with photos (front, back)" : "Test with a photo"}
                <input
                  type="file"
                  accept="image/*"
                  multiple={s.id === "smart_id"}
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
        ))}
      </ul>
    </main>
  );
}
