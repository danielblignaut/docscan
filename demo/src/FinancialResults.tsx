import { financialTableCsv, type FinancialTablesOptions, type CellValue } from './financial-tables';
import type { Outcome } from './outcome';

type Financial=Extract<Outcome,{kind:'financial'}>;
function normalized(value:CellValue){return value.type==='text'?null:value.type==='date'?value.iso:value.value;}
function download(text:string,name:string){
  const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
export function FinancialResults({outcome,onOptions}:{outcome:Financial;onOptions?:(outcome:Financial,options:FinancialTablesOptions)=>void}){
  const r=outcome.report,options=outcome.options;
  const fileIndices=[...new Set(outcome.pages.map(p=>p.fileIndex))].sort((a,b)=>a-b);
  return <section data-testid="financial-results">
    <p><strong>{r.tables.length} table{r.tables.length===1?'':'s'} · {r.status}</strong></p>
    <p>These checks compare extracted numbers. They do not verify the bank, employer, document authenticity or income.</p>
    {r.checks.some(c=>c.status==='inconsistent')&&<p role="alert">Some extracted numbers do not reconcile. OCR can misread digits or decimal points; compare the cited source values before using this data.</p>}
    {onOptions&&<div className="financial-options">
      <label>Date order <select aria-label="Financial date order" value={options.dateOrder??'auto'} onChange={e=>onOptions(outcome,{...options,dateOrder:e.target.value==='auto'?undefined:e.target.value as 'DMY'|'MDY'|'YMD'})}>
        <option value="auto">Infer only when unambiguous</option><option value="DMY">Day / month / year</option><option value="MDY">Month / day / year</option><option value="YMD">Year / month / day</option>
      </select></label>
      <label>Decimal separator <select aria-label="Financial decimal separator" value={options.decimalSeparator??'auto'} onChange={e=>onOptions(outcome,{...options,decimalSeparator:e.target.value==='auto'?undefined:e.target.value as '.'|','})}>
        <option value="auto">Infer only when unambiguous</option><option value=".">Decimal point</option><option value=",">Decimal comma</option>
      </select></label>
      <label>Currency for unmarked amounts <input aria-label="Financial currency" placeholder="e.g. ZAR" value={options.defaultCurrency??''} maxLength={3} onChange={e=>onOptions(outcome,{...options,defaultCurrency:e.target.value.toUpperCase()||undefined})}/></label>
      {fileIndices.length>1 && r.tables.some(t=>t.documentKind === "bank_statement") && <label><input type="checkbox" aria-label="Statements belong to the same account"
        checked={options.sameAccountFiles?.some(g=>fileIndices.every(i=>g.includes(i)))??false}
        onChange={e=>onOptions(outcome,{...options,sameAccountFiles:e.target.checked?[fileIndices]:undefined})}/>
        I have checked that these files are statements for the same account. Compare their periods and recurring credits together.
      </label>}
    </div>}
    {r.abstentions.map((a,i)=><p key={i} role="status">Not extracted{a.pageIndex===null?'':` on page ${a.pageIndex+1}`}: {a.detail}</p>)}
    {r.ambiguities.length>0&&<details open><summary>Ambiguities to review ({r.ambiguities.length})</summary><ul>{r.ambiguities.map((a,i)=><li key={i}>{a.detail}</li>)}</ul></details>}
    {r.tables.map(table=><section className="group" key={table.id} data-testid="financial-table">
      <h2>{table.documentKind.replaceAll('_',' ')} · {table.rows.length} rows · {table.status}</h2>
      <button type="button" onClick={()=>download(financialTableCsv(table),`${table.kind}-${table.id}.csv`)}>Download this table as CSV</button>
      <div className="table-scroll"><table><thead><tr><th>Page</th>{table.columns.map(c=><th key={c.key}>{c.label}</th>)}</tr></thead><tbody>
        {table.rows.map(row=><tr key={row.id}><td>{row.pageIndex+1}</td>{table.columns.map(column=>{
          const cell=row.cells.find(c=>c.column===column.key);if(!cell)return <td key={column.key}/>;
          const value=normalized(cell.value),bad=cell.issues.length||('status' in cell.value&&cell.value.status!=='parsed');
          return <td key={column.key} className={bad?'cell-review':undefined}><span>{value??cell.text}</span>
            <details><summary>Source</summary><p>{cell.text}</p><small>Page {cell.source.pageIndex+1}, text boxes {cell.source.lineIndices.map(i=>i+1).join(', ')}{cell.source.approximate?' · approximate positions':''}</small>
              {cell.issues.length>0&&<p>{cell.issues.join('; ')}</p>}
            </details></td>;
        })}</tr>)}
      </tbody></table></div>
    </section>)}
    <section className="group"><h2>Arithmetic checks</h2>
      {!r.checks.length&&<p>No supported check has enough extracted evidence.</p>}
      <ul>{r.checks.map(check=><li key={check.id}><strong>{check.code.replaceAll('_',' ')}: {check.status.replaceAll('_',' ')}</strong> · {check.completeness}<p>{check.reason}</p>
        {check.expected!==null&&<small>Expected {check.expected}; observed {check.observed??'unknown'}</small>}
      </li>)}</ul>
    </section>
    {r.classifications.length>0&&<details><summary>Provisional transaction labels</summary><ul>{r.classifications.map(c=><li key={c.rowId}>{c.rowId}: {c.label.replaceAll('_',' ')}{c.alternatives.length>1?' · multiple interpretations':''}</li>)}</ul></details>}
    {r.observations.length>0&&<section className="group"><h2>Possible patterns to review</h2><ul>{r.observations.map(o=><li key={o.id}>{o.summary}<p className="muted">{o.limitations.join(' ')}</p></li>)}</ul></section>}
    <details><summary>Source pages</summary>{outcome.pages.map(p=><div key={p.pageIndex}><p>Page {p.pageIndex+1}{p.input?` · ${p.input.name}`:''}. Positions refer to processed OCR pixels.</p><img className="captured" src={p.imageUrl} alt={`Financial page ${p.pageIndex+1}`}/></div>)}</details>
    <details><summary>Extraction limitations and issues</summary><ul>{r.issues.map((i,n)=><li key={n}>{i.detail}</li>)}{r.limitations.map(l=><li key={l}>{l}</li>)}</ul></details>
  </section>;
}
