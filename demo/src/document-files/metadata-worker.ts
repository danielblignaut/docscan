import { parseImageMetadata } from "./image.js";
self.onmessage = async event => {
  try { self.postMessage({ metadata: await parseImageMetadata(event.data.bytes, event.data.limits) }); }
  catch { self.postMessage({ error: "Unable to parse original image metadata. The file may be malformed or use an unsupported metadata encoding." }); }
};
