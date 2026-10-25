import { type LabelEngine, labelEngineFromUrl } from "./label-engine";
// Three screens: home (a card per scanner), the full-screen camera, and the
// results form. The URL names the scanner (`?doc=…`, `?mode=…`), so a deep
// link opens its camera directly; Back to home always returns to the menu.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AddressCaptured } from "./AddressCapture";
import { AddressCapture } from "./AddressCapture";
import { FaceClient } from "./face-client";
import { type FaceFlowId, FaceFlow } from "./FaceFlow";
import { Home } from "./Home";
import { type Captured, type DocType, IdCapture } from "./IdCapture";
import { type TextEngine, textEngineFromUrl, financialEngineFromUrl } from "./text-engine";
import { TextCapture } from "./TextCapture";
import { FinancialCapture } from "./FinancialCapture";
import { readFinancialPages } from "./financial-data";
import type { ItemRegion } from "./item-grouping";
import type { FinancialTablesOptions } from "./financial-tables";
import { ItemsCapture } from "./ItemsCapture";
import { MultiBarcode } from "./MultiBarcode";
import type { Extractor } from "./models";
import type { CaptureMeta, Outcome, ReadyInfo } from "./outcome";
import { analysePhotos, releasePhotoOutcome } from "./photo";
import { Results } from "./Results";
import { ScannerClient } from "./scanner-client";
import { createProcessingSession, type ProcessingSession } from "./processing";
import { barcodeLeaves, cancelLabelReadings, enrichmentDetail, mergeLabelReading, replaceOutcome } from "./barcode-enrichment";
import { ProcessingView } from "./ProcessingView";
import { methodFromUrl, type ScannerId, scannerById, scannerFromUrl, urlFor } from "./scanners";

(window as unknown as { __docscan: { events: unknown[]; frames: unknown[]; ready?: unknown } }).__docscan = { events: [], frames: [] };

type Screen = { kind: "home" } | { kind: "capture"; scanner: ScannerId } | { kind: "processing"; scanner: ScannerId } | { kind: "results"; outcome: Outcome };

function screenFromUrl(): Screen {
  const scanner = scannerFromUrl();
  return scanner ? { kind: "capture", scanner } : { kind: "home" };
}

/** `?threads=N` overrides; by default up to 8 of the device's cores. */
function threadCount(): number {
  const asked = Number(new URLSearchParams(location.search).get("threads"));
  return asked > 0 ? asked : Math.min(8, navigator.hardwareConcurrency || 1);
}

/** Set on the history entries the app pushes, so Back to home can pop them. */
const PUSHED = "docscan";

export function App() {
  const client = useMemo(() => new ScannerClient(threadCount()), []);
  const fastClient = useMemo(() => new ScannerClient(1, { loadModels: false }), []);
  // The face models (~18 MB) load only once a face scanner is opened.
  const faceRef = useRef<FaceClient | null>(null);
  const faceClient = useCallback(() => {
    faceRef.current ??= new FaceClient(threadCount());
    return faceRef.current;
  }, []);
  const [status, setStatus] = useState("Loading the scanner…");
  const [ready, setReady] = useState<ReadyInfo | null>(null);
  const [failed, setFailed] = useState(false);
  const [modelsState, setModelsState] = useState<"loading" | "idle" | "failed" | "ready">("loading");
  const [readingLabels, setReadingLabels] = useState(false);
  const [screen, setScreen] = useState<Screen>(screenFromUrl);
  const resultRef = useRef<Outcome | null>(null);
  // Release on explicit transitions, outside React's replayable state updaters
  // and effect cleanups. StrictMode must never revoke a displayed preview.
  const changeScreen = useCallback((next: Screen) => {
    const previous = resultRef.current;
    resultRef.current = next.kind === "results" ? next.outcome : null;
    if (previous && previous !== resultRef.current) releasePhotoOutcome(previous);
    setScreen(next);
  }, []);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      // React replays mount effects synchronously in StrictMode. Defer actual
      // disposal until that replay has had a chance to reclaim the result.
      queueMicrotask(() => {
        if (!mounted.current) {
          if (resultRef.current) {
            const { outcome, cancelled } = cancelLabelReadings(resultRef.current);
            for (const page of cancelled) window.dispatchEvent(new CustomEvent("docscan:enriched", {
              detail: enrichmentDetail(outcome, page, labelOperation.current),
            }));
          }
          if (resultRef.current) releasePhotoOutcome(resultRef.current);
          resultRef.current = null;
          client.dispose(); fastClient.dispose(); faceRef.current?.dispose();
        }
      });
    };
  }, [client, fastClient]);
  const [financialEngine, setFinancialEngine] = useState<TextEngine>(financialEngineFromUrl);
  const [labelEngine, setLabelEngine] = useState<LabelEngine>(labelEngineFromUrl);
  const [textEngine, setTextEngine] = useState<TextEngine>(textEngineFromUrl);
  const [method, setMethod] = useState<Extractor | "auto">(methodFromUrl);
  const [busy, setBusy] = useState<ScannerId | null>(null);
  const [photoError, setPhotoError] = useState<{ id: ScannerId; message: string } | null>(null);
  const photoRequest = useRef<AbortController | null>(null);
  const photoProcessing = useRef<ProcessingSession | null>(null);
  const photoClient = useRef<ScannerClient | null>(null);
  const attemptedLabels = useRef(new WeakSet<Outcome>());
  const labelOperation = useRef<string | null>(null);
  const cancelPhoto = useCallback((cancelLabelQueue = true) => {
    if (cancelLabelQueue && resultRef.current) {
      const { outcome, cancelled } = cancelLabelReadings(resultRef.current);
      for (const value of barcodeLeaves(outcome)) attemptedLabels.current.add(value);
      if (cancelled.length) {
        resultRef.current = outcome; setScreen({ kind: "results", outcome });
        for (const page of cancelled) window.dispatchEvent(new CustomEvent("docscan:enriched", {
          detail: enrichmentDetail(outcome, page, labelOperation.current),
        }));
      }
    }
    photoRequest.current?.abort();
    photoRequest.current = null;
    photoProcessing.current?.cancel(); photoProcessing.current = null;
    client.cancelPending();
    // A live camera pass may finish normally; only kill an abandoned file read.
    if (photoClient.current === fastClient) fastClient.cancelPending();
    photoClient.current = null;
    labelOperation.current = null;
    setReadingLabels(false);
    setBusy(null);
  }, [client, fastClient]);
  useEffect(() => () => { photoRequest.current?.abort(); photoProcessing.current?.cancel(); }, []);


  useEffect(() => {
    fastClient.onReady = r => {
      setReady(previous => previous ?? r);
      setFailed(false);
      (window as unknown as { __docscan: { captureReady?: unknown } }).__docscan.captureReady = r;
    };
    fastClient.onState = (state, error) => {
      if (state === "failed") { setFailed(true); setStatus(`Scanner failed: ${error?.message}`); }
    };
    client.onState = (state, error) => {
      setModelsState(state);
      if (state === "failed") setStatus(`Document models unavailable; select a document scanner to retry. Barcode scanning remains available. ${error?.message ?? ""}`);
      else if (state === "idle") setStatus("Barcode scanner ready. Document models load when needed.");
    };
    client.onReady = r => {
      setReady(r); setModelsState("ready");
      setStatus(`Scanner ready in ${Math.round(r.loadMs)} ms · ${r.threads} thread${r.threads > 1 ? "s" : ""}${r.tagger ? " · tagger" : ""}`);
      (window as unknown as { __docscan: { ready?: unknown } }).__docscan.ready = r;
    };
    void fastClient.ready.catch(() => {});
    void client.ready.catch(() => {});
    return () => { fastClient.onReady = null; fastClient.onState = null; client.onReady = null; client.onState = null; };
  }, [client, fastClient]);

  // Model download progress, and a request that the browser keep the cached models.
  useEffect(() => {
    client.onProgress = (p) => {
      if (!p.cached && p.total) setStatus(`Downloading ${p.file}: ${Math.round((100 * p.loaded) / p.total)}%`);
    };
    void navigator.storage?.persist?.().catch(() => false);
  }, [client]);

  // The browser's own Back (and Android's) follows the URL.
  useEffect(() => {
    const onPop = () => { cancelPhoto(); setTextEngine(textEngineFromUrl()); setFinancialEngine(financialEngineFromUrl()); setLabelEngine(labelEngineFromUrl()); changeScreen(screenFromUrl()); };
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, [cancelPhoto, changeScreen]);

  // Each screen starts at the top.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [screen.kind]);

  const open = useCallback(
    (scanner: ScannerId) => {
      cancelPhoto();
      history.pushState(PUSHED, "", urlFor(scanner, method, scanner === "tables" ? financialEngine : textEngine, labelEngine));
      changeScreen({ kind: "capture", scanner });
    },
    [method, textEngine, financialEngine, labelEngine, cancelPhoto, changeScreen],
  );

  /** Unmounting the capture screen stops its camera. */
  const goHome = useCallback(() => {
    cancelPhoto();
    changeScreen({ kind: "home" });
    if (history.state === PUSHED) history.back();
    else history.replaceState(null, "", urlFor(null));
  }, [cancelPhoto, changeScreen]);

  const onId = useCallback(
    (scanner: ScannerId) => (captured: Captured[], meta: CaptureMeta) => changeScreen({ kind: "results", outcome: { kind: "id", scanner, captured, meta } }),
    [changeScreen],
  );
  const onAddress = useCallback((captured: AddressCaptured, meta: CaptureMeta) => changeScreen({ kind: "results", outcome: { kind: "address", captured, meta } }), [changeScreen]);
  const onOutcome = useCallback((outcome: Outcome) => changeScreen({ kind: "results", outcome }), [changeScreen]);
  const capturing = screen.kind === "capture" ? screen.scanner : null;
  // Stable per scanner: the capture restarts when its callback changes.
  const idDone = useMemo(() => (capturing ? onId(capturing) : null), [capturing, onId]);

  async function onPhoto(id: ScannerId, files: File[]) {
    cancelPhoto();
    // An import selected from the camera screen must stop its frame loop before
    // the shared worker reads the file. The home card shows import progress.
    if (screen.kind === "capture") {
      changeScreen({ kind: "home" });
      history.replaceState(null, "", urlFor(null));
    }
    const request = new AbortController();
    photoRequest.current = request;
    photoClient.current = (id === "barcodes" || id === "items") ? fastClient : client;
    const processing = createProcessingSession(id, "file");
    photoProcessing.current = processing;
    processing.captured({ inputCount: files.length });
    processing.stage((id === "barcodes" || id === "items") ? "decoding_barcodes" : "reading_image");
    changeScreen({ kind: "processing", scanner: id });
    setBusy(id);
    setPhotoError(null);
    try {
      const outcome = await analysePhotos((id === "barcodes" || id === "items") ? fastClient : client, id, files, method, faceClient, id === "tables" ? financialEngine : textEngine, request.signal, labelEngine);
      if (request.signal.aborted) { releasePhotoOutcome(outcome); return; }
      if (outcome.kind === "file_error" && outcome.severity !== "warning") processing.fail(outcome.message);
      else processing.complete();
      outcome.operationId = processing.id;
      history.pushState(PUSHED, "", urlFor(id, method, id === "tables" ? financialEngine : textEngine, labelEngine));
      changeScreen({ kind: "results", outcome });
      window.dispatchEvent(new CustomEvent("docscan:file", { detail: { outcome, operationId: processing.id } }));
    } catch (e) {
      if (request.signal.aborted) return;
      processing.fail(e);
      changeScreen({ kind: "home" });
      setPhotoError({ id, message: `Could not read the document: ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      if (photoRequest.current === request) { photoRequest.current = null; photoProcessing.current = null; photoClient.current = null; setBusy(null); }
    }
  }

  async function readLabels(target: Extract<Outcome, { kind: "barcodes" }>) {
    let root = resultRef.current;
    const blob = target.blob;
    if (!root || !blob) return;
    attemptedLabels.current.add(target);
    cancelPhoto(false);
    const request = new AbortController();
    photoRequest.current = request; photoClient.current = client;
    const session = createProcessingSession("labels", target.meta.source === "camera" ? "camera" : "file");
    photoProcessing.current = session; labelOperation.current = session.id;
    const originalTarget = target;
    target = { ...target, labelReader: labelEngine, labelReadStatus: "pending", labelReadError: undefined };
    attemptedLabels.current.add(target);
    root = replaceOutcome(root, originalTarget, target);
    resultRef.current = root; setScreen({ kind: "results", outcome: root });
    session.stage("reading_labels"); setReadingLabels(true);
    const start = performance.now();
    let reading: Outcome | undefined;
    try {
      reading = await analysePhotos(client, "labels", [blob instanceof File ? blob : new File([blob], "captured-label.jpg", { type: blob.type || "image/jpeg" })], method, faceClient, textEngine, request.signal, labelEngine);
      if (request.signal.aborted || resultRef.current !== root) return;
      const replacement = mergeLabelReading(target, reading, performance.now() - start);
      const next = replaceOutcome(root, target, replacement);
      // Refinement shares the original previews: ownership moves, without revocation.
      resultRef.current = next; setScreen({ kind: "results", outcome: next });
      if (replacement.labelReadError) session.fail(replacement.labelReadError); else session.complete();
      window.dispatchEvent(new CustomEvent("docscan:enriched", { detail: enrichmentDetail(next, replacement, session.id) }));
    } catch (error) {
      if (request.signal.aborted || resultRef.current !== root) return;
      session.fail(error);
      const replacement = { ...target, labelReadStatus: "failed" as const, labelReadError: error instanceof Error ? error.message : String(error) };
      const next = replaceOutcome(root, target, replacement);
      resultRef.current = next; setScreen({ kind: "results", outcome: next });
      window.dispatchEvent(new CustomEvent("docscan:enriched", { detail: enrichmentDetail(next, replacement, session.id) }));
    } finally {
      if (reading) releasePhotoOutcome(reading);
      if (photoRequest.current === request) {
        photoRequest.current = null; photoProcessing.current = null; photoClient.current = null; labelOperation.current = null; setReadingLabels(false);
      }
    }
  }

  // Display decoded codes first; add printed labels without blocking use of
  // the results. A cancelled attempt is never silently restarted.
  useEffect(() => {
    if (screen.kind !== "results" || readingLabels) return;
    const target = barcodeLeaves(screen.outcome).find(value => !value.labels && value.blob &&
      value.labelReadMs === undefined && value.labelReadStatus !== "cancelled" && !value.labelReadError && !attemptedLabels.current.has(value));
    if (target) void readLabels(target);
  }, [screen, readingLabels]);

  function onItemRegions(target: Extract<Outcome,{kind:"barcodes"}>, regions: ItemRegion[]) {
    const root=resultRef.current;
    if (!root || photoRequest.current || !barcodeLeaves(root).includes(target)) return;
    const next=replaceOutcome(root,target,{...target,itemRegions:regions});
    resultRef.current=next;setScreen({kind:"results",outcome:next});
    window.dispatchEvent(new CustomEvent("docscan:items-review",{detail:{operationId:next.operationId??null,outcome:next}}));
  }

  function onFinancialOptions(target: Extract<Outcome,{kind:"financial"}>, options: FinancialTablesOptions) {
    if (!resultRef.current) return;
    const next = replaceOutcome(resultRef.current,target,{...target,options,report:readFinancialPages(target.pages,options,target.incompleteInputs)});
    resultRef.current=next;setScreen({kind:"results",outcome:next});
    window.dispatchEvent(new CustomEvent("docscan:financial",{detail:{operationId:next.operationId??null,source:"review_options",outcome:next}}));
  }

  if (screen.kind === "results") return <>
    {readingLabels && <aside className="processing-panel" role="status" data-testid="label-processing">
      Reading printed labels… Barcode results are ready to use.
      <button type="button" data-testid="cancel-label-reading" onClick={() => cancelPhoto()}>Stop label reading</button>
    </aside>}
    <Results outcome={screen.outcome} onFinancialOptions={onFinancialOptions} onItemRegions={onItemRegions} itemsEditable={!readingLabels} ready={ready} onHome={goHome} face={faceRef.current}
    onReadLabels={readingLabels ? undefined : target => { void readLabels(target); }} /></>;
  if (screen.kind === "processing") return <ProcessingView title={scannerById(screen.scanner).title}
    stage={(screen.scanner === "barcodes" || screen.scanner === "items") ? "Decoding barcodes…" : "Reading and checking the image…"} onCancel={goHome} />;

  if (screen.kind === "capture") {
    const s = screen.scanner;
    return (
      <div className="capture-screen" data-testid="capture" data-scanner={s}>
        {s === "liveness" || s === "faceid" || s === "facedoc" ? (
          <FaceFlow flow={s as FaceFlowId} face={faceClient()} scanner={client} captureClient={fastClient} onDone={onOutcome} />
        ) : s === "tables" ? (
          <FinancialCapture client={client} captureClient={fastClient} engine={financialEngine === "ppocr_v6_tiny_exposure" ? "ppocr_v6_tiny" : financialEngine} onDone={onOutcome} />
        ) : s === "items" ? (
          <ItemsCapture client={fastClient} onDone={onOutcome} />
        ) : s === "barcodes" || s === "labels" ? (
          <MultiBarcode client={fastClient} reader={client} labelEngine={labelEngine} labels={s === "labels"} onDone={onOutcome} />
        ) : s === "text" ? (
          <TextCapture client={client} captureClient={fastClient} engine={textEngine} onDone={onOutcome} />
        ) : s === "address" ? (
          <AddressCapture client={client} captureClient={fastClient} method={method} onDone={onAddress} />
        ) : (
          <IdCapture client={client} captureClient={fastClient} docType={s as DocType} onDone={idDone!} />
        )}
        <button type="button" className="back" data-testid="capture-home" onClick={goHome} aria-label={`Back to home from ${scannerById(s).title}`}>
          <span aria-hidden="true">‹</span> Back to home
        </button>
        {(s === "barcodes" || s === "labels" || s === "items") && <label className="photo-action capture-import">
          Import image
          <input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" multiple disabled={!ready}
            aria-label="Import barcode images or PDF" data-testid="capture-import"
            onChange={event => {
              const files = [...(event.target.files ?? [])];
              event.target.value = "";
              if (files.length) void onPhoto(s, files);
            }} />
        </label>}
      </div>
    );
  }

  return (
    <Home
      ready={ready}
      status={status}
      modelsState={modelsState}
      failed={failed}
      method={method}
      financialEngine={financialEngine}
      onFinancialEngine={setFinancialEngine}
      labelEngine={labelEngine}
      onLabelEngine={setLabelEngine}
      textEngine={textEngine}
      onTextEngine={setTextEngine}
      onMethod={setMethod}
      onOpen={open}
      onPhoto={onPhoto}
      busy={busy}
      photoError={photoError}
    />
  );
}
