// Camera helpers: open the rear camera at a document-friendly resolution, and
// crop the part of the frame under the on-screen guide.

export async function openCamera(): Promise<MediaStream> {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new Error("The camera needs https or localhost.");
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      facingMode: { ideal: "environment" },
      width: { ideal: 1920 },
      height: { ideal: 1080 },
    },
  });
  const [track] = stream.getVideoTracks();
  // Close-up documents defeat fixed-focus defaults; ask for continuous focus
  // where the browser supports it.
  const caps = (track.getCapabilities?.() ?? {}) as { focusMode?: string[] };
  if (caps.focusMode?.includes("continuous")) {
    await track.applyConstraints({ advanced: [{ focusMode: "continuous" } as MediaTrackConstraintSet] }).catch(() => {});
  }
  return stream;
}

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * The guide rectangle in the video's own pixels. The video is drawn with
 * `object-fit: cover`, so part of it is cropped off-screen; the guide is a
 * CSS box inside the same container.
 */
export function guideInVideo(video: HTMLVideoElement, guide: HTMLElement, margin = 0.08): Rect {
  const box = video.getBoundingClientRect();
  const g = guide.getBoundingClientRect();
  const scale = Math.max(box.width / video.videoWidth, box.height / video.videoHeight);
  const offX = (video.videoWidth * scale - box.width) / 2;
  const offY = (video.videoHeight * scale - box.height) / 2;
  const mx = g.width * margin;
  const my = g.height * margin;
  const x = (g.left - box.left - mx + offX) / scale;
  const y = (g.top - box.top - my + offY) / scale;
  const w = (g.width + 2 * mx) / scale;
  const h = (g.height + 2 * my) / scale;
  const cx = Math.max(0, x);
  const cy = Math.max(0, y);
  return {
    x: cx,
    y: cy,
    w: Math.min(video.videoWidth - cx, w),
    h: Math.min(video.videoHeight - cy, h),
  };
}

const work = document.createElement("canvas");
const workCtx = work.getContext("2d", { willReadFrequently: true })!;

/** Pixels of `rect` from the video, scaled down to at most `maxWidth`. */
export function grab(source: CanvasImageSource, rect: Rect, maxWidth = 1280): ImageData {
  const scale = Math.min(1, maxWidth / rect.w);
  work.width = Math.round(rect.w * scale);
  work.height = Math.round(rect.h * scale);
  workCtx.drawImage(source, rect.x, rect.y, rect.w, rect.h, 0, 0, work.width, work.height);
  return workCtx.getImageData(0, 0, work.width, work.height);
}

/** Pixels of `rect` at the video's full resolution. */
export function grabFull(source: CanvasImageSource, rect: Rect): ImageData {
  return grab(source, rect, Number.POSITIVE_INFINITY);
}

export async function toJpeg(image: ImageData): Promise<Blob> {
  const c = document.createElement("canvas");
  c.width = image.width;
  c.height = image.height;
  c.getContext("2d")!.putImageData(image, 0, 0);
  return new Promise((resolve, reject) =>
    c.toBlob((b) => (b ? resolve(b) : reject(new Error("encode failed"))), "image/jpeg", 0.92),
  );
}

/** Maps a point in the analysed crop to CSS pixels over a `object-fit: cover` video. */
export function cropToScreen(video: HTMLVideoElement, rect: Rect, analysedWidth: number, [x, y]: [number, number]): [number, number] {
  const box = video.getBoundingClientRect();
  const scale = Math.max(box.width / video.videoWidth, box.height / video.videoHeight);
  const offX = (video.videoWidth * scale - box.width) / 2;
  const offY = (video.videoHeight * scale - box.height) / 2;
  const k = rect.w / analysedWidth;
  return [(rect.x + x * k) * scale - offX, (rect.y + y * k) * scale - offY];
}

/** A full-resolution JPEG of `rect`, for the captured document image. */
export async function still(source: CanvasImageSource, rect: Rect): Promise<Blob> {
  const c = document.createElement("canvas");
  c.width = Math.round(rect.w);
  c.height = Math.round(rect.h);
  c.getContext("2d")!.drawImage(source, rect.x, rect.y, rect.w, rect.h, 0, 0, c.width, c.height);
  return new Promise((resolve, reject) =>
    c.toBlob((b) => (b ? resolve(b) : reject(new Error("encode failed"))), "image/jpeg", 0.92),
  );
}
