import { extractFinancialTables, type FinancialPageInput, type FinancialTablesOptions, type FinancialTablesReport } from './financial-tables';
import type { TextResult } from './TextCapture';
import type { InputReference } from './document-review';

export interface FinancialCapturedPage {
  pageIndex:number; fileIndex:number; reading:TextResult; imageUrl:string; input?:InputReference;
}
export function financialInputs(pages:FinancialCapturedPage[]):FinancialPageInput[] {
  return pages.map(page=>({pageIndex:page.pageIndex,fileIndex:page.fileIndex,
    lines:('words' in page.reading && page.reading.words.length ? page.reading.words : page.reading.lines).map(line=>({text:line.text,x:line.x,y:line.y,w:line.w,h:line.h,...('line' in line && typeof line.line === 'number' ? {line:line.line}:{})})),
    width:page.reading.page_size[0],height:page.reading.page_size[1],inputReference:page.input?`${page.input.name} · file ${page.input.fileIndex+1} · page ${(page.input.pageIndex??0)+1}`:null,source:'engine' in page.reading ? 'ppocr_v6_tiny_lines_original_pixels' : 'ocrs_words_processed_pixels',trust:'extracted_unverified'}));
}
export function readFinancialPages(pages:FinancialCapturedPage[], options:FinancialTablesOptions={}, incompleteInputs=0):FinancialTablesReport {
  const failedPages=options.failedPages?.length ? options.failedPages : incompleteInputs ? [{pageIndex:null,fileIndex:null,reason:`${incompleteInputs} input page/file records failed or were incomplete.`}] : [];
  return extractFinancialTables(financialInputs(pages),{...options,failedPages,source:'ocr',trustStatus:'extracted_unverified'});
}
