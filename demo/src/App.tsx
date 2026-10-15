// Three screens: home (a card per scanner), the full-screen camera, and the
// results form. The URL names the scanner (`?doc=…`, `?mode=…`), so a deep
// link opens its camera directly; Back to home always returns to the menu.
import { useCallback, useEffect, useMemo, useState } from "react";
import type { AddressCaptured } from "./AddressCapture";
import { AddressCapture } from "./AddressCapture";
import { Home } from "./Home";
import { type Captured, type DocType, IdCapture } from "./IdCapture";
import { MultiBarcode } from "./MultiBarcode";
import type { Extractor } from "./models";
import type { CaptureMeta, Outcome, ReadyInfo } from "./outcome";
import { analysePhotos } from "./photo";
import { Results } from "./Results";
import { ScannerClient } from "./scanner-client";
import { methodFromUrl, type ScannerId, scannerById, scannerFromUrl, urlFor } from "./scanners";

(window as unknown as { __docscan: { events: unknown[]; frames: unknown[]; ready?: unknown } }).__docscan = { events: [], frames: [] };

type Screen = { kind: "home" } | { kind: "capture"; scanner: ScannerId } | { kind: "results"; outcome: Outcome };

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
  const [status, setStatus] = useState("Loading the scanner…");
  const [ready, setReady] = useState<ReadyInfo | null>(null);
  const [failed, setFailed] = useState(false);
  const [screen, setScreen] = useState<Screen>(screenFromUrl);
  const [method, setMethod] = useState<Extractor | "auto">(methodFromUrl);
  const [busy, setBusy] = useState<ScannerId | null>(null);
  const [photoError, setPhotoError] = useState<{ id: ScannerId; message: string } | null>(null);

  useEffect(() => {
    client.ready
      .then((r) => {
        setReady(r);
        setStatus(`Scanner ready in ${Math.round(r.loadMs)} ms · ${r.threads} thread${r.threads > 1 ? "s" : ""}${r.tagger ? " · tagger" : ""}`);
        (window as unknown as { __docscan: { ready?: unknown } }).__docscan.ready = r;
      })
      .catch((e) => {
        setFailed(true);
        setStatus(`Scanner failed: ${e}`);
      });
  }, [client]);

  // Model download progress, and a request that the browser keep the cached models.
  useEffect(() => {
    client.onProgress = (p) => {
      if (!p.cached && p.total) setStatus(`Downloading ${p.file}: ${Math.round((100 * p.loaded) / p.total)}%`);
    };
    void navigator.storage?.persist?.().catch(() => false);
  }, [client]);

  // The browser's own Back (and Android's) follows the URL.
  useEffect(() => {
    const onPop = () => setScreen(screenFromUrl());
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  // Each screen starts at the top.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [screen.kind]);

  const open = useCallback(
    (scanner: ScannerId) => {
      history.pushState(PUSHED, "", urlFor(scanner, method));
      setScreen({ kind: "capture", scanner });
    },
    [method],
  );

  /** Unmounting the capture screen stops its camera. */
  const goHome = useCallback(() => {
    setScreen({ kind: "home" });
    if (history.state === PUSHED) history.back();
    else history.replaceState(null, "", urlFor(null));
  }, []);

  const onId = useCallback(
    (scanner: ScannerId) => (captured: Captured[], meta: CaptureMeta) => setScreen({ kind: "results", outcome: { kind: "id", scanner, captured, meta } }),
    [],
  );
  const onAddress = useCallback((captured: AddressCaptured, meta: CaptureMeta) => setScreen({ kind: "results", outcome: { kind: "address", captured, meta } }), []);
  const onOutcome = useCallback((outcome: Outcome) => setScreen({ kind: "results", outcome }), []);
  const capturing = screen.kind === "capture" ? screen.scanner : null;
  // Stable per scanner: the capture restarts when its callback changes.
  const idDone = useMemo(() => (capturing ? onId(capturing) : null), [capturing, onId]);

  async function onPhoto(id: ScannerId, files: File[]) {
    setBusy(id);
    setPhotoError(null);
    try {
      const outcome = await analysePhotos(client, id, files, method);
      history.pushState(PUSHED, "", urlFor(id, method));
      setScreen({ kind: "results", outcome });
    } catch (e) {
      setPhotoError({ id, message: `Could not read the photo: ${e instanceof Error ? e.message : String(e)}` });
    } finally {
      setBusy(null);
    }
  }

  if (screen.kind === "results") return <Results outcome={screen.outcome} ready={ready} onHome={goHome} />;

  if (screen.kind === "capture") {
    const s = screen.scanner;
    return (
      <div className="capture-screen" data-testid="capture" data-scanner={s}>
        {s === "barcodes" || s === "labels" ? (
          <MultiBarcode client={client} labels={s === "labels"} onDone={onOutcome} />
        ) : s === "address" ? (
          <AddressCapture client={client} method={method} onDone={onAddress} />
        ) : (
          <IdCapture client={client} docType={s as DocType} onDone={idDone!} />
        )}
        <button type="button" className="back" data-testid="capture-home" onClick={goHome} aria-label={`Back to home from ${scannerById(s).title}`}>
          <span aria-hidden="true">‹</span> Back to home
        </button>
      </div>
    );
  }

  return (
    <Home
      ready={ready}
      status={status}
      failed={failed}
      method={method}
      onMethod={setMethod}
      onOpen={open}
      onPhoto={onPhoto}
      busy={busy}
      photoError={photoError}
    />
  );
}
