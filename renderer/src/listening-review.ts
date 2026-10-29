import type { Playable } from './listening-queue';
type RPC=(method:string,params?:Record<string,unknown>)=>Promise<any>;
export async function saveListeningReview(rpc:RPC,item:Playable,resolvedId:string|undefined,
  changes?:Record<string,unknown>,credit?:{name:string;followed?:boolean}) {
  let id=resolvedId||item.trackId;
  if(!id&&item.candidateId){const kept=await rpc('discovery_library_research_review',{candidate_id:item.candidateId,decision:'keep'});id=kept.track_id;}
  if(!id)throw new Error('This track could not be saved.');
  if(credit)await rpc('discovery_follow',{name:credit.name,enabled:!credit.followed});
  else await rpc('discovery_react',{track_id:id,...changes});
  return id;
}
