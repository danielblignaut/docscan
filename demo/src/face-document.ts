import type { PhotoFace } from "./face-types";

/** Workers cannot cancel inference, but a cancelled flow must not publish its answer. */
export async function readDocumentFace(
  imageUrl: string,
  pixels: (url: string) => Promise<ImageData>,
  read: (image: ImageData) => Promise<PhotoFace>,
  signal: AbortSignal,
): Promise<PhotoFace | null> {
  if (signal.aborted) return null;
  try {
    const image = await pixels(imageUrl);
    if (signal.aborted) return null;
    const face = await read(image);
    return signal.aborted ? null : face;
  } catch (error) {
    if (signal.aborted) return null;
    throw error;
  }
}
