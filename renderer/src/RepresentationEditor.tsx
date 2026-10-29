import { useState } from 'react';
export type Representation={profile_key:string;name:string;source_url:string;note:string;updated_at:string};
export default function RepresentationEditor({watchId,name,value,onSave}:{watchId:string;name:string;value?:Representation;onSave:(params:Record<string,unknown>)=>Promise<void>}){
  const [source,setSource]=useState(value?.source_url||'');const [note,setNote]=useState(value?.note||'');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  async function save(included:boolean){setBusy(true);setError('');try{await onSave({watch_id:watchId,included,source_url:source,note});}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  return <details className="representation-editor"><summary>{value?'Included in Women focus · review source':'Women focus · add artist information'}</summary>
    <p>Include women artists and acts with women members using an artist’s self-description or explicit public bio/interview. Leave uncertain profiles unset.</p>
    {value&&<><p>{value.note}</p><button className="text-button" onClick={()=>void window.soulseek!.openRepresentationSource(value.profile_key).catch(e=>setError(e.message))}>Read source ↗</button><small>Reviewed {new Date(value.updated_at).toLocaleDateString()}</small></>}
    <form onSubmit={e=>{e.preventDefault();void save(true);}}><label>Public source<input aria-label={`Women focus source for ${name}`} type="url" placeholder="https://…" value={source} onChange={e=>setSource(e.target.value)} maxLength={2048}/></label><label>What the artist or source says<textarea aria-label={`Women focus note for ${name}`} value={note} onChange={e=>setNote(e.target.value)} maxLength={1000}/></label><div className="watch-actions"><button className="secondary" disabled={busy||!source.trim()||note.trim().length<10}>{value?'Update source':'Include in Women focus'}</button>{value&&<button type="button" className="text-button" disabled={busy} onClick={()=>void save(false)}>Remove association</button>}</div></form>{error&&<p role="alert">{error}</p>}
  </details>;
}
