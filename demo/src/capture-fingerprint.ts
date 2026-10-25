/** A local fingerprint of the exact resized RGBA view used by the decoder, not an authenticity assertion. */
export interface CaptureFingerprint {kind:'sha256_rgba8';sha256:string;width:number;height:number}
export async function fingerprintCapture(image:ImageData):Promise<CaptureFingerprint>{
 if(!Number.isInteger(image.width)||!Number.isInteger(image.height)||image.width<=0||image.height<=0||image.data.length!==image.width*image.height*4)throw Error('Invalid capture pixels');
 const hash=await crypto.subtle.digest('SHA-256',image.data.slice());
 return {kind:'sha256_rgba8',sha256:Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,'0')).join(''),width:image.width,height:image.height};
}
