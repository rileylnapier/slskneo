import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Heart, ThumbsDown, ThumbsUp } from 'lucide-react';
import { saveListeningReview } from './listening-review';
import type { Playable } from './listening-queue';
export const discoveryChanged=()=>window.dispatchEvent(new Event('taste-discovery-changed'));
export default function PlayerReview({item}:{item:Playable}) {
  const [track,setTrack]=useState<any>(null);
  const [people,setPeople]=useState<{name:string;followed:boolean}[]>([]);
  const [ready,setReady]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const pending=useRef(false);
  useEffect(()=>{
    let alive=true;let request=0;
    async function refresh(){const revision=++request;try{
      const rpc=window.soulseek!.rpc;
      let id=item.trackId;
      if(!id&&item.candidateId){const state=await rpc('discovery_library_research_state');id=state.candidates.find((c:any)=>c.id===item.candidateId)?.track_id;}
      const inbox=await rpc('discovery_inbox');
      if(alive&&revision===request){setPeople(inbox.people);setTrack(inbox.tracks.find((t:any)=>t.id===id)||null);setReady(true);}
    }catch(e:any){if(alive&&revision===request)setError(e.message||'Could not load your reactions.');}}
    void refresh();window.addEventListener('taste-discovery-changed',refresh);
    return()=>{alive=false;window.removeEventListener('taste-discovery-changed',refresh);};
  },[item.id]);
  async function act(changes?:Record<string,unknown>,credit?:{name:string;followed?:boolean}){
    if(pending.current)return;pending.current=true;setBusy(true);setError('');
    try {
      const rpc=window.soulseek!.rpc;
      const id=await saveListeningReview(rpc,item,track?.id,changes,credit);
      const inbox=await rpc('discovery_inbox');setTrack(inbox.tracks.find((t:any)=>t.id===id));
    }catch(e:any){setError(e.message||'Could not save your reaction.');}finally{pending.current=false;setBusy(false);discoveryChanged();}
  }
  const needsReview=item.requiresReview&&!track;
  const credits=track?.credits||(item.credits||[]).map(c=>({...c,followed:people.find(p=>p.name.normalize('NFKC').toLowerCase()===c.name.normalize('NFKC').toLowerCase())?.followed||false}));
  return <div className="player-review">
    {needsReview&&<p>Confirm the recording artist and version in the finding before saving reactions. The uploader may be a remixer or curator.</p>}
    <div className="player-review-actions">
      <button className="secondary" disabled={!ready||busy||!!needsReview} aria-pressed={!!track?.favorite} onClick={()=>void act({favorite:!track?.favorite})}><Heart size={15} fill={track?.favorite?'currentColor':'none'}/>{track?.favorite?'Favorited':'Favorite'}</button>
      <button className="secondary" disabled={!ready||busy||!!needsReview} aria-label="Like playing track" aria-pressed={track?.rating===1} onClick={()=>void act({rating:track?.rating===1?0:1})}><ThumbsUp size={15}/></button>
      <button className="secondary" disabled={!ready||busy||!!needsReview} aria-label="Dislike playing track" aria-pressed={track?.rating===-1} onClick={()=>void act({rating:track?.rating===-1?0:-1})}><ThumbsDown size={15}/></button>
    </div>
    <p>{track?.owned?'Already in your library':track?'Saved discovery':"Reacting saves this find to your collection."} · Skips don’t change your taste.</p>
    {!!item.reasons?.length&&<div className="queue-reasons"><strong>Why it’s here</strong>{item.reasons.map(reason=><p key={reason}>{reason}</p>)}</div>}
    {!!credits.length&&<div className="queue-credits">{credits.map((c:any)=><div key={`${c.name}-${c.role}`}><span>{c.name}<small>{c.role}</small></span><button className="text-button" disabled={!ready||busy||!!needsReview} aria-pressed={!!c.followed} onClick={()=>void act(undefined,c)}>{c.followed?'Following':'+ Follow'}</button></div>)}</div>}
    <div className="queue-source-links">{(track?.sources||item.sources||[]).filter((s:any)=>s.url).map((s:any,i:number)=><button className="text-button" key={`${s.url}-${i}`} onClick={()=>void window.soulseek!.openMusicLink(s.url).catch(e=>setError(e.message))}>Open {s.source}<ArrowUpRight size={12}/></button>)}</div>
    {error&&<p role="alert" className="review-error">{error} <button className="text-button" onClick={()=>{setError('');discoveryChanged();}}>Reload reactions</button></p>}
  </div>;
}
