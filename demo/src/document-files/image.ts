import { DocumentFileError, MetadataBudget, bounded, entries } from "./common.js";
import type { Limits } from "./common.js";
import type { MetadataEvidence } from "./types.js";

const JPEG_SOF = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);
export function sniff(bytes: Uint8Array): string | null {
  if (bytes.length >= 8 && [137,80,78,71,13,10,26,10].every((v, i) => bytes[i] === v)) return "image/png";
  if (bytes.length >= 3 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return "image/jpeg";
  if (bytes.length >= 12 && ascii(bytes,0,4) === "RIFF" && ascii(bytes,8,12) === "WEBP") return "image/webp";
  // The PDF header may occur after a short binary transport prefix (PDF.js also accepts this).
  const prefix = ascii(bytes, 0, Math.min(bytes.length, 1024));
  if (/%PDF-\d\.\d/.test(prefix)) return "application/pdf";
  return null;
}
function ascii(bytes: Uint8Array, start: number, end: number): string { return String.fromCharCode(...bytes.subarray(start, end)); }
export function dimensions(bytes: Uint8Array, mime: string): { width: number; height: number; pixelCount: number } {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let width = 0, height = 0;
  if (mime === "image/png") {
    if (bytes.length < 33 || view.getUint32(8) !== 13 || ascii(bytes, 12, 16) !== "IHDR") throw malformed();
    width = view.getUint32(16); height = view.getUint32(20);
    let offset = 8, ended = false;
    while (offset + 12 <= bytes.length) {
      const length = view.getUint32(offset);
      if (length > bytes.length - offset - 12) throw malformed();
      if (ascii(bytes, offset+4, offset+8) === "IEND") { ended = true; break; }
      offset += length + 12;
    }
    if (!ended) throw malformed();
  } else if (mime === "image/jpeg") {
    let offset = 2;
    while (offset < bytes.length) {
      if (bytes[offset++] !== 255) throw malformed();
      while (bytes[offset] === 255) offset++;
      const marker = bytes[offset++];
      if (marker === 0xd9 || marker === 0xda) break;
      if (marker === 0x01 || marker >= 0xd0 && marker <= 0xd7) continue;
      if (offset+2 > bytes.length) throw malformed();
      const length = view.getUint16(offset);
      if (length < 2 || length > bytes.length-offset) throw malformed();
      if (JPEG_SOF.has(marker)) {
        if (length < 8) throw malformed();
        height = view.getUint16(offset+3); width = view.getUint16(offset+5);
      }
      offset += length;
    }
  } else if (mime === "image/webp") {
    if (bytes.length < 30 || view.getUint32(4, true)+8 > bytes.length) throw malformed();
    const chunk = ascii(bytes,12,16);
    if (chunk === "VP8X") {
      width = 1 + bytes[24] + (bytes[25]<<8) + (bytes[26]<<16);
      height = 1 + bytes[27] + (bytes[28]<<8) + (bytes[29]<<16);
    } else if (chunk === "VP8 " && bytes[23] === 0x9d && bytes[24] === 0x01 && bytes[25] === 0x2a) {
      width = view.getUint16(26,true)&0x3fff; height = view.getUint16(28,true)&0x3fff;
    } else if (chunk === "VP8L" && bytes[20] === 0x2f) {
      const packed = view.getUint32(21,true); width = (packed&0x3fff)+1; height = ((packed>>>14)&0x3fff)+1;
    }
  }
  if (!width || !height || !Number.isSafeInteger(width*height)) throw malformed();
  return { width, height, pixelCount: width*height };
}
function malformed(): DocumentFileError { return new DocumentFileError("malformed_image", "The image header or container is malformed. Supply the original JPEG, PNG or WebP file again."); }

const ALLOWED = new Set([
  "Make", "Model", "Software", "Orientation", "ImageWidth", "ImageHeight", "ExifImageWidth", "ExifImageHeight",
  "ColorSpace", "BitsPerSample", "Compression", "XResolution", "YResolution", "ResolutionUnit",
  "ExposureTime", "FNumber", "ISO", "FocalLength", "Flash", "WhiteBalance", "LensMake", "LensModel",
  "DateTimeOriginal", "CreateDate", "ModifyDate", "DateTimeDigitized", "OffsetTime", "OffsetTimeOriginal", "OffsetTimeDigitized",
  "CreatorTool", "MetadataDate", "DigitalSourceType", "Source", "OriginatingProgram", "ProgramVersion", "FileSource", "DateCreated", "TimeCreated", "DigitalCreationDate", "DigitalCreationTime",
  "width", "height", "bitDepth", "colorType", "compression", "filter", "interlace",
]);
/** Full parser is run in an owned, terminable browser Worker; only allowlisted fields leave it. */
export async function parseImageMetadata(bytes: Uint8Array, limits: Limits): Promise<MetadataEvidence> {
  const exifr = await import("exifr");
  const parse = exifr.parse ?? exifr.default.parse;
  const parserOptions = { tiff: true, xmp: true, iptc: true, ihdr: true,
    ifd0: {}, exif: true, gps: true, ifd1: false, icc: false, jfif: false,
    makerNote: false, userComment: false, mergeOutput: false, reviveValues: false, silentErrors: false };
  const raw: unknown = await parse(bytes, parserOptions);
  const budget = new MetadataBudget(limits);
  let gps = false, visited = 0;
  const walk = (value: unknown, path: string, depth: number) => {
    if (depth > 4) { budget.truncated = true; return; }
    for (const [key, item] of entries(value)) {
      if (++visited > 2048) { budget.truncated = true; return; }
      if (/gps|latitude|longitude|geotag/i.test(key)) { gps = true; continue; }
      if (ALLOWED.has(key)) budget.add(`${path}${key}`, item);
      else if (item && typeof item === "object" && !Array.isArray(item)) walk(item, `${path}${key}.`, depth+1);
    }
  };
  walk(raw, "", 0);
  return { status: "checked", fields: budget.fields, truncated: budget.truncated,
    gpsPresence: gps ? "present" : "not_observed", trust: "self_reported_unverified" };
}
export async function imageMetadata(bytes: Uint8Array, limits: Limits, signal?: AbortSignal): Promise<MetadataEvidence> {
  if (typeof Worker === "undefined") return bounded(parseImageMetadata(bytes, limits), limits.timeoutMs, signal);
  const worker = new Worker(new URL("./metadata-worker.ts", import.meta.url), { type: "module" });
  try {
    const promise = new Promise<MetadataEvidence>((resolve, reject) => {
      worker.onmessage = event => event.data.error ? reject(new DocumentFileError("metadata_parse_error", event.data.error)) : resolve(event.data.metadata);
      worker.onerror = () => reject(new DocumentFileError("metadata_parse_error", "The local image metadata worker failed."));
      worker.postMessage({ bytes, limits }, [bytes.buffer]);
    });
    return await bounded(promise, limits.timeoutMs, signal, () => worker.terminate());
  } finally { worker.terminate(); }
}
