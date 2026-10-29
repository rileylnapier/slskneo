import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Check, FlaskConical, Loader2, Search } from 'lucide-react';
import './library-research.css';
import { PlayControls, useMusicPlayer, type Playable } from './MusicPlayer';

import { discoveryChanged } from './PlayerReview';

type Seed = {id:string;artist:string;title:string;owned:boolean;favorite:boolean;rating:number};
type JobSeed = {id:string;artist:string;title:string;status:string;candidates?:number;collected?:number;error?:string};
type Job = {id:string;status:string;started_at:string;completed:number;seeds:JobSeed[]};
type Finding = {women_focus_matches?:{name:string}[];id:string;status:string;track_id:string|null;record:{source?:string;soundcloud_url?:string;uploader?:string;uploaded_at?:string;content_kind?:string;classification_note?:string;identity_note?:string;identity_confirmed?:boolean;source_links?:{source:string;url:string}[];download_available?:boolean;artist:string;title:string;url:string;preview_url:string;artwork:string;label:string;genre:string;release_date:string;release:string;bpm:number|null;credits:{name:string;role:string;url:string}[]};
  evidence:{seed_id:string;artist:string;title:string;kind:string;reason:string;checked_at:string}[]};
type State = {women_focus_enabled?:boolean;job:Job|null;candidates:Finding[];counts:Record<string,number>};
const initial:State={job:null,candidates:[],counts:{}};

function suggestedSeeds(tracks:Seed[]) {
  const seen=new Set<string>();
  return [...tracks].filter(t=>t.owned&&t.rating!==-1).sort((a,b)=>Number(b.favorite)-Number(a.favorite)||b.rating-a.rating)
    .filter(t=>{const key=t.artist.toLocaleLowerCase().trim();if(seen.has(key))return false;seen.add(key);return true;}).slice(0,20).map(t=>t.id);
}

export default function LibraryResearch({tracks,available,rpc,onChanged,onSearch,open,watchOnly=false}:{watchOnly?:boolean;tracks:Seed[];available:boolean;rpc:(method:string,params?:Record<string,unknown>)=>Promise<any>;onChanged:()=>Promise<void>;onSearch:(query:string)=>void;open:(url:string)=>Promise<void>}) {
  const player=useMusicPlayer();
  const [state,setState]=useState<State>(initial);
  const [loaded,setLoaded]=useState(false);
  const [selectedSeeds,setSelectedSeeds]=useState<string[]>(()=>suggestedSeeds(tracks));
  const [seedFilter,setSeedFilter]=useState('');
  const [seedLimit,setSeedLimit]=useState(40);
  const [choose,setChoose]=useState(false);
  const [view,setView]=useState('pending');
  const [selected,setSelected]=useState('');
  const [findingFilter,setFindingFilter]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const initializedSeeds=useRef(tracks.some(t=>t.owned));
  useEffect(()=>{if(!initializedSeeds.current&&tracks.some(t=>t.owned)){setSelectedSeeds(suggestedSeeds(tracks));initializedSeeds.current=true;}},[tracks]);
  const refresh=useCallback(async()=>{const next=await rpc('discovery_library_research_state');setState(next);setLoaded(true);return next as State;},[rpc]);
  useEffect(()=>{let stopped=false;let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{const next=await rpc('discovery_library_research_state');if(!stopped){setState(next);setLoaded(true);}}
      catch(e:any){if(!stopped)setError(e.message||'Could not read research progress.');}
      if(!stopped)timer=setTimeout(poll,2000);};
    void poll();return()=>{stopped=true;clearTimeout(timer);};},[rpc]);
  async function act(fn:()=>Promise<unknown>){setBusy(true);setError('');try{await fn();await refresh();discoveryChanged();}catch(e:any){setError(e.message||'Could not update research.');}finally{setBusy(false);}}
  const owned=tracks.filter(t=>t.owned);
  const filteredSeeds=owned.filter(t=>`${t.artist} ${t.title}`.toLowerCase().includes(seedFilter.toLowerCase()));
  const running=state.job?.status==='running';
  const results=state.candidates.filter(c=>c.status===view&&(!watchOnly||c.evidence.some(e=>e.kind==='watch'))&&`${c.record.artist} ${c.record.title} ${c.record.label} ${c.evidence.map(e=>e.artist).join(' ')}`.toLowerCase().includes(findingFilter.toLowerCase()))
    .sort((a,b)=>Number(!!state.women_focus_enabled&&!!b.women_focus_matches?.length)-Number(!!state.women_focus_enabled&&!!a.women_focus_matches?.length)||Number(b.evidence.some(e=>e.kind==='artist_catalog'))-Number(a.evidence.some(e=>e.kind==='artist_catalog'))||b.record.release_date.localeCompare(a.record.release_date));
  useEffect(()=>{if(!results.some(f=>f.id===selected))setSelected(results[0]?.id||'');},[results,selected]);
  const playable=(f:Finding):Playable=>({id:`research:${f.id}`,candidateId:f.id,sources:[{source:f.record.source||'Beatport',url:f.record.url},...(f.record.source_links||[])],trackId:f.track_id||undefined,url:f.record.soundcloud_url||f.record.preview_url,requiresReview:f.record.source==='SoundCloud'&&!f.track_id,title:f.record.title,artist:f.record.artist,kind:f.record.soundcloud_url?'soundcloud':'preview',artwork:f.record.artwork,reasons:f.evidence.map(e=>e.reason),credits:f.record.credits});
  const playableResults=results.filter(f=>f.record.preview_url||f.record.soundcloud_url).map(playable);
  const finding=results.find(c=>c.id===selected)||results[0];
  const counts=watchOnly?state.candidates.filter(c=>c.evidence.some(e=>e.kind==='watch')).reduce((all,c)=>({...all,[c.status]:(all[c.status]||0)+1}),{} as Record<string,number>):state.counts;
  const record=finding?.record;
  const [reviewArtist,setReviewArtist]=useState('');const [reviewTitle,setReviewTitle]=useState('');const [reviewKind,setReviewKind]=useState('unclassified');const [confirmed,setConfirmed]=useState(false);
  useEffect(()=>{setReviewArtist(record?.artist||'');setReviewTitle(record?.title||'');setReviewKind(record?.content_kind||'unclassified');setConfirmed(false);},[finding?.id]);
  const current=state.job?.seeds.find(s=>s.status==='researching');
  const labels:Record<string,string>={running:'Following the trail…',complete:'Your finds are ready',partial:'Some seeds need another try',failed:'Beatport research couldn’t finish',cancelled:'Research stopped',interrupted:'Research was interrupted'};
  return <section className="library-research" aria-label="Research my library">
    {!watchOnly&&<><div className="research-intro"><div><div className="discovery-eyebrow">LET YOUR RECORDS LEAD THE WAY</div><h2>Research my library.</h2><p>Pick a handful of records. Follow their artists into Beatport releases, edits, remix credits, and labels.</p></div><FlaskConical size={34}/></div>
    <div className="research-launch"><div><strong>{selectedSeeds.length} seeds selected</strong><p>Suggested: up to 20 different artist names, with favorites first. Choose up to 30 tracks.</p></div>
      <button className="secondary" disabled={busy||running} onClick={()=>setChoose(!choose)} aria-expanded={choose}>{choose?'Hide seeds':'Choose seeds'}</button>
      <button className="primary" disabled={!loaded||busy||running||!available||!selectedSeeds.length} onClick={()=>void act(async()=>{await rpc('discovery_library_research_start',{seed_ids:selectedSeeds});setChoose(false);setView('pending');})}>{running?<Loader2 size={14} className="spin"/>:<Search size={14}/>}Research selected tracks</button>
    </div>
    {!available&&<p>Connect your Beatport sign-in to research your library.</p>}
    {!owned.length&&<p>Import a music folder in Manage sources to choose your first seeds.</p>}
    {choose&&<div className="research-seeds"><div className="research-seed-tools"><input aria-label="Filter research seeds" placeholder="Find a seed track…" value={seedFilter} onChange={e=>{setSeedFilter(e.target.value);setSeedLimit(40);}}/><button className="text-button" disabled={running||busy} onClick={()=>setSelectedSeeds(suggestedSeeds(tracks))}>Use suggested 20</button><button className="text-button" disabled={running||busy} onClick={()=>setSelectedSeeds([])}>Clear</button></div>
      <div className="research-seed-list">{filteredSeeds.slice(0,seedLimit).map(t=><label key={t.id}><input type="checkbox" checked={selectedSeeds.includes(t.id)} disabled={running||busy||(!selectedSeeds.includes(t.id)&&selectedSeeds.length>=30)} onChange={e=>setSelectedSeeds(ids=>e.target.checked?[...ids,t.id]:ids.filter(id=>id!==t.id))}/><span><strong>{t.title}</strong><small>{t.artist}{t.favorite?' · Favorite':''}</small></span></label>)}</div>
      {filteredSeeds.length>seedLimit&&<button className="text-button" onClick={()=>setSeedLimit(n=>n+40)}>Show more seeds</button>}
    </div>}
    {error&&<div className="discovery-message error" role="alert">{error}<button onClick={()=>void act(refresh)}>Retry</button></div>}
    {state.job&&<section className="research-progress" aria-label="Research progress"><div><strong>{labels[state.job.status]||state.job.status}</strong><span>{state.job.completed} / {state.job.seeds.length} seeds checked</span>{running&&<button className="secondary" disabled={busy} onClick={()=>void act(()=>rpc('discovery_library_research_cancel'))}>Stop research</button>}</div>
      <progress aria-label="Seeds checked" value={state.job.completed} max={state.job.seeds.length}/>
      <p role="status">{current?`${current.artist} — ${current.title}`:`Started ${new Date(state.job.started_at).toLocaleString()} · Findings stay here for review.`}</p>
      <details><summary>Seed-by-seed results</summary>{state.job.seeds.map(s=><p key={s.id}><strong>{s.artist} — {s.title}</strong><br/>{s.status==='done'?`${s.candidates||0} findings · ${s.collected||0} already collected`:s.error||s.status}</p>)}</details>
      {!running&&state.job.seeds.some(s=>s.status!=='done')&&<button className="text-button" disabled={busy} onClick={()=>{setSelectedSeeds(state.job!.seeds.filter(s=>s.status!=='done').map(s=>s.id));setChoose(true);}}>Select unfinished seeds to retry</button>}
    </section>}
    </>}
    {watchOnly&&error&&<div className="discovery-message error" role="alert">{error}</div>}
    <div className="research-results-heading"><h3>{watchOnly?'Fresh from your watches':'A little listening homework'}</h3><button className="primary" disabled={!playableResults.length} onClick={()=>player.startQueue(playableResults)}>Listen to findings ({playableResults.length})</button><p>{watchOnly?'Watch findings':'All research runs and watches'} · Keep adds a finding to Fresh picks. Dismiss only hides this suggestion.</p></div>
    <div className="research-review-tabs" aria-label="Finding status">{[['pending','To review'],['kept','Kept'],['dismissed','Dismissed']].map(([key,label])=><button key={key} className={view===key?'chosen':''} aria-pressed={view===key} onClick={()=>setView(key)}>{label} <span>{counts[key]||0}</span></button>)}</div>
    <input className="research-find-filter" aria-label="Filter research findings" placeholder="Find a track, seed artist, or label…" value={findingFilter} onChange={e=>setFindingFilter(e.target.value)}/>
    {Object.values(state.counts).reduce((a,b)=>a+b,0)>500&&<p>Showing the 500 most recently seen findings.</p>}
    {state.women_focus_enabled&&<p className="watch-note">Women focus: findings with sourced artist or remixer matches come first. Other findings remain available.</p>}
    {!loaded?<p>Opening research…</p>:!finding?<div className="research-empty"><FlaskConical size={28}/><h3>{running?'Looking for your next find…':'Room for a good find.'}</h3><p>{findingFilter?'Try a different search or clear the filter.':view==='pending'?watchOnly?'New entries appear after your first successful baseline check.':'Start a research run above, or restore a dismissed suggestion.':`No ${view} findings yet.`}</p></div>:record&&<div className="research-findings-layout"><div className="research-findings-list" aria-label="Research findings">{results.map(f=><button key={f.id} className={finding.id===f.id?'selected':''} onClick={()=>setSelected(f.id)} aria-pressed={finding.id===f.id}><span className="track-art">{f.record.artwork?<img src={f.record.artwork} alt="" loading="lazy" referrerPolicy="no-referrer"/>:<span className="taste-sleeve-record"/>}</span><span><strong>{f.record.title}</strong><small>{f.record.artist}</small><small>{f.evidence.some(e=>e.kind==='possible_version')?'Version to check':f.evidence.some(e=>e.kind==='watch')?'Watch finding':'Artist trail'} · {f.record.label||f.record.source||'Beatport'}</small></span></button>)}</div>
      <article className="research-finding-detail" aria-label="Selected research finding"><div className="discovery-eyebrow">{finding.evidence.some(e=>e.kind==='possible_version')?'POSSIBLE MATCH · CHECK THE VERSION':finding.evidence.some(e=>e.kind==='watch')?'NEWLY SEEN ON A SOURCE WATCH':'FROM AN ARTIST IN YOUR LIBRARY'}</div><h2>{record.title}</h2><p className="detail-artist">{record.artist}</p><p>{[record.genre,record.bpm?`${record.bpm} BPM`:'',record.release_date].filter(Boolean).join(' · ')}</p>
        {record.source==='SoundCloud'&&<section className="soundcloud-review"><p>Uploaded by <strong>{record.uploader}</strong>{record.uploaded_at?` · ${new Date(record.uploaded_at).toLocaleDateString()}`:''}. Uploader and recording artist may differ.</p><p>Suggested type: <strong>{record.content_kind?.replace('_',' ')}</strong> · {record.classification_note}</p>
          {finding.status!=='kept'&&<><label>Recording artist<input aria-label="Confirm SoundCloud recording artist" value={reviewArtist} onChange={e=>{setReviewArtist(e.target.value);setConfirmed(false);}} maxLength={250}/></label><label>Track title and version<input aria-label="Confirm SoundCloud track version" value={reviewTitle} onChange={e=>{setReviewTitle(e.target.value);setConfirmed(false);}} maxLength={500}/></label><label>Upload type<select aria-label="Confirm SoundCloud upload type" value={reviewKind} onChange={e=>{setReviewKind(e.target.value);setConfirmed(false);}}>{['unclassified','original','remix','edit','bootleg','dj_set'].map(k=><option key={k} value={k}>{k.replace('_',' ')}</option>)}</select></label><label className="profile-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I checked the recording artist and exact version.</label></>}
        </section>}
        <div className="research-review-actions">{finding.status==='kept'?<span><Check size={14}/> Saved to Fresh picks</span>:<><button className="primary" disabled={busy||(record.source==='SoundCloud'&&(!confirmed||!reviewArtist.trim()||!reviewTitle.trim()))} onClick={()=>void act(async()=>{await rpc('discovery_library_research_review',{candidate_id:finding.id,decision:'keep',...(record.source==='SoundCloud'?{artist:reviewArtist,title:reviewTitle,content_kind:reviewKind}:{})});await onChanged();})}><Check size={14}/>Keep this find</button><button className="secondary" disabled={busy} onClick={()=>void act(()=>rpc('discovery_library_research_review',{candidate_id:finding.id,decision:finding.status==='dismissed'?'restore':'dismiss'}))}>{finding.status==='dismissed'?'Restore to review':'Dismiss'}</button></>}</div>
        <section className="discovery-player"><h3>Take a taste</h3>{record.preview_url||record.soundcloud_url?<PlayControls item={playable(finding)}/>:<p>No inline player available. Open the source to listen.</p>}</section>
        <section className="discovery-context"><h3>Follow the trail</h3>{finding.evidence.map(e=><div className="research-evidence" key={e.seed_id}><strong>{e.artist} — {e.title}</strong><p>{e.reason}</p><small>Checked {new Date(e.checked_at).toLocaleString()} · {record.source||'Beatport'}</small></div>)}</section>
        <section className="discovery-context"><h3>People & release</h3>{record.credits.map(c=><div className="credit-row" key={`${c.name}-${c.role}`}><span>{c.name} <small>{c.role}</small></span>{c.url&&<button className="text-button" onClick={()=>void open(c.url)}>Profile <ArrowUpRight size={12}/></button>}</div>)}{record.label&&<p>Label · <strong>{record.label}</strong></p>}{record.release&&<p>Release · {record.release}</p>}</section>
        {(record.source_links||[]).length>0&&<section className="discovery-context"><h3>Uploader-provided links</h3><p>Check the version at the destination. A Hypeddit gate may offer a different recording.</p><div className="source-links">{record.source_links!.map(link=><button className="secondary" key={link.url} onClick={()=>void open(link.url)}>Open {link.source}<ArrowUpRight size={12}/></button>)}</div></section>}
        {record.source==='SoundCloud'&&record.download_available&&<p>The uploader offers a download on SoundCloud. Open the source to collect it.</p>}
        <div className="source-links"><button className="secondary" onClick={()=>void open(record.url)}>View on {record.source||'Beatport'} <ArrowUpRight size={12}/></button><button className="text-button" onClick={()=>onSearch(`${record.artist} ${record.title}`)}>Search Soulseek <ArrowUpRight size={12}/></button></div><p className="lookup-note">Keep saves this source entry. It doesn’t identify or replace a local audio file.</p>
      </article></div>}
  </section>;
}
