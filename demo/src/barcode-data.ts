import { parseGs1 } from './gs1';
import type { SeenCode } from './outcome';
import type { Barcode } from './types';

/** Retain geometric/carrier evidence without copying binary payload buffers. */
export function describeBarcodes(codes: readonly (Pick<Barcode,'format'|'text'> & Partial<Pick<Barcode,'points'|'symbology_identifier'>> & {count?:number})[]): SeenCode[] {
  return codes.map(code => {
    const gs1=parseGs1(code.text,{symbologyIdentifier:code.symbology_identifier});
    return {format:code.format,text:code.text,count:code.count??1,
      ...(code.symbology_identifier?{symbology_identifier:code.symbology_identifier}:{}),
      ...(code.points?{points:code.points.map(p=>[p[0],p[1]] as [number,number])}:{}),
      ...(gs1.status!=='not_gs1'?{gs1}:{}),
    };
  });
}
