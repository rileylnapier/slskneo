export type Playable = {id:string;url:string;title:string;artist:string;kind:'local'|'preview'|'soundcloud';requiresReview?:boolean;format?:string;artwork?:string;
  trackId?:string;candidateId?:string;sources?:{source:string;url:string}[];reasons?:string[];credits?:{name:string;role:string}[]};
export type ListeningQueue = {items:Playable[];index:number};
export const emptyQueue:ListeningQueue={items:[],index:-1};
export function makeQueue(items:Playable[],startUrl?:string):ListeningQueue {
  const seen=new Set<string>();
  const unique=items.filter(item=>{if(!item.url||seen.has(item.url))return false;seen.add(item.url);return true;});
  return {items:unique,index:unique.length?Math.max(0,unique.findIndex(item=>item.url===startUrl)):-1};
}
export function appendQueue(queue:ListeningQueue,items:Playable[]):ListeningQueue {
  const next=makeQueue([...queue.items,...items]);
  return {...next,index:queue.index<0?next.index:queue.index};
}
export function removeQueued(queue:ListeningQueue,index:number):ListeningQueue {
  if(index===queue.index||index<0||index>=queue.items.length)return queue;
  return {items:queue.items.filter((_,i)=>i!==index),index:queue.index-(index<queue.index?1:0)};
}
export function queueStep(queue:ListeningQueue,direction:number):number|null {
  const index=queue.index+direction;
  return index>=0&&index<queue.items.length?index:null;
}
export function trackPlayable(track:{id:string;title:string;artist:string;artwork?:string;preview_url?:string;soundcloud_url?:string;
  sources?:{source:string;url:string}[];local_audio?:{url:string;format:string}[];reasons?:string[];credits?:{name:string;role:string}[]}):Playable|null {
  const local=track.local_audio?.[0];const url=local?.url||track.preview_url||track.soundcloud_url;
  return url?{id:track.id,trackId:track.id,url,title:track.title,artist:track.artist,artwork:track.artwork,
    kind:local?'local':track.preview_url?'preview':'soundcloud',format:local?.format,reasons:track.reasons,credits:track.credits,sources:track.sources}:null;
}
