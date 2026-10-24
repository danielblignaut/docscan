/** Internal PDF.js protocol adapter; audit against the installed source on every upgrade.
 * PartialEvaluator._sendImgData sends null on XObject decode failure, including
 * globally cached failures/Type3 images. The display transport resolves that null
 * and CanvasGraphics skips it, even with stopAtErrors. No decoder reason survives.
 * Inline decoder errors already reject the operator list with stopAtErrors.
 */
export const PDFJS_IMAGE_PROTOCOL_VERSION = "6.4.299";
export function isFailedPdfImageMessage(message: unknown): boolean {
  if (!message || typeof message !== "object") return false;
  const { action, data } = message as { action?: unknown; data?: unknown };
  if (!Array.isArray(data)) return false;
  return (action === "obj" && data.length === 4 && data[2] === "Image" && data[3] === null)
    || (action === "commonobj" && data.length === 3 && data[1] === "Image" && data[2] === null);
}
