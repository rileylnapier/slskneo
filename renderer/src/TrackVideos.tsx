import { useEffect, useState } from 'react';
import { useMusicPlayer } from './MusicPlayer';
const kinds:Record<string,string>={music_video:'Music video',live:'Live / performance',visualizer:'Visualizer',lyric:'Lyric video',audio:'Audio upload',other:'Other / unknown'};
type Video={video_id:string;url:string;title:string;channel:string;kind:string;confirmed:boolean;origin:string};
type State={videos:Video[];configured:boolean;checked_at:string|null};
export default function TrackVideos({trackId,query,rpc,open}:{trackId:string;query:string;rpc:(method:string,params?:Record<string,unknown>)=>Promise<any>;open:(url:string)=>Promise<void>}){
  const [state,setState]=useState<State>({videos:[],configured:false,checked_at:null});
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('');
  const [setup,setSetup]=useState(false);const [apiKey,setApiKey]=useState('');
  const [url,setUrl]=useState('');const [title,setTitle]=useState('');const [kind,setKind]=useState('other');const [confirmed,setConfirmed]=useState(false);
  const [editing,setEditing]=useState(false);
  const [filter,setFilter]=useState('all');const player=useMusicPlayer();
  useEffect(()=>{let stopped=false;void rpc('discovery_video_state',{track_id:trackId}).then(r=>{if(!stopped)setState(r);}).catch(e=>{if(!stopped)setError(e.message);});return()=>{stopped=true;};},[rpc,trackId]);
  async function act(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await fn();}catch(e:any){setError(e.message||'Could not update videos.');}finally{setBusy(false);}}
  async function watch(link:string){player.pause();await open(link);}
  return <section className="discovery-context track-videos" aria-label="YouTube videos for this song"><h3>See the song.</h3><p>Music videos, performances, visualizers, lyrics, and audio uploads—all on equal footing. Results are possible matches; check the artist and version.</p>
    <div className="source-links"><button className="secondary" disabled={busy||!state.configured} onClick={()=>void act(async()=>{setState(await rpc('discovery_video_search',{track_id:trackId}));setNotice('YouTube results saved for review. Type labels are title hints.');})}>{busy?'Working…':'Find videos'}</button><button className="text-button" onClick={()=>void act(()=>watch('https://www.youtube.com/results?search_query='+encodeURIComponent(query)))}>Search on YouTube ↗</button><button className="text-button" onClick={()=>setSetup(!setup)}>{state.configured?'Update YouTube connection':'Set up YouTube search'}</button></div>
    {!state.configured&&<p>Save links now, or connect a YouTube Data API key to bring search results into Taste.</p>}
    {setup&&<form onSubmit={e=>{e.preventDefault();void act(async()=>{await window.soulseek!.saveYouTube(apiKey);setApiKey('');setSetup(false);setState(await rpc('discovery_video_state',{track_id:trackId}));setNotice('API key encrypted and saved. Find videos will verify access.');});}}><label>YouTube Data API key<input type="password" aria-label="YouTube Data API key" autoComplete="off" value={apiKey} onChange={e=>setApiKey(e.target.value)} maxLength={512}/></label><button className="secondary" disabled={busy||apiKey.trim().length<10}>Save encrypted key</button><p>Enable YouTube Data API v3 for this key. It is stored encrypted on this Mac and sent only to Google’s API. Searches run when you choose Find videos and use your project’s quota.</p></form>}
    {state.checked_at&&<p>Last search: {new Date(state.checked_at).toLocaleString()}</p>}
    {state.videos.length>0&&<><select aria-label="Video type filter" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All video types</option>{Object.entries(kinds).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select><div className="video-results">{state.videos.filter(v=>filter==='all'||v.kind===filter).map(v=><article key={v.video_id}><strong>{v.title}</strong><p>{kinds[v.kind]}{v.channel?` · ${v.channel}`:''}</p><small>{v.confirmed?'Match confirmed by you':'Possible match · check the recording/version'}</small><div className="source-links"><button className="secondary" onClick={()=>void act(()=>watch(v.url))}>Watch on YouTube ↗</button><button className="text-button" onClick={()=>{setUrl(v.url);setTitle(v.title);setKind(v.kind);setConfirmed(!!v.confirmed);setEditing(true);}}>Review / edit</button></div></article>)}</div></>}
    <details open={editing} onToggle={e=>setEditing(e.currentTarget.open)}><summary>Save or review a video link</summary><form onSubmit={e=>{e.preventDefault();void act(async()=>{setState(await rpc('discovery_video_save',{track_id:trackId,url,title,kind,confirmed}));setUrl('');setTitle('');setKind('other');setConfirmed(false);setNotice('Video linked to this song. Your music preferences are unchanged.');});}}>
      <label>YouTube link<input aria-label="YouTube video link" value={url} onChange={e=>{setUrl(e.target.value);setConfirmed(false);}} placeholder="https://www.youtube.com/watch?v=…" maxLength={2048}/></label>
      <label>Video title<input aria-label="YouTube video title" value={title} onChange={e=>setTitle(e.target.value)} maxLength={500}/></label>
      <label>Video type<select aria-label="Saved video type" value={kind} onChange={e=>setKind(e.target.value)}>{Object.entries(kinds).map(([value,label])=><option value={value} key={value}>{label}</option>)}</select></label>
      <label className="profile-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I checked how this video relates to this recording.</label>
      <button className="secondary" disabled={busy||!url.trim()||!title.trim()}>Save video link</button>
    </form></details><p className="lookup-note">Videos open on YouTube. Saving a video does not replace your audio, favorite a song, or confirm an official uploader.</p>
    {error&&<p role="alert" className="discovery-message error">{error}</p>}{notice&&<p role="status">{notice}</p>}
  </section>;
}
