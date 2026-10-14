import { useCallback, useEffect, useMemo, useState } from "react";
import { type Captured, crossCheck, type DocType, IdCapture } from "./IdCapture";
import { MultiBarcode } from "./MultiBarcode";
import { ScannerClient } from "./scanner-client";
import type { DocumentResult } from "./types";

(window as unknown as { __docscan: { events: unknown[]; frames: unknown[]; ready?: unknown } }).__docscan = { events: [], frames: [] };

type Mode = { kind: "menu" } | { kind: "id"; doc: DocType } | { kind: "multi"; labels: boolean } | { kind: "done"; captured: Captured[] };

function initialMode(): Mode {
  const p = new URLSearchParams(location.search);
  if (p.get("mode") === "multi") return { kind: "multi", labels: false };
  if (p.get("mode") === "labels") return { kind: "multi", labels: true };
  const doc = p.get("doc") as DocType | null;
  if (doc) return { kind: "id", doc };
  return { kind: "menu" };
}

/** `?threads=N` overrides; by default up to 8 of the device's cores. */
function threadCount(): number {
  const asked = Number(new URLSearchParams(location.search).get("threads"));
  return asked > 0 ? asked : Math.min(8, navigator.hardwareConcurrency || 1);
}

export function App() {
  const client = useMemo(() => new ScannerClient(threadCount()), []);
  const [status, setStatus] = useState("Loading the scanner…");
  const [mode, setMode] = useState<Mode>(initialMode);
  const [photo, setPhoto] = useState<DocumentResult | null>(null);

  useEffect(() => {
    client.ready
      .then((r) => {
        setStatus(`Scanner ready in ${Math.round(r.loadMs)} ms · ${r.threads} thread${r.threads > 1 ? "s" : ""}`);
        (window as unknown as { __docscan: { ready?: unknown } }).__docscan.ready = r;
      })
      .catch((e) => setStatus(`Scanner failed: ${e}`));
  }, [client]);

  const onDone = useCallback((captured: Captured[]) => setMode({ kind: "done", captured }), []);

  async function analysePhoto(file: File) {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, 1280 / bmp.width);
    const c = new OffscreenCanvas(Math.round(bmp.width * scale), Math.round(bmp.height * scale));
    const ctx = c.getContext("2d")!;
    ctx.drawImage(bmp, 0, 0, c.width, c.height);
    const image = ctx.getImageData(0, 0, c.width, c.height);
    const { result } = await client.run<DocumentResult>({ kind: "document", image, runOcr: true, expected: "" });
    setPhoto(result);
  }

  return (
    <main>
      <header>
        <button type="button" className="link" onClick={() => setMode({ kind: "menu" })}>
          docscan
        </button>
        <span data-testid="status">{status}</span>
      </header>
      {mode.kind === "menu" && (
        <section className="menu">
          <h2>Capture an identity document</h2>
          <button type="button" onClick={() => setMode({ kind: "id", doc: "smart_id" })}>SA smart ID card (front and back)</button>
          <button type="button" onClick={() => setMode({ kind: "id", doc: "green_book" })}>SA green ID book</button>
          <button type="button" onClick={() => setMode({ kind: "id", doc: "passport" })}>Passport (SA, UK or other)</button>
          <button type="button" onClick={() => setMode({ kind: "id", doc: "auto" })}>Detect automatically</button>
          <h2>Barcodes</h2>
          <button type="button" onClick={() => setMode({ kind: "multi", labels: false })}>Scan many barcodes at once</button>
          <button type="button" onClick={() => setMode({ kind: "multi", labels: true })}>Scan a device label (IMEI, S/N, EAN)</button>
          <h2>Test with a photo</h2>
          <input type="file" accept="image/*" onChange={(e) => e.target.files?.[0] && analysePhoto(e.target.files[0])} />
          {photo && <ResultView result={photo} />}
        </section>
      )}
      {mode.kind === "id" && <IdCapture client={client} docType={mode.doc} onDone={onDone} />}
      {mode.kind === "multi" && <MultiBarcode client={client} labels={mode.labels} />}
      {mode.kind === "done" && (
        <section className="done" data-testid="done">
          <CrossCheckView captured={mode.captured} />
          {mode.captured.map((c) => (
            <article key={c.step}>
              <h3>{c.step}</h3>
              <img src={c.imageUrl} alt={c.step} />
              <ResultView result={c.result} />
            </article>
          ))}
          <button type="button" onClick={() => setMode({ kind: "menu" })}>Start again</button>
        </section>
      )}
    </main>
  );
}

/** The two sides of a smart ID card must carry the same identity number. */
function CrossCheckView({ captured }: { captured: Captured[] }) {
  const check = crossCheck(captured);
  if (!check) return null;
  return (
    <p className={check.match ? "check ok" : "check mismatch"} data-testid="crosscheck">
      {check.match
        ? `Front and back agree: identity number ${check.front}`
        : `Mismatch: the front reads ${check.front ?? "no number"}, the back's barcode ${check.back ?? "no number"}`}
    </p>
  );
}

function ResultView({ result }: { result: DocumentResult }) {
  const fields: [string, string | undefined | null][] = [];
  if (result.mrz) {
    const m = result.mrz;
    fields.push(["Issuing state", m.issuing_state], ["Surname", m.surname], ["Given names", m.given_names],
      ["Document number", m.document_number], ["Nationality", m.nationality], ["Date of birth", m.date_of_birth],
      ["Sex", m.sex], ["Expiry", m.date_of_expiry], ["Check digits", m.checks.composite && Object.values(m.checks).every(Boolean) ? "all pass" : JSON.stringify(m.checks)]);
  }
  if (result.smart_id_barcode) {
    const b = result.smart_id_barcode;
    fields.push(["Surname", b.surname], ["Names", b.names], ["Sex", b.sex], ["Nationality", b.nationality],
      ["ID number", `${b.id_number.value} (Luhn ${b.id_number.luhn_valid ? "ok" : "FAIL"})`], ["Date of birth", b.date_of_birth],
      ["Country of birth", b.country_of_birth], ["Status", b.status]);
  } else if (result.id_barcode) {
    fields.push(["ID number (Code 39 only)", result.id_barcode.value]);
  }
  if (result.printed) {
    const p = result.printed;
    fields.push(["Surname", p.surname], ["Names", p.names], ["Sex", p.sex], ["Nationality", p.nationality],
      ["Date of birth", p.date_of_birth], ["Country of birth", p.country_of_birth], ["Status", p.status],
      ["ID number", p.id_number ? `${p.id_number.value} (Luhn ${p.id_number.luhn_valid ? "ok" : "FAIL"}, ${p.id_number.sex}, ${p.id_number.citizenship})` : null]);
  }
  return (
    <div className="result">
      <p>
        <b>{result.kind.replaceAll("_", " ")}</b> — {result.accepted ? "accepted" : "not accepted"} · {result.reasons.join("; ")} ·{" "}
        {Math.round(result.timings_ms.total)} ms
      </p>
      <dl>
        {fields.filter(([, v]) => v).map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
      <details>
        <summary>OCR lines and barcodes</summary>
        <pre>{result.lines.map((l) => l.text).join("\n")}</pre>
        <pre>{result.barcodes.map((b) => `${b.format}: ${b.text}`).join("\n")}</pre>
      </details>
    </div>
  );
}
