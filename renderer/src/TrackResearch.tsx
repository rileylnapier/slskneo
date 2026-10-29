import { useState } from 'react';
import { ArrowUpRight } from 'lucide-react';

export type ResearchEvidence = {
  id:string; kind:'dj_play'|'chart_position'|'soulseek_snapshot'; source:string; url:string;
  event_date:string; subject:string; status:'candidate'|'confirmed'; metric:number|null; recorded_at:string;
  details:{query?:string;matching_files?:number;distinct_peers?:number;duration_seconds?:number|null;truncated?:boolean};
};
export type TrackResearchData = {evidence:ResearchEvidence[];confirmed_djs:number;dj_plays:number;djs_last_7_days:number;djs_previous_7_days:number};
const empty:TrackResearchData={evidence:[],confirmed_djs:0,dj_plays:0,djs_last_7_days:0,djs_previous_7_days:0};

export default function TrackResearch({trackId,query,research=empty,busy,act,rpc,open,onSearch}:{
  trackId:string;query:string;research?:TrackResearchData;busy:boolean;
  act:(fn:()=>Promise<unknown>,message?:string)=>Promise<void>;
  rpc:(method:string,params?:Record<string,unknown>)=>Promise<any>;
  open:(url:string)=>Promise<void>;onSearch:(query:string,trackId?:string)=>void;
}) {
  const [formOpen,setFormOpen]=useState(false);
  const [kind,setKind]=useState('dj_play');
  const [subject,setSubject]=useState('');
  const [url,setUrl]=useState('');
  const [day,setDay]=useState('');
  const [position,setPosition]=useState('');
  const [confirmed,setConfirmed]=useState(false);
  const [limit,setLimit]=useState(8);
  return <section className="discovery-context track-research" aria-label="Track research">
    <h3>Track research</h3>
    {research.dj_plays>0?<><div className="research-stats"><strong>{research.confirmed_djs} DJs</strong><span>across {research.dj_plays} recorded plays</span></div><p>{research.djs_last_7_days} distinct DJ names in the last 7 days · {research.djs_previous_7_days} in the previous 7 days.</p><p>Confirmed observations in Taste; source coverage is incomplete.</p></>:<p>No confirmed DJ plays recorded yet. Start with evidence for this exact version.</p>}
    <div className="research-actions"><button className="secondary" onClick={()=>onSearch(query,trackId)}>Sample Soulseek availability <ArrowUpRight size={12}/></button><button className="text-button" onClick={()=>void open('https://www.1001tracklists.com/')}>Open 1001Tracklists <ArrowUpRight size={12}/></button><button className="text-button" aria-expanded={formOpen} onClick={()=>setFormOpen(!formOpen)}>Record source evidence</button></div>
    {formOpen&&<form className="research-form" onSubmit={e=>{e.preventDefault();void act(async()=>{
      await rpc('discovery_research_record',{track_id:trackId,kind,url:url.trim(),event_date:day,subject:subject.trim(),confirmed,position:kind==='chart_position'?Number(position):null});
      setFormOpen(false);setSubject('');setUrl('');setDay('');setPosition('');setConfirmed(false);
    },'Source evidence saved for this track version.');}}>
      <label>Observation<select aria-label="Research observation type" value={kind} onChange={e=>{setKind(e.target.value);setConfirmed(false);}}><option value="dj_play">DJ played this version</option><option value="chart_position">Beatport chart position</option></select></label>
      <label>{kind==='dj_play'?'DJ name':'Exact chart name'}<input required maxLength={250} value={subject} onChange={e=>setSubject(e.target.value)} placeholder={kind==='dj_play'?'Who played it?':'e.g. Tech House Top 100'}/></label>
      <label>{kind==='dj_play'?'Set / tracklist URL':'Chart URL'}<input required type="url" value={url} maxLength={4096} onChange={e=>setUrl(e.target.value)} placeholder={kind==='dj_play'?'1001Tracklists, YouTube, or SoundCloud':'https://www.beatport.com/…'}/></label>
      <label>{kind==='dj_play'?'Date played':'Chart date'}<input required type="date" value={day} max={new Date().toISOString().slice(0,10)} onChange={e=>setDay(e.target.value)}/></label>
      {kind==='chart_position'&&<label>Position<input required type="number" min={1} max={1000} value={position} onChange={e=>setPosition(e.target.value)}/></label>}
      <label className="research-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I checked the source and it matches this exact version.</label>
      <p>Unchecked observations remain candidates and don’t count as confirmed support. Nothing is fetched automatically.</p>
      <button className="primary" disabled={busy}>Save observation</button>
    </form>}
    <div className="research-history">{research.evidence.slice(0,limit).map(e=><article className="research-observation" key={e.id}>
      <div className="research-observation-heading"><strong>{e.kind==='dj_play'?e.subject:e.kind==='chart_position'?`${e.subject} · #${e.metric}`:'Soulseek availability sample'}</strong><small>{e.event_date}</small></div>
      {e.kind==='soulseek_snapshot'?<><p>{e.details.distinct_peers} distinct peers · {e.details.matching_files} matching files · {e.details.duration_seconds==null?'duration unavailable':`${e.details.duration_seconds}s search`}{e.details.truncated?' · result limit reached':''}</p><p>Query: {e.details.query}</p><p>Candidate filename matches, possibly other versions. This measures observed availability, not listens, downloads, or DJ support.</p></>:<><p>{e.source} · {e.status==='confirmed'?'Exact version confirmed by you':'Candidate — version needs review'}</p><div className="research-actions"><button className="text-button" onClick={()=>void open(e.url)}>View evidence <ArrowUpRight size={12}/></button><button className="text-button" disabled={busy} onClick={()=>void act(()=>rpc('discovery_research_review',{observation_id:e.id,confirmed:e.status!=='confirmed'}))}>{e.status==='confirmed'?'Mark uncertain':'Confirm exact version'}</button></div></>}
      <small className="research-recorded">Recorded {e.recorded_at.slice(0,10)} · {e.source}</small>
    </article>)}</div>
    {research.evidence.length>limit&&<button className="text-button" onClick={()=>setLimit(n=>n+8)}>Show older observations</button>}
    {!research.evidence.length&&<p className="research-empty">No history yet. Each saved observation keeps its date and source.</p>}
  </section>;
}
