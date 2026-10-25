import type {ScannerId} from './scanners';
import type {TextEngine} from './text-engine';
import type {LabelEngine} from './label-engine';
export type ReaderRoute='capture'|'paddle'|'documents';
/** Only the selected workflow loads weights. No accuracy policy is chosen from device hints. */
export function readerRoute(scanner:ScannerId, text:TextEngine, financial:TextEngine, labels:LabelEngine):ReaderRoute{
 if(scanner==='barcodes'||scanner==='items')return 'capture';
 if(scanner==='labels'&&labels==='fast')return 'paddle';
 if(scanner==='text'&&text!=='ocrs')return 'paddle';
 if(scanner==='tables'&&financial!=='ocrs')return 'paddle';
 return 'documents';
}

/** Tiny line-by-line OCR defaults to one thread; retain bounded explicit benchmark overrides. */
export function paddleThreadCount(search=location.search):number{
 const asked=Number(new URLSearchParams(search).get('threads'));
 return Number.isInteger(asked)&&asked>0&&asked<=32?asked:1;
}
