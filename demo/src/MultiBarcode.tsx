import { useEffect, useRef, useState } from "react";
import { grab, openCamera } from "./camera";
import type { ScannerClient } from "./scanner-client";
import type { Barcode } from "./types";

interface Seen {
  format: string;
  text: string;
  /** Frames the code was read in. */
  count: number;
}

/**
 * A code is listed once read in this many frames. rxing occasionally reports
 * a spurious short code (a UPC-E inside a dense symbol) in a single frame; a
 * real code in view is read again in the next.
 */
const CONFIRM_FRAMES = 2;
/** Analyse up to this width: small codes need every pixel the camera gives. */
const MAX_WIDTH = 1920;

/** Reads every barcode in the full frame, outlines each, and keeps a running list. */
export function MultiBarcode({ client }: { client: ScannerClient }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const [seen, setSeen] = useState<Seen[]>([]);
  const [rate, setRate] = useState({ ms: 0, inFrame: 0 });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let stopped = false;
    const all = new Map<string, Seen>();

    async function loop() {
      const video = videoRef.current;
      const overlay = overlayRef.current;
      if (stopped) return;
      if (!video || !overlay || video.readyState < 2 || client.busy) {
        requestAnimationFrame(loop);
        return;
      }
      const rect = { x: 0, y: 0, w: video.videoWidth, h: video.videoHeight };
      const image = grab(video, rect, MAX_WIDTH);
      const scale = image.width / video.videoWidth;
      try {
        const { result, ms } = await client.run<Barcode[]>({ kind: "barcodes", image, formats: [] });
        if (stopped) return;
        draw(video, overlay, result, scale);
        const confirmed: Barcode[] = [];
        for (const b of result) {
          const key = `${b.format}|${b.text}`;
          const s = all.get(key) ?? { format: b.format, text: b.text, count: 0 };
          s.count++;
          all.set(key, s);
          if (s.count === CONFIRM_FRAMES) confirmed.push(b);
        }
        const ds = (window as unknown as { __docscan: { events: unknown[]; frames: unknown[] } }).__docscan;
        ds.frames.push({ ms, size: [image.width, image.height], read: result.length });
        if (confirmed.length) {
          ds.events.push({ type: "barcodes", barcodes: confirmed.map(({ format, text }) => ({ format, text })) });
        }
        setSeen([...all.values()]);
        setRate({ ms: Math.round(ms), inFrame: result.length });
      } catch (e) {
        setError(String(e));
      }
      requestAnimationFrame(loop);
    }

    openCamera()
      .then((s) => {
        stream = s;
        if (videoRef.current) {
          videoRef.current.srcObject = s;
          void videoRef.current.play();
        }
        requestAnimationFrame(loop);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    return () => {
      stopped = true;
      for (const t of stream?.getTracks() ?? []) t.stop();
    };
  }, [client]);

  return (
    <div className="capture">
      <div className="viewport">
        <video ref={videoRef} playsInline muted />
        <canvas ref={overlayRef} className="overlay" />
        <div className="hint">{error ?? `${rate.inFrame} in frame · ${rate.ms} ms per frame`}</div>
      </div>
      <ul className="codes" data-testid="codes">
        {seen.map((s) => (
          <li key={`${s.format}|${s.text}`} className={s.count < CONFIRM_FRAMES ? "pending" : undefined}>
            <b>{s.format}</b> <code>{s.text}</code> <small>×{s.count}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Maps analysis-image points to the on-screen video (object-fit: cover) and outlines each code. */
function draw(video: HTMLVideoElement, canvas: HTMLCanvasElement, codes: Barcode[], scale: number) {
  const box = video.getBoundingClientRect();
  canvas.width = box.width * devicePixelRatio;
  canvas.height = box.height * devicePixelRatio;
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  const s = Math.max(box.width / video.videoWidth, box.height / video.videoHeight);
  const offX = (video.videoWidth * s - box.width) / 2;
  const offY = (video.videoHeight * s - box.height) / 2;
  const map = ([x, y]: [number, number]) => [(x / scale) * s - offX, (y / scale) * s - offY] as const;
  ctx.lineWidth = 3;
  ctx.font = "600 13px system-ui";
  for (const c of codes) {
    if (!c.points.length) continue;
    const pts = c.points.map(map);
    ctx.strokeStyle = "#22c55e";
    ctx.beginPath();
    if (pts.length <= 2) {
      // 1D codes report scan-line end points: draw a bar across them.
      const [a, b] = [pts[0], pts[pts.length - 1]];
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
    } else {
      pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
    }
    ctx.stroke();
    const [lx, ly] = pts[0];
    const label = `${c.format}: ${c.text.slice(0, 24)}`;
    ctx.fillStyle = "rgba(0,0,0,.7)";
    ctx.fillRect(lx, ly - 18, ctx.measureText(label).width + 8, 18);
    ctx.fillStyle = "#fff";
    ctx.fillText(label, lx + 4, ly - 5);
  }
}
