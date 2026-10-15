// The colour of the outlines drawn over the live camera, from explicit capture
// state rather than each frame's `accepted`, so it does not flicker:
//
// - grey: looking or tracking;
// - green: capture has started (the first frame that counts towards it) and
//   stays green through every frame after, and through flattening, OCR and
//   inference, until the flow moves on;
// - back to grey when the run breaks (a different reading, or too long
//   without one), and at the start of a flow's next step;
// - done: every step captured.
//
// Each transition is pushed to `window.__docscan.events` as
// `{ type: "outline", state }`, so the e2e suite can check the sequence.

export type OutlineState = "grey" | "green" | "done";

export const OUTLINE_COLOUR: Record<OutlineState, string> = {
  grey: "rgba(214, 219, 225, 0.85)",
  green: "#22c55e",
  done: "#22c55e",
};

type Docscan = { events: unknown[] };
const docscan = () => (window as unknown as { __docscan: Docscan }).__docscan;

/**
 * The current state, starting grey; `set` records a transition (a repeat of
 * the current state is ignored) and tells `onChange` (for the guide's border).
 */
export function outlineState(onChange: (s: OutlineState) => void) {
  let state: OutlineState = "grey";
  docscan().events.push({ type: "outline", state });
  onChange(state);
  return {
    get: () => state,
    set(next: OutlineState, detail: Record<string, unknown> = {}) {
      if (next === state) return;
      state = next;
      docscan().events.push({ type: "outline", state, ...detail });
      onChange(state);
    },
  };
}

/**
 * Draws one closed outline (screen points, CSS pixels) over the video, or
 * clears the overlay when there is none. Called once per analysed frame, so
 * the last outline stays drawn while the worker is busy.
 */
export function drawPolygon(canvas: HTMLCanvasElement | null, video: HTMLVideoElement, pts: [number, number][] | null, colour: string) {
  if (!canvas) return;
  const box = video.getBoundingClientRect();
  canvas.width = box.width * devicePixelRatio;
  canvas.height = box.height * devicePixelRatio;
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  if (!pts) return;
  ctx.strokeStyle = colour;
  ctx.lineWidth = 4;
  ctx.lineJoin = "round";
  ctx.beginPath();
  pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
  ctx.closePath();
  ctx.stroke();
}
