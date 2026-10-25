/** Offline GS1 extraction. Parsed data is not issuer/product authenticity. */
import { GS1_DICTIONARY as DICTIONARY, GS1_DICTIONARY_REVISION } from './dictionary';

export interface Gs1Field {
  ai: string; title: string; value: string; start: number; end: number;
  checks: { format: boolean; checksum: boolean | null; calendar: boolean | null };
  date?: { yearTwoDigits: number; month: number; day: number | null; endOfMonth: boolean };
  decimal?: { value: string; unit: string | null; currencyCode?: string };
  errors: string[]; uncheckedRules: string[];
}
export interface Gs1Result {
  schemaVersion: 1; dictionaryRevision: string;
  status: 'not_gs1' | 'parsed' | 'incomplete' | 'invalid' | 'unsupported';
  syntax: 'element_string' | 'human_readable' | 'digital_link' | null;
  fields: Gs1Field[]; errors: string[]; warnings: string[];
  identifiers: Record<string, string>;
  interpretation: 'parsed_data_not_product_or_issuer_verification';
  validationScope: 'format_checksum_calendar_only';
}
export interface Gs1Options { symbologyIdentifier?: string | null; assumeGs1?: boolean }
const MARKERS = new Set([']C1', ']d2', ']d5', ']Q3', ']Q4']);
const CSET82 = new Set('!"%&\'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz');
const CSET39 = new Set('#-/0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ');
const MAX_INPUT = 8192, MAX_FIELDS = 128;
const NAMES: Record<string,string> = { '00':'sscc','01':'gtin','02':'containedGtin','10':'lot','21':'serial','22':'variant','240':'additionalProductId','241':'customerPartNumber','414':'gln','8004':'assetId','8040':'imei1','8041':'imei2','8042':'esimId','8043':'simId','30':'variableCount','37':'containedCount' };
const SIMPLE_LINTERS = new Set(['csum','yymmd0','yymmdd','nonzero','zero','nozeroprefix','yesno']);
const has = (key: string) => Object.hasOwn(DICTIONARY,key);
const matchesAi = (ai: string, pattern: string) => ai.length === pattern.length && [...pattern].every((c,i) => c === 'n' || c === ai[i]);
export function gs1Checksum(value: string): boolean {
  return /^\d{2,18}$/.test(value) && [...value].reverse().reduce((n,c,i) => n+Number(c)*(i%2 ? 3:1),0)%10 === 0;
}
function calendar(value: string, allowZero: boolean) {
  if (!/^\d{6}$/.test(value)) return null;
  const yy=Number(value.slice(0,2)), month=Number(value.slice(2,4)), day=Number(value.slice(4));
  const days=[31,yy%4===0?29:28,31,30,31,30,31,31,30,31,30,31];
  if(month<1||month>12||day>days[month-1]||day< (allowZero?0:1))return null;
  return {yearTwoDigits:yy,month,day:day||null,endOfMonth:day===0};
}
function decimal(value: string, scale: number): string {
  const padded=value.padStart(scale+1,'0'),cut=padded.length-scale;
  return (padded.slice(0,cut).replace(/^0+(?=\d)/,'')||'0')+(scale?'.'+padded.slice(cut):'');
}
function checkField(ai: string,value: string,start: number,end: number): Gs1Field {
  const def=DICTIONARY[ai];
  const field:Gs1Field={ai,title:def.title,value,start,end,checks:{format:true,checksum:null,calendar:null},errors:[],uncheckedRules:[]};
  let at=0;
  for(const component of def.components){
    if(component.optional&&at===value.length)continue;
    const part=value.slice(at,at+component.max);at+=part.length;
    const validCharacters=component.kind==='N'?/^\d*$/.test(part):component.kind==='Z'?(/^[A-Za-z0-9_-]*={0,2}$/.test(part)&&(!part.includes('=')||part.length%3===0)):[...part].every(c=>(component.kind==='Y'?CSET39:CSET82).has(c));
    if(part.length<component.min||!validCharacters)field.errors.push('invalid_component_format');
    for(const rule of component.linters){
      if(!SIMPLE_LINTERS.has(rule)){field.uncheckedRules.push(rule);continue;}
      if(rule==='csum'){
        const valid=gs1Checksum(part);field.checks.checksum=(field.checks.checksum??true)&&valid;
        if(!valid)field.errors.push('invalid_check_digit');
      }else if(rule==='yymmd0'||rule==='yymmdd'){
        const date=calendar(part,rule==='yymmd0');field.checks.calendar=(field.checks.calendar??true)&&date!==null;
        if(!date)field.errors.push('invalid_calendar_date');else if(def.components.filter(c=>c.linters.some(l=>l==='yymmd0'||l==='yymmdd')).length===1)field.date=date;
      }else if(rule==='nonzero'&&!/[1-9]/.test(part))field.errors.push('zero_not_allowed');
      else if(rule==='zero'&&!/^0+$/.test(part))field.errors.push('must_be_zero');
      else if(rule==='nozeroprefix'&&part.length>1&&part[0]==='0')field.errors.push('leading_zero_not_allowed');
      else if(rule==='yesno'&&!/^[01]$/.test(part))field.errors.push('expected_zero_or_one');
    }
  }
  if(at!==value.length)field.errors.push('invalid_length');
  field.checks.format=!field.errors.some(e=>e==='invalid_component_format'||e==='invalid_length');
  if(!field.errors.length&&/^3[1-6]\d[0-5]$/.test(ai)&&/^\d{6}$/.test(value)) {
    const units:Record<string,string>={'310':'kg','311':'m','312':'m','313':'m','314':'m²','315':'l','316':'m³','320':'lb'};
    field.decimal={value:decimal(value,Number(ai[3])),unit:units[ai.slice(0,3)]??null};
  }
  if(!field.errors.length&&/^39[0-3][0-9]$/.test(ai)&&/^\d+$/.test(value)){
    const currency=ai[2]==='1'||ai[2]==='3';field.decimal={value:decimal(currency?value.slice(3):value,Number(ai[3])),unit:null,...(currency?{currencyCode:value.slice(0,3)}:{})};
  }
  field.errors=[...new Set(field.errors)];field.uncheckedRules=[...new Set(field.uncheckedRules)];
  return field;
}

/** No network requests, resolver calls, percent-decoding of element strings, or guessed separators. */
export function parseGs1(input: string, options: Gs1Options = {}): Gs1Result {
  const result:Gs1Result={schemaVersion:1,dictionaryRevision:GS1_DICTIONARY_REVISION,status:'not_gs1',syntax:null,fields:[],errors:[],warnings:[],identifiers:{},interpretation:'parsed_data_not_product_or_issuer_verification',validationScope:'format_checksum_calendar_only'};
  if(typeof input!=='string'||input.length>MAX_INPUT){result.status='invalid';result.errors.push('input_limit');return result;}
  const append=(ai:string,value:string,start:number,end:number)=>{
    if(result.fields.length>=MAX_FIELDS){result.errors.push('field_limit');return false;}
    if(!has(ai)){result.errors.push(`unsupported_ai:${ai}`);return false;}
    result.fields.push(checkField(ai,value,start,end));return true;
  };
  if(/^https?:\/\//i.test(input)){
    let url:URL;try{url=new URL(input);}catch{return result;}
    const segments=url.pathname.split('/').filter(Boolean);
    const first=segments.findIndex(s=>has(s)&&Object.hasOwn(DICTIONARY[s].attributes,'dlpkey'));
    if(first<0)return result;
    result.syntax='digital_link';
    const rawUri=/^https?:\/\/([^/?#]*)([^?#]*)(?:\?[^#]*)?(?:#.*)?$/i.exec(input);
    const rawPath=rawUri?.[2]??'';
    if(!rawUri||rawPath!==url.pathname||rawPath.includes('//')||input.includes('\\')){
      result.status='invalid';result.errors.push('noncanonical_uri_path');return result;
    }
    const pathStart=input.indexOf('://')+3+rawUri[1].length;
    const rawSegments=[...rawPath.matchAll(/[^/]+/g)];
    if(/%(?![0-9a-fA-F]{2})/.test(input))result.errors.push('invalid_percent_encoding');
    if(url.username||url.password||url.hash)result.errors.push('unsupported_uri_credentials_or_fragment');
    const path=segments.slice(first);
    if(path.length%2)result.errors.push('unpaired_path_segment');
    const pathAis:string[]=[];

    for(let i=0;i+1<path.length;i+=2){
      const ai=path[i],encoded=path[i+1];pathAis.push(ai);
      const start=pathStart+rawSegments[first+i+1].index!;
      try{append(ai,decodeURIComponent(encoded),start,start+encoded.length);}catch{result.errors.push('invalid_percent_encoding');}
    }
    const primary=DICTIONARY[pathAis[0]];
    const variants=primary?.attributes.dlpkey?.[0]?.split('|').map(v=>v?v.split(','):[])??[];
    if(!variants.some(v=>{
      let prev=-1;return pathAis.slice(1).every(ai=>{const next=v.indexOf(ai);const valid=next>prev;prev=next;return valid;});
    }))result.errors.push('invalid_digital_link_qualifier_order');
    for(const pair of url.search.slice(1).split('&').filter(Boolean)){
      const at=pair.indexOf('=');
      let ai:string,value:string;
      try{ai=decodeURIComponent(at<0?pair:pair.slice(0,at));value=decodeURIComponent(at<0?'':pair.slice(at+1));}
      catch{result.errors.push('invalid_percent_encoding');continue;}
      if(!/^\d{2,4}$/.test(ai))continue;
      if(!has(ai)){result.errors.push(`unsupported_ai:${ai}`);continue;}
      if(!DICTIONARY[ai].digitalAttribute)result.errors.push(`ai_not_digital_link_attribute:${ai}`);
      append(ai,value,-1,-1); // query offsets aren't equivalent after URL decoding
    }
    result.warnings.push('uri_parsed_without_resolving_or_trusting_host');
  }else if(/^\(\d{2,4}\)/.test(input)){
    result.syntax='human_readable';
    const tokens=[...input.matchAll(/\((\d{2,4})\)/g)];
    for(let i=0;i<tokens.length;i++){
      const t=tokens[i],start=t.index!+t[0].length,end=tokens[i+1]?.index??input.length;
      append(t[1],input.slice(start,end),start,end);
    }
    result.warnings.push('human_readable_ai_not_proof_of_gs1_carrier');
  }else{
    let text=input,offset=0;
    const prefix=MARKERS.has(text.slice(0,3))?text.slice(0,3):null;
    const metadata=options.symbologyIdentifier;
    if(metadata&&!MARKERS.has(metadata))return result;
    if(!prefix&&!MARKERS.has(metadata??'')&&!options.assumeGs1)return result;
    if(prefix){text=text.slice(3);offset=3;}
    result.syntax='element_string';
    while(text.length){
      if(text[0]==='\x1d'){result.errors.push('unexpected_separator');break;}
      const ai=[4,3,2].map(n=>text.slice(0,n)).find(key=>has(key));
      if(!ai){result.errors.push(`unsupported_ai_at:${offset}`);break;}
      const def=DICTIONARY[ai],size=def.components.reduce((n,c)=>n+c.max,0);
      const body=text.slice(ai.length),separator=body.indexOf('\x1d');
      const count=def.predefined?size:separator<0?body.length:separator;
      if(body.length<count){append(ai,body,offset+ai.length,input.length);result.errors.push('truncated_value');break;}
      if(!append(ai,body.slice(0,count),offset+ai.length,offset+ai.length+count))break;
      const consumed=ai.length+count;text=text.slice(consumed);offset+=consumed;
      if(text[0]==='\x1d'){text=text.slice(1);offset++;if(!text.length)result.warnings.push('trailing_separator');}
    }
  }
  if(!result.syntax)return result;
  const seen=new Set<string>();
  for(const field of result.fields){
    if(seen.has(field.ai))result.errors.push(`duplicate_ai:${field.ai}`);seen.add(field.ai);
    for(const e of field.errors)result.errors.push(`${field.ai}:${e}`);
    if(field.uncheckedRules.length)result.warnings.push(`${field.ai}:additional_rules_not_checked:${field.uncheckedRules.join(',')}`);
    if(field.date)result.warnings.push('two_digit_year_requires_century_policy');
  }
  let missingRelated=false;
  const identifiers:Record<string,string>={};
  for(const field of result.fields){
    const attrs=DICTIONARY[field.ai].attributes;
    for(const req of attrs.req??[]){
      if(!req.split(',').some(group=>group.split('+').every(pattern=>[...seen].some(ai=>matchesAi(ai,pattern))))){missingRelated=true;result.warnings.push(`${field.ai}:required_related_ai_not_present:${req}`);}
    }
    for(const ex of attrs.ex??[]){
      if(ex.split(',').some(pattern=>[...seen].some(ai=>ai!==field.ai&&matchesAi(ai,pattern))))result.errors.push(`${field.ai}:incompatible_ai_combination`);
    }
    const name=NAMES[field.ai];
    if(name&&!field.errors.length&&result.fields.filter(f=>f.ai===field.ai).length===1)identifiers[name]=field.value;
  }
  result.errors=[...new Set(result.errors)];result.warnings=[...new Set(result.warnings)];
  result.status=result.errors.some(e=>e.startsWith('unsupported_ai'))?'unsupported':result.errors.length?'invalid':missingRelated?'incomplete':'parsed';
  if(result.status==='parsed')result.identifiers=identifiers;
  return result;
}
