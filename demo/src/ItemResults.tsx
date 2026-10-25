import { useRef, useState } from 'react';
import { outcomeGrouping, savedItemSession } from './item-data';
import type { ItemRegion, KeyedRole } from './item-grouping';
import type { Outcome } from './outcome';

type Reading=Extract<Outcome,{kind:'barcodes'}>;
const ROLES:KeyedRole[]=['gtin','imei1','imei2','serial'];
const title=(role:string)=>role==='serial'?'SN':role.toUpperCase();
export function ItemSessionResults({outcome}:{outcome:Outcome}){
  const result=savedItemSession(outcome);
  return <section className="group" data-testid="item-session-results"><h2>Identifiers across saved views</h2>
    <p>Groups are candidates for review. Repeated reads and repeated GTINs are not quantities. Each saved view contributes once, even after OCR is added.</p>
    {Object.values(result.losses).some(n=>n>0)&&<p role="status">Partial item session: bounded processing omitted some observations or tracks. Review each saved view.</p>}
    {!result.rows.length&&<p>No item-specific identifier has been read yet. Product-only codes are retained below.</p>}
    <div className="table-scroll"><table><thead><tr><th>Track</th>{ROLES.map(r=><th key={r}>{title(r)}</th>)}<th>IMEI (index not read)</th><th>Evidence</th></tr></thead><tbody>
      {result.rows.map(row=><tr key={row.id}><td>{row.id}{row.identity && <small> · Identity: {title(row.identity.role)} {row.identity.value}</small>}</td>{ROLES.map(role=>{
        const v=role==='gtin'?row.gtin:role==='imei1'?row.imei1:role==='imei2'?row.imei2:row.serial;
        return <td key={role} className={v.status==='conflict'||v.status==='invalid'||v.association==='unverified'||v.disputedBy.length>0?'cell-review':undefined}>{v.value??(v.values.map(c=>c.value).join(' / ')||'Not read')}<small> · {v.association==='unverified'?'unconfirmed association':v.status}</small>{v.disputedBy.length>0&&<p>Disputed by: {v.disputedBy.map(d=>`${d.value} (${d.frames} views)`).join(", ")}</p>}{v.overflow>0&&<p>{v.overflow} additional values omitted from bounded history.</p>}</td>;
      })}<td>{row.imeiUnindexed.length ? row.imeiUnindexed.map(v=><p key={v.value}>{v.value} · {v.association === "unverified" ? "unconfirmed association" : v.association}</p>) : "Not read"}</td><td>{row.countIsLowerBound ? "At least " : ""}{row.framesSeen} saved views · {row.explicit?'has manual/explicit boundaries':'association unverified'}{row.conflicts.length?` · ${row.conflicts.map(c=>`${c.role}: ${c.value}`).join('; ')}`:''}{row.contested.length>0&&<p>Contested between items: {row.contested.map(c=>`${title(c.role)} ${c.value}`).join('; ')}. Not assigned.</p>}{row.possiblySameAs.length>0&&<p>Possibly the same item as {row.possiblySameAs.join(', ')}; not merged.</p>}</td></tr>)}
    </tbody></table></div>
    {result.unanchored.length>0&&<p>Product-only sightings: {result.unanchored.map(p=>p.gtin).join(', ')}. They do not establish separate physical units.</p>}
    {result.views.some(v=>v.duplicateOf!==null)&&<p>Repeated files/pages were excluded from independent-observation counts.</p>}
  </section>;
}

export function ItemGroups({outcome,editable,onRegions}:{outcome:Reading;editable:boolean;onRegions?:(outcome:Reading,regions:ItemRegion[])=>void}){
  const grouping=outcomeGrouping(outcome);
  const [drawing,setDrawing]=useState(false),[drag,setDrag]=useState<[number,number,number,number]|null>(null);
  const start=useRef<[number,number]|null>(null);
  if(!grouping)return null;
  const point=(event:React.PointerEvent<HTMLImageElement>):[number,number]=>{
    const box=event.currentTarget.getBoundingClientRect();return [Math.max(0,Math.min(grouping.width,(event.clientX-box.left)*grouping.width/box.width)),Math.max(0,Math.min(grouping.height,(event.clientY-box.top)*grouping.height/box.height))];
  };
  return <section className="group" data-testid="item-groups"><h2>Groups in this view</h2>
    {grouping.limits.incomplete && <p role="status">Partial grouping: input limits excluded some values or boundaries.</p>}
    <p>Nearby values may be on different boxes. Outline an item to resolve its uncertain associations. Values outside your outlines remain unconfirmed proximity groups.</p>
    {grouping.items.map(item=><article key={item.key}><h3>{item.key} · {item.strength==='explicit'?'Explicit boundary':'Unconfirmed proximity group'}</h3>
      <dl>{([...ROLES,"imei"] as KeyedRole[]).map(role=>{const v=item.roles[role];return <div key={role}><dt>{role === "imei" ? "IMEI (index not read)" : title(role)}</dt><dd>{v.value??(v.candidates.map(c=>c.value).join(' / ')||'Not read')} · {v.status}</dd></div>;})}</dl>
      {item.conflicts.length>0&&<p role="alert">{item.conflicts.join('; ')}</p>}
    </article>)}
    {!!grouping.unassigned.length&&<p role="status">{grouping.unassigned.length} values remain unassigned.</p>}
    {grouping.unassigned.length>0&&<ul>{grouping.unassigned.map((u,i)=><li key={i}>{grouping.members[u.member]?.label??"Value"}: {grouping.members[u.member]?.value??"unavailable"} · {u.reason}</li>)}</ul>}
    {grouping.ambiguities.map((a,i)=><p key={i} role="status">{a.detail}</p>)}
    {onRegions&&outcome.imageUrl&&<details><summary>Review item boundaries</summary>
      <p>Drag a rectangle around one physical item. Overlapping boundaries remain ambiguous. Finish or stop background label reading before editing.</p>
      <button type="button" disabled={!editable} onClick={()=>setDrawing(!drawing)}>{drawing?'Stop outlining':'Outline an item'}</button>
      <button type="button" disabled={!editable||!outcome.itemRegions?.length} onClick={()=>onRegions(outcome,[])}>Clear boundaries</button>
      <div className="item-review-image">
        <img draggable={false} src={outcome.imageUrl} alt="Draw item boundaries on this captured view" data-testid="item-review-image"
          style={{touchAction:drawing?'none':'auto',cursor:drawing?'crosshair':'default'}}
          onPointerDown={e=>{if(!editable||!drawing||!e.isPrimary)return;e.preventDefault();start.current=point(e);setDrag([...start.current,0,0]);e.currentTarget.setPointerCapture(e.pointerId);}}
          onPointerMove={e=>{if(!start.current)return;const p=point(e),a=start.current;setDrag([Math.min(a[0],p[0]),Math.min(a[1],p[1]),Math.abs(a[0]-p[0]),Math.abs(a[1]-p[1])]);}}
          onPointerCancel={()=>{start.current=null;setDrag(null);}}
          onPointerUp={e=>{
            const a=start.current;if(!a)return;start.current=null;setDrag(null);if(!editable)return;
            const p=point(e),bbox:[number,number,number,number]=[Math.min(a[0],p[0]),Math.min(a[1],p[1]),Math.abs(a[0]-p[0]),Math.abs(a[1]-p[1])];
            if(bbox[2]<10||bbox[3]<10||(outcome.itemRegions?.length??0)>=16)return;
            onRegions(outcome,[...(outcome.itemRegions??[]),{id:crypto.randomUUID(),bbox,origin:'manual'}]);
          }}/>
        <svg viewBox={`0 0 ${grouping.width} ${grouping.height}`} aria-hidden="true">{outcome.itemRegions?.map(r=><rect key={r.id} x={r.bbox[0]} y={r.bbox[1]} width={r.bbox[2]} height={r.bbox[3]} />)}{drag&&<rect x={drag[0]} y={drag[1]} width={drag[2]} height={drag[3]}/>}</svg>
      </div>
      <p>{outcome.itemRegions?.length??0}/16 boundaries</p>
    </details>}
    <details><summary>Grouping limits</summary><ul>{grouping.limitations.map(l=><li key={l}>{l}</li>)}</ul></details>
  </section>;
}
