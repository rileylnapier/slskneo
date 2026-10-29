import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Headphones, Pause, Play, RotateCcw, RotateCw, X, ListMusic, SkipBack, SkipForward, Plus } from 'lucide-react';
import './music-player.css';
import { appendQueue, emptyQueue, makeQueue, queueStep, removeQueued, type ListeningQueue, type Playable } from './listening-queue';
import { SoundCloudPlayer, type CloudControls } from './SoundCloudPlayer';
import PlayerReview from './PlayerReview';
export type { Playable } from './listening-queue';

type Player = {current:Playable|null;playing:boolean;position:number;duration:number;error:string;
  startQueue:(items:Playable[],startUrl?:string)=>void;enqueue:(item:Playable)=>void;play:(item:Playable)=>void;pause:()=>void;seek:(seconds:number)=>void;stop:()=>void};
const Context=createContext<Player|null>(null);
export function useMusicPlayer(){const value=useContext(Context);if(!value)throw new Error('Music player is unavailable.');return value;}

export function MusicPlayerProvider({children}:{children:ReactNode}){
  const [current,setCurrent]=useState<Playable|null>(null);
  const [playing,setPlaying]=useState(false);
  const [position,setPosition]=useState(0);
  const [duration,setDuration]=useState(0);
  const playbackState=useRef({position:0,duration:0});playbackState.current={position,duration};
  const [cloudStarted,setCloudStarted]=useState(false);
  const [error,setError]=useState('');
  const [queue,setQueue]=useState<ListeningQueue>(emptyQueue);
  const queueRef=useRef<ListeningQueue>(emptyQueue);
  const [queueOpen,setQueueOpen]=useState(false);
  function updateQueue(value:ListeningQueue){queueRef.current=value;setQueue(value);}
  const activeRow=useRef<HTMLLIElement>(null);
  useEffect(()=>{activeRow.current?.scrollIntoView({block:'nearest'});},[queue.index,queueOpen]);
  const audio=useRef<HTMLAudioElement>(null);
  const cloud=useRef<CloudControls>(null);
  const active=useRef<Playable|null>(null);
  const generation=useRef(0);
  function failure(){setPlaying(false);setError(active.current?.kind==='local'
    ? 'Couldn’t play this local file. Make it available offline in Dropbox, or re-import its folder if it moved or changed. Some audio formats may need your external music app.'
    : 'This preview is unavailable. Open the source to listen.');}
  function playAudio(item:Playable){
    const el=audio.current;if(!el)return;
    const changed=active.current?.url!==item.url;
    if(changed){generation.current++;el.pause();cloud.current?.pause();setPlaying(false);setPosition(0);setDuration(0);}
    active.current=item;setCurrent(item);setError('');
    if(item.kind==='soundcloud'){
      setCloudStarted(true);
      el.removeAttribute('src');el.load();
      if(!changed)cloud.current?.play();
      return;
    }
    setCloudStarted(false);
    if(changed||!el.getAttribute('src'))el.src=item.url;
    if(el.error)el.load();
    const attempt=generation.current;
    void el.play().catch(e=>{if(attempt===generation.current&&e.name!=='AbortError')failure();});
  }
  function play(item:Playable){
    const q=queueRef.current;const index=q.items.findIndex(i=>i.url===item.url);
    if(index>=0){updateQueue({...q,index,items:q.items.map((i,n)=>n===index?item:i)});}
    else updateQueue(makeQueue([item]));
    playAudio(item);
  }
  function startQueue(items:Playable[],startUrl?:string){const q=makeQueue(items,startUrl);if(q.index<0)return;updateQueue(q);setQueueOpen(true);playAudio(q.items[q.index]);}
  function enqueue(item:Playable){const q=appendQueue(queueRef.current,[item]);updateQueue(q);setQueueOpen(true);if(!active.current){active.current=q.items[q.index];setCurrent(active.current);const el=audio.current;if(el&&active.current.kind!=='soundcloud')el.src=active.current.url;}}
  function jump(index:number){const q=queueRef.current;if(!q.items[index])return;updateQueue({...q,index});playAudio(q.items[index]);}
  function step(direction:number){const index=queueStep(queueRef.current,direction);if(index!==null)jump(index);}
  function ended(){setPlaying(false);step(1);}
  function pause(){if(active.current?.kind==='soundcloud')cloud.current?.pause();else audio.current?.pause();}
  function seek(seconds:number){if(active.current?.kind==='soundcloud'){cloud.current?.seek(Math.max(0,Math.min(playbackState.current.duration,seconds)));return;}const el=audio.current;if(el&&Number.isFinite(el.duration)&&el.duration>0)el.currentTime=Math.min(el.duration,Math.max(0,seconds));}
  function stop(){cloud.current?.pause();setCloudStarted(false);updateQueue(emptyQueue);setQueueOpen(false);generation.current++;const el=audio.current;if(el){el.pause();el.removeAttribute('src');el.load();}active.current=null;setCurrent(null);setError('');setPosition(0);setDuration(0);}
  useEffect(()=>{
    if(!('mediaSession' in navigator))return;
    navigator.mediaSession.metadata=current?new MediaMetadata({title:current.title,artist:current.artist,album:current.kind==='local'?'Your library':current.kind==='soundcloud'?'SoundCloud':'Online preview'}):null;
    navigator.mediaSession.setActionHandler('play',()=>{if(active.current)play(active.current);});
    navigator.mediaSession.setActionHandler('pause',pause);
    navigator.mediaSession.setActionHandler('seekbackward',details=>seek((active.current?.kind==='soundcloud'?playbackState.current.position:(audio.current?.currentTime||0))-(details.seekOffset||15)));
    navigator.mediaSession.setActionHandler('seekforward',details=>seek((active.current?.kind==='soundcloud'?playbackState.current.position:(audio.current?.currentTime||0))+(details.seekOffset||15)));
    navigator.mediaSession.setActionHandler('seekto',details=>{if(details.seekTime!==undefined)seek(details.seekTime);});
    navigator.mediaSession.setActionHandler('stop',stop);
    navigator.mediaSession.setActionHandler('nexttrack',()=>step(1));
    navigator.mediaSession.setActionHandler('previoustrack',()=>step(-1));
    return()=>{for(const action of ['play','pause','seekbackward','seekforward','seekto','stop','nexttrack','previoustrack'] as MediaSessionAction[])navigator.mediaSession.setActionHandler(action,null);};
  },[current?.url]);
  useEffect(()=>{if('mediaSession' in navigator)navigator.mediaSession.playbackState=!current?'none':playing?'playing':'paused';},[playing,current]);
  const player:Player={current,playing,position,duration,error,play,pause,seek,stop,startQueue,enqueue};
  return <Context.Provider value={player}><div className={current?'with-music-player':''}>{children}
    {current&&queueOpen&&<aside className="listening-queue" aria-label="Listening queue">
      <header><div><strong>Your listening queue</strong><small>{queue.index+1} of {queue.items.length} · This session</small></div><button aria-label="Hide listening queue" onClick={()=>setQueueOpen(false)}><X size={18}/></button></header>
      <div className="queue-current"><span className="discovery-eyebrow">NOW PLAYING</span><h3>{current.title}</h3><p>{current.artist}</p></div>
      {(current.trackId||current.candidateId)&&<PlayerReview key={current.id} item={current}/>}
      <div className="queue-list-heading"><strong>In this queue</strong><button className="text-button" disabled={queue.index===queue.items.length-1} onClick={()=>updateQueue({...queueRef.current,items:queueRef.current.items.slice(0,queueRef.current.index+1)})}>Clear upcoming</button></div>
      <ol>{queue.items.map((item,index)=><li key={item.url} ref={index===queue.index?activeRow:undefined} className={index===queue.index?'queue-active':''}>
        <button className="queue-track" aria-label={`Play queued track ${index+1}: ${item.title}`} aria-current={index===queue.index?'true':undefined} onClick={()=>jump(index)}><span>{index+1}</span><span><strong>{item.title}</strong><small>{item.artist} · {item.kind==='local'?'Your file':item.kind==='soundcloud'?'SoundCloud':'Preview'}</small></span></button>
        {index!==queue.index&&<button className="queue-remove" aria-label={`Remove ${item.title} from queue`} onClick={()=>updateQueue(removeQueued(queueRef.current,index))}><X size={13}/></button>}
      </li>)}</ol>
      <p className="queue-footnote">Tracks advance when playback ends. An unavailable file or preview pauses the queue; use Next to continue.</p>
    </aside>}
    <section className="taste-music-player" aria-label="Now playing" hidden={!current}>
      <div className="now-playing-copy"><Headphones size={19}/><div><strong>{current?.title}</strong><span>{current?.artist}</span><small>{current?.kind==='local'?`YOUR FILE · ${current.format||'LOCAL AUDIO'}`:current?.kind==='soundcloud'?'SOUNDCLOUD PLAYER':'ONLINE PREVIEW'}</small></div></div>
      <button className="player-skip" aria-label="Previous track" disabled={queue.index<=0} onClick={()=>step(-1)}><SkipBack size={18}/></button>
      <button className="player-skip" aria-label="Back 15 seconds" disabled={!duration} onClick={()=>seek(position-15)}><RotateCcw size={17}/><small>15</small></button>
      {current?.kind==='soundcloud'&&(cloudStarted?<SoundCloudPlayer key={current.url} ref={cloud} url={current.url} onPlaying={value=>{setPlaying(value);if(value)setError('');}} onPosition={setPosition} onDuration={setDuration} onEnd={ended} onError={failure}/>:<button className="primary" onClick={()=>play(current)}>Play on SoundCloud</button>)}
      <audio hidden={current?.kind==='soundcloud'} ref={audio} aria-label="Music playback" controls preload="none" onPlay={()=>{if(active.current?.kind!=='soundcloud'){setPlaying(true);setError('');}}} onPause={()=>{if(active.current?.kind!=='soundcloud')setPlaying(false);}} onEnded={ended} onError={()=>{if(active.current&&active.current.kind!=='soundcloud')failure();}}
        onTimeUpdate={e=>{if(active.current?.kind!=='soundcloud')setPosition(e.currentTarget.currentTime);}} onLoadedMetadata={e=>{if(active.current?.kind!=='soundcloud')setDuration(Number.isFinite(e.currentTarget.duration)?e.currentTarget.duration:0);}} onDurationChange={e=>{if(active.current?.kind!=='soundcloud')setDuration(Number.isFinite(e.currentTarget.duration)?e.currentTarget.duration:0);}}/>
      <button className="player-skip" aria-label="Forward 15 seconds" disabled={!duration} onClick={()=>seek(position+15)}><RotateCw size={17}/><small>15</small></button>
      <button className="player-skip" aria-label="Next track" disabled={queue.index>=queue.items.length-1} onClick={()=>step(1)}><SkipForward size={18}/></button>
      <button className="player-queue-toggle" aria-label="Show listening queue" aria-expanded={queueOpen} onClick={()=>setQueueOpen(!queueOpen)}><ListMusic size={18}/><small>{queue.index+1}/{queue.items.length}</small></button>
      <button className="player-close" aria-label="Close player" onClick={stop}><X size={17}/></button>
      {error&&<p className="player-error" role="alert">{error}</p>}
    </section>
  </div></Context.Provider>;
}

export function PlayControls({item}:{item:Playable}){
  const player=useMusicPlayer();const active=player.current?.url===item.url;
  return <><button className="primary" onClick={()=>active&&player.playing?player.pause():player.play(item)}>
    {active&&player.playing?<Pause size={15}/>:<Play size={15}/ >}{active&&player.playing?'Pause':item.kind==='local'?'Play from your library':item.kind==='soundcloud'?'Play on SoundCloud':'Play preview'}</button><button className="secondary" onClick={()=>player.enqueue(item)}><Plus size={14}/>Add to queue</button>
    <div className="preview-jumps">{[0,.25,.5,.75].map(p=><button key={p} disabled={!active||!player.duration} onClick={()=>player.seek(player.duration*p)}>{p===0?'Start':`${p*100}%`}</button>)}<span>{item.kind==='local'?'Positions in your full recording':item.kind==='soundcloud'?'Positions in this SoundCloud upload':'Positions within this preview'}</span></div>
    {active&&player.error&&<p role="alert">{player.error}</p>}</>;
}
