import { useCallback, useEffect, useState } from 'react';
import { ArrowUpRight, Check, Heart, Headphones, Import, Loader2, Plus, RefreshCw, Search, ThumbsDown, ThumbsUp, Users, X } from 'lucide-react';
import './discovery.css';
import TasteRecord from './TasteRecord';
import { PlayControls, useMusicPlayer } from './MusicPlayer';
import { trackPlayable, type Playable } from './listening-queue';
import { discoveryChanged } from './PlayerReview';
import Watches, { type WatchDraft } from './Watches';
import LibraryResearch from './LibraryResearch';
import TrackVideos from './TrackVideos';
import TrackResearch, { type TrackResearchData } from './TrackResearch';

type Credit = {name:string; person_key:string; role:string; followed:boolean};
type Source = {source:string; url:string;source_links?:{source:string;url:string}[];uploader?:string;identity_note?:string;content_kind?:string; preview_url?:string;label_url?:string; credits?:{name:string;url:string;role:string}[]; isrc?:string;source_title?:string};
export const uses=[['dj','DJ'],['sample','Sample'],['remix','Remix']] as const;
const sourceNames=['Beatport','Hypeddit','LDS','YouTube','SoundCloud','1001Tracklists','Soulseek','Manual'];
type Draft = {source:string;url:string;artist:string;title:string;source_title?:string;uploader?:string;note?:string};
type Track = {id:string; artist:string; title:string; favorite:boolean; owned:boolean; rating:number; bpm:number|null; musical_key:string|null;
  women_focus_matches?:{name:string;profile_key:string}[];
  local_audio:{id:string;url:string;name:string;format:string}[];
  uses:string[]; tasks:Record<string,{status:string;agent:string;note:string;updated_at:string}>;
  genre:string; label:string; release:string; release_date:string; upcoming:boolean; artwork:string; preview_url:string; soundcloud_url?:string;
  research?:TrackResearchData; query:string; score:number; reasons:string[]; sources:Source[]; credits:Credit[];
  cues:{preview_url:string;seconds:number;label:string}[]; lookups:{name:string;url:string}[]};
type Inbox = {women_focus?:{enabled:boolean;artists:{name:string;profile_key:string}[]};tracks:Track[]; people:{name:string;person_key:string;roles:string[];tracks:number;followed:boolean;search_url:string}[];
  feeds:{source:string;checked_at:string;added:number}[];beatport_available:boolean};
const blank:Inbox = {tracks:[],people:[],feeds:[],beatport_available:false};
const time = (s:number) => `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;

export default function Discovery({rpc,onSearch}:{rpc:(method:string,params?:Record<string,unknown>)=>Promise<any>;onSearch:(query:string,trackId?:string)=>void}) {
  const [data,setData] = useState<Inbox>(blank);
  const [loaded,setLoaded] = useState(false);
  const [selected,setSelected] = useState('');
  const [watchCount,setWatchCount]=useState(0);
  useEffect(()=>{let stopped=false;let pending=false;
    async function poll(){if(pending)return;pending=true;try{const state=await rpc('discovery_watch_state');if(!stopped)setWatchCount(state.pending_count);}catch{/* The watch screen presents detailed errors. */}finally{pending=false;}}
    void poll();const timer=setInterval(poll,15000);window.addEventListener('taste-discovery-changed',poll);return()=>{stopped=true;clearInterval(timer);window.removeEventListener('taste-discovery-changed',poll);};},[rpc]);
  const [watchDraft,setWatchDraft]=useState<WatchDraft|null>(null);
  function watchProfile(kind:string,query:string,url?:string){setWatchDraft({kind,query,url});setView('watches');}
  const [view,setView] = useState('inbox');
  const [personKey,setPersonKey] = useState('');
  const [peopleFilter,setPeopleFilter] = useState('');
  const [peopleLimit,setPeopleLimit] = useState(60);
  const [digQuery,setDigQuery] = useState('');
  const [filter,setFilter] = useState('');
  const [source,setSource] = useState('all');
  const [use,setUse] = useState('all');
  const [sort,setSort] = useState('taste');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [sourcesOpen,setSourcesOpen] = useState(false);
  const [linkOpen,setLinkOpen] = useState(false);
  const [link,setLink] = useState('');
  const [draft,setDraft] = useState<Draft|null>(null);
  const [genre,setGenre] = useState(0);
  const [artistFilter,setArtistFilter] = useState('');
  const [importSource,setImportSource] = useState('LDS');
  const [genres,setGenres] = useState([{id:91,name:'Bass House'},{id:5,name:'House'},{id:11,name:'Tech House'},{id:12,name:'Deep House'}]);
  const [cueName,setCueName] = useState('');
  const player=useMusicPlayer();
  const [audioChoice,setAudioChoice]=useState('');
  const playing=player.playing;
  const refresh = useCallback(async()=>{const value=await rpc('discovery_inbox');setData(value);setLoaded(true);},[rpc]);
  useEffect(()=>{void refresh().catch(e=>{setError(e.message);setLoaded(true);});},[refresh]);
  useEffect(()=>{const changed=()=>{void refresh().catch(e=>setError(e.message));};window.addEventListener('taste-discovery-changed',changed);return()=>window.removeEventListener('taste-discovery-changed',changed);},[refresh]);
  async function act(fn:()=>Promise<unknown>,message='') {
    setBusy(true);setError('');setNotice('');
    try{await fn();await refresh();discoveryChanged();if(message)setNotice(message);}catch(e:any){setError(e.message||'Could not update discovery.');}finally{setBusy(false);}
  }
  async function open(url:string){try{await window.soulseek!.openMusicLink(url);}catch(e:any){setError(e.message);}}
  const person=data.people.find(p=>p.person_key===personKey);
  const personTracks=person?data.tracks.filter(t=>t.credits.some(c=>c.person_key===person.person_key)):[];
  const supportedBy=[...new Set(personTracks.flatMap(t=>(t.research?.evidence||[]).filter(e=>e.kind==='dj_play'&&e.status==='confirmed').map(e=>e.subject)))];
  const profileLinks=personTracks.flatMap(t=>t.sources.flatMap(s=>(s.credits||[]).filter(c=>c.name===person?.name&&c.url))).filter((c,i,all)=>all.findIndex(other=>other.url===c.url)===i);
  const relatedPeople=data.people.filter(p=>p.person_key!==personKey&&personTracks.some(t=>t.credits.some(c=>c.person_key===p.person_key))).sort((a,b)=>a.name.localeCompare(b.name));
  function showPerson(key:string){setPersonKey(key);setView('artist');setFilter('');setSource('all');}
  let tracks=data.tracks.filter(t=>(view==='artist'?t.credits.some(c=>c.person_key===personKey):view==='watchlist'?t.favorite:view==='rated'?t.rating!==0:view==='library'?t.owned:t.rating!==-1&&!t.owned)
    &&(source==='all'||t.sources.some(s=>s.source===source))
    &&(view!=='library'||use==='all'||(use==='none'?!t.uses.length:t.uses.includes(use)))
    &&`${t.artist} ${t.title} ${t.credits.map(c=>c.name).join(' ')} ${t.label}`.toLowerCase().includes(filter.toLowerCase()));
  if(sort==='newest')tracks=[...tracks].sort((a,b)=>Number(!!data.women_focus?.enabled&&!!b.women_focus_matches?.length)-Number(!!data.women_focus?.enabled&&!!a.women_focus_matches?.length)||b.release_date.localeCompare(a.release_date)||a.title.localeCompare(b.title));
  const playableTracks=tracks.map(trackPlayable).filter((t):t is Playable=>!!t);
  const track=tracks.find(t=>t.id===selected)||tracks[0];
  const localFiles=track?.local_audio||[];
  const choices=[...localFiles.map(f=>({...f,kind:'local' as const})),...(track?.preview_url?[{id:'preview',url:track.preview_url,name:'Beatport preview',format:'',kind:'preview' as const}]:[]),...(track?.soundcloud_url?[{id:'soundcloud',url:track.soundcloud_url,name:'SoundCloud upload',format:'',kind:'soundcloud' as const}]:[])];
  const chosen=choices.find(c=>c.url===audioChoice)||choices[0];
  const active=!!chosen&&player.current?.url===chosen.url;
  const position=active?player.position:0;
  const length=active?player.duration:0;
  useEffect(()=>{setCueName('');},[track?.id,chosen?.url]);
  function seek(seconds:number){if(active)player.seek(seconds);}
  const react=(changes:Record<string,unknown>)=>track&&act(()=>rpc('discovery_react',{track_id:track.id,...changes}));
  const follow=(credit:Credit)=>act(()=>rpc('discovery_follow',{name:credit.name,enabled:!credit.followed}));

  return <section className="discovery-page">
    <header className="discovery-heading taste-hero">
      <div className="taste-hero-copy"><div className="discovery-eyebrow"><span className="taste-tiny-star" aria-hidden="true">✳</span> FOR THE LOVE OF THE FIND</div>
        <h1>Follow your ears.<br/><span>Find your flavor.</span></h1><p>New favorites, old gems, and very good rabbit holes.</p>
        <div className="discovery-heading-actions"><button className="primary" onClick={()=>setView('research')}>Research my library</button><button className="primary" onClick={()=>{setLinkOpen(!linkOpen);setDraft(null);setLink('');}}><Plus size={14}/>Add a find</button><button className="secondary" onClick={()=>setSourcesOpen(!sourcesOpen)} aria-expanded={sourcesOpen}>Manage sources</button></div>
      </div>
      <div className="taste-hero-art" aria-hidden="true"><div className="taste-record-sleeve"><TasteRecord playing={playing}/></div><span className="taste-spark spark-one">✴</span><span className="taste-spark spark-two">✳</span><span className="taste-good-sticker">GOOD<br/>STUFF</span><span className="taste-handnote">a little off the beaten track ↗</span></div>
    </header>
    {watchCount>0&&view!=='watches'&&<div className="discovery-message" role="status">{watchCount} finds from your watches are ready to hear.<button className="text-button" onClick={()=>setView('watches')}>Listen & review →</button></div>}
    {linkOpen&&<section className="discovery-sources" aria-label="Add discovery link"><h2>Bring a find into your inbox</h2><p>Paste a track, video, or set link. Confirm the artist and exact version before saving.</p><div className="discovery-source-controls"><input className="discovery-link-input" aria-label="Music source URL" placeholder="https://…" value={link} onChange={e=>{setLink(e.target.value);if(draft)setDraft({...draft,url:''});}}/>
      <button className="primary" disabled={busy||!link.trim()} onClick={()=>void act(async()=>{const value=await rpc('discovery_resolve',{url:link.trim()});setDraft({...value,artist:draft?.artist||'',title:draft?.title||value.title});})}>Read link</button><button aria-label="Close add link" onClick={()=>setLinkOpen(false)}><X size={14}/></button></div>
      {draft&&<><p>{draft.source}{draft.uploader?` · Uploaded by ${draft.uploader} (not necessarily the artist)`:''}</p>{draft.note&&<p>{draft.note}</p>}<div className="discovery-source-controls"><input aria-label="Track artist" placeholder="Artist / remixer" value={draft.artist} onChange={e=>setDraft({...draft,artist:e.target.value})} maxLength={250}/><input aria-label="Track title and version" placeholder="Track title (exact remix)" value={draft.title} onChange={e=>setDraft({...draft,title:e.target.value})} maxLength={500}/><button className="primary" disabled={busy||!draft.url||!draft.artist.trim()||!draft.title.trim()} onClick={()=>void act(async()=>{const r=await rpc('discovery_import',{records:[draft],source:draft.source});setSelected(r.track_ids[0]);setView('inbox');setFilter('');setSource('all');setLinkOpen(false);},'Saved to your inbox.')}>Save track & link</button></div></>}
    </section>}
    {sourcesOpen&&<section className="discovery-sources" aria-label="Discovery sources">
      <div><h2>Beatport <span className="discovery-status">{data.beatport_available?'Sign-in found':'Sign-in needed'}</span></h2><p>A broad batch across ten electronic genres, or up to 25 tracks in one genre. Includes upcoming releases.</p>
        <div className="discovery-source-controls"><select aria-label="Beatport genre" value={genre} onChange={e=>setGenre(Number(e.target.value))}><option value={0}>Broad electronic</option>{genres.map(g=><option key={g.id} value={g.id}>{g.name}</option>)}</select>
          <input aria-label="Beatport artist filter" placeholder="Artist name (optional)" value={artistFilter} onChange={e=>setArtistFilter(e.target.value)} maxLength={250}/>
          <button className="primary" disabled={busy||!data.beatport_available} onClick={()=>void act(async()=>{const r=await rpc('discovery_beatport',{genre_id:genre,artist_name:artistFilter});setNotice(`${r.added} new tracks added · ${r.received} checked.`);})}>{busy?<Loader2 className="spin" size={13}/>:<RefreshCw size={13}/>}Pull new tracks</button></div>
        <button className="text-button" disabled={busy||!data.beatport_available} onClick={()=>void act(async()=>{const r=await rpc('discovery_beatport',{operation:'genres'});setGenres(r.genres);})}>Load all genres</button>
      </div>
      <div className="source-directory">{[['YouTube','Link metadata'],['SoundCloud','Upload watches + player'],['1001Tracklists','Link / list import'],['Hypeddit','Link / list import'],['LDS','Link / list import'],['Soulseek','Search handoff']].map(([name,status])=><div key={name}><strong>{name}</strong><small>{status}</small></div>)}</div>
      <div><h2>Your existing music <span className="discovery-status quiet">Local taste seeds</span></h2><p>Read artist, title, genre, and BPM tags from a folder. Owned tracks gently guide recommendations and stay out of the new-track inbox.</p><button className="secondary" disabled={busy} onClick={()=>void act(async()=>{const r=await window.soulseek!.seedDiscovery();if(r)setNotice(`${r.matched_files} files matched · ${r.added} tracks added · ${r.skipped+r.unreadable} skipped${r.filename_inferences?` · ${r.filename_inferences} inferred from filenames`:''}${r.truncated?' · Scan limited to 5,000 files':''}.`);})}><Import size={13}/>Import music folder</button></div>
      <div><h2>Import from any source <span className="discovery-status quiet">One shared inbox</span></h2><p>Bring a saved track list into the same inbox. Beatport and connected SoundCloud profiles support watches. Other sources use links or list imports.</p>
        <div className="discovery-source-controls"><select aria-label="Import source" value={importSource} onChange={e=>setImportSource(e.target.value)}>{sourceNames.map(s=><option key={s}>{s}</option>)}</select>
          <button className="secondary" disabled={busy} onClick={()=>void act(async()=>{const r=await window.soulseek!.importDiscovery(importSource);if(r)setNotice(`${r.added} new tracks imported.`);})}><Import size={13}/>Import JSON</button>
          <button className="text-button" onClick={()=>void open('https://hypeddit.com/newreleases')}>Explore Hypeddit <ArrowUpRight size={12}/></button>
          <button className="text-button" onClick={()=>void open('https://livedjservice.com/')}>Open LDS <ArrowUpRight size={12}/></button></div>
      </div>
    </section>}
    {error&&<div className="discovery-message error" role="alert">{error}<button onClick={()=>void act(refresh)}>Retry</button></div>}
    {notice&&<div className="discovery-message" role="status"><Check size={14}/>{notice}<button aria-label="Dismiss discovery notice" onClick={()=>setNotice('')}><X size={13}/></button></div>}
    <section className="women-focus-bar" aria-label="Listening focus"><div><strong>A little more room for women.</strong><p>{data.women_focus?.enabled?'Women focus is on. Matches move up in track lists, research, and watches. Your other music stays available.':'Turn on Women focus to prioritize artists with sourced representation information.'} {data.women_focus?.artists.length||0} artist profiles included.</p></div><button className={`secondary ${data.women_focus?.enabled?'chosen':''}`} aria-pressed={!!data.women_focus?.enabled} disabled={busy} onClick={()=>void act(()=>rpc('discovery_representation_mode',{enabled:!data.women_focus?.enabled}))}>Women focus {data.women_focus?.enabled?'on':'off'}</button>{data.women_focus?.enabled&&<button className="secondary" disabled={busy||!data.beatport_available||!data.women_focus.artists.length} onClick={()=>void act(async()=>{const r=await rpc('discovery_representation_explore');setNotice(`${r.added} new findings from ${r.profiles_checked} artist profiles.${r.errors.length?` Could not read: ${r.errors.join(', ')}.`:''}`);setView('research');})}>Find music for this focus</button>}<button className="text-button" onClick={()=>setView('watches')}>Review artist information</button></section>
    <div className="discovery-tabs" role="tablist" aria-label="Discovery views">{[
      ['inbox','Fresh picks',data.tracks.filter(t=>t.rating!==-1&&!t.owned).length],['watchlist','Favorites',data.tracks.filter(t=>t.favorite).length],
      ['people','Artists',data.people.length],['library','Library',data.tracks.filter(t=>t.owned).length],['rated','Rated',data.tracks.filter(t=>t.rating!==0).length],['research','Research',null],['watches','Watches',watchCount],['dig','Dig',null]
    ].map(([id,label,count])=><button key={id} role="tab" aria-selected={view===id||(id==='people'&&view==='artist')} onClick={()=>setView(String(id))}>{label}{count!==null&&<span>{count}</span>}</button>)}</div>
    {view==='watches'?<Watches tracks={data.tracks} available={data.beatport_available} rpc={rpc} onChanged={refresh} onSearch={onSearch} open={open} draft={watchDraft}/>:view==='research'?<LibraryResearch tracks={data.tracks} available={data.beatport_available} rpc={rpc} onChanged={refresh} onSearch={onSearch} open={open}/>:view==='dig'?<section className="discovery-dig" aria-label="Dig for music">
      <div className="discovery-eyebrow">FOLLOW A HUNCH</div><h2>Take the scenic route.</h2><p>An artist, a year, a label, or a phrase. Leave room for something you weren’t looking for.</p>
      <form className="discovery-source-controls" onSubmit={e=>{e.preventDefault();if(digQuery.trim())onSearch(digQuery.trim());}}><input aria-label="Dig query" placeholder="1975, jazz funk, an artist, a label…" value={digQuery} maxLength={256} onChange={e=>setDigQuery(e.target.value)}/><button className="primary" disabled={!digQuery.trim()}><Search size={14}/>Dig on Soulseek</button></form>
      <div className="dig-prompts">{['1975','jazz funk','disco edits'].map(q=><button className="secondary" key={q} onClick={()=>setDigQuery(q)}>{q}</button>)}<button className="secondary" disabled={!data.tracks.some(t=>t.owned&&t.credits.length)} onClick={()=>{const seeds=data.people.filter(p=>data.tracks.some(t=>t.owned&&t.credits.some(c=>c.person_key===p.person_key)));if(seeds.length)setDigQuery(seeds[Math.floor(Math.random()*seeds.length)].name);}}>Pick an artist from my library</button></div>
      <div className="dig-guide"><h3>Turn a search into a rabbit hole</h3><p>Switch results to Folders to explore possible albums. Open a peer’s collection to see what else they share, or save the query to your wishlist.</p><p>A year matches text in shared paths; it isn’t a verified release-date filter. Folder names and artist matches are clues to check.</p><p>Digging doesn’t change your taste profile. Import something you keep, or rate a collected track when you want it to influence discovery.</p></div>
    </section>:view==='people'?<div className="discovery-people"><div className="discovery-section-intro"><h2>Meet the music makers.</h2><p>Explore the music we’ve collected for each artist, remixer, and editor. Follow the people you want to hear more from.</p><input aria-label="Find an artist" placeholder="Find an artist or remixer…" value={peopleFilter} onChange={e=>{setPeopleFilter(e.target.value);setPeopleLimit(60);}}/></div>
      {data.people.length===0&&<p>Pull a batch of tracks to find artists and remixers.</p>}
      {[...data.people].filter(p=>p.name.toLowerCase().includes(peopleFilter.toLowerCase())).sort((a,b)=>Number(b.followed)-Number(a.followed)||a.name.localeCompare(b.name)).slice(0,peopleLimit).map(p=><article key={p.person_key}><div className="person-avatar"><Users size={18}/></div><div><button className="person-name" onClick={()=>showPerson(p.person_key)}>{p.name}</button><p>{p.roles.join(' · ')} · {p.tracks} {p.tracks===1?'track':'tracks'} collected</p></div>
        <button className="text-button" onClick={()=>showPerson(p.person_key)}>Explore artist</button><button className="secondary" disabled={busy} aria-pressed={p.followed} onClick={()=>void act(()=>rpc('discovery_follow',{name:p.name,enabled:!p.followed}))}>{p.followed?<Check size={13}/>:<Plus size={13}/ >}{p.followed?'Following':'Follow'}</button></article>)}
      {data.people.filter(p=>p.name.toLowerCase().includes(peopleFilter.toLowerCase())).length>peopleLimit&&<button className="secondary" onClick={()=>setPeopleLimit(n=>n+60)}>Show more artists</button>}
      {data.people.length>0&&!data.people.some(p=>p.name.toLowerCase().includes(peopleFilter.toLowerCase()))&&<p>No collected artists match that name.</p>}
    </div>:<>
      {view==='artist'&&person&&<section className="artist-summary" aria-label="Artist profile"><button className="text-button" onClick={()=>setView('people')}>← All artists</button><div className="artist-summary-heading"><div><div className="discovery-eyebrow">FROM YOUR COLLECTED MUSIC</div><h2>{person.name}</h2><p>{person.roles.join(' · ')} · {personTracks.length} tracks · {personTracks.filter(t=>t.owned).length} owned · {personTracks.filter(t=>t.favorite).length} favorites</p></div><button className="secondary" disabled={busy} aria-pressed={person.followed} onClick={()=>void act(()=>rpc('discovery_follow',{name:person.name,enabled:!person.followed}))}>{person.followed?'Following':'+ Follow'}</button></div>
        <div className="dig-prompts"><button className="secondary" onClick={()=>watchProfile('artist',person.name,profileLinks.find(p=>p.url.includes('beatport.com/artist/'))?.url)}>Watch new releases</button><button className="primary" onClick={()=>onSearch(person.name)}>Find music on Soulseek <ArrowUpRight size={13}/></button><button className="secondary" onClick={()=>{setDigQuery(`${person.name} remix`);setView('dig');}}>Dig for remixes</button>{profileLinks.map(p=><button className="text-button" key={p.url} onClick={()=>void open(p.url)}>Source profile <ArrowUpRight size={12}/></button>)}</div>
        <p>Collected credits, not a complete discography. Soulseek searches shared filenames; check the artist and version.</p>
        {supportedBy.length>0&&<p>Recorded DJ support for collected tracks: {supportedBy.join(', ')}. Exact versions confirmed by you; names may include aliases.</p>}
        {relatedPeople.length>0&&<div className="artist-connections"><span>Appears on the same tracks as</span>{relatedPeople.slice(0,12).map(p=><button className="text-button" key={p.person_key} onClick={()=>showPerson(p.person_key)}>{p.name}</button>)}</div>}
      </section>}
      <div className="discovery-filters"><label><Search size={14}/><input aria-label="Filter discovery tracks" placeholder="Find a track, artist, or label…" value={filter} onChange={e=>setFilter(e.target.value)}/></label>
        <select aria-label="Discovery source filter" value={source} onChange={e=>setSource(e.target.value)}><option value="all">All sources</option>{[...sourceNames,'Library'].map(s=><option key={s}>{s}</option>)}</select>
        {view==='library'&&<select aria-label="Library use filter" value={use} onChange={e=>setUse(e.target.value)}><option value="all">All uses</option>{uses.map(([id,label])=><option key={id} value={id}>{label}</option>)}<option value="none">Not marked yet</option></select>}
        <select aria-label="Discovery sort" value={sort} onChange={e=>setSort(e.target.value)}><option value="taste">For you</option><option value="newest">Release date</option></select><span>{tracks.length} tracks</span><button className="primary" disabled={!playableTracks.length} onClick={()=>player.startQueue(playableTracks)}>Listen to {view==='library'?'library':'these picks'} ({playableTracks.length})</button></div>
      {tracks.length>0&&<p className="queue-availability">{playableTracks.length} playable · {tracks.length-playableTracks.length} have no inline audio; open their source to listen. The queue follows this list’s filters and order.</p>}
      {!loaded?<div className="discovery-empty"><Loader2 className="spin"/><h2>Opening your inbox…</h2></div>:!track?<div className="discovery-empty"><Headphones size={35}/><h2>{data.tracks.length?'Nothing in this view yet.':'Start with a fresh batch.'}</h2><p>{data.tracks.length?'Try another filter, or favorite a track to keep it here.':'Pull new tracks from Beatport or import a track list. Your favorites and ratings stay on this computer.'}</p><button className="primary" onClick={()=>setSourcesOpen(true)}>Choose your sources</button></div>:
      <div className="discovery-layout"><div className="discovery-track-list" aria-label="Discovery tracks">{tracks.map(t=><button key={t.id} className={`discovery-track ${t.id===track.id?'selected':''}`} aria-pressed={t.id===track.id} onClick={()=>setSelected(t.id)}>
        <span className="track-art">{t.artwork?<img src={t.artwork} alt="" loading="lazy" referrerPolicy="no-referrer"/>:<span className="taste-sleeve-record" aria-hidden="true"/>}</span><span className="track-copy"><strong>{t.title}</strong><span>{t.artist}</span><small>{t.sources.map(s=>s.source).filter((s,i,a)=>a.indexOf(s)===i).join(' + ')}{t.genre?` · ${t.genre}`:''}</small></span>
        <span className="track-flags">{t.uses.map(u=><small className="use-badge" key={u}>{uses.find(([id])=>id===u)?.[1]}</small>)}{data.women_focus?.enabled&&!!t.women_focus_matches?.length&&<small className="women-focus-badge">Women focus</small>}{t.favorite&&<Heart size={13} fill="currentColor"/>}{t.rating===1&&<ThumbsUp size={13}/ >}{t.rating===-1&&<ThumbsDown size={13}/ >}<small>{t.bpm?`${t.bpm} BPM`:''}</small></span>
      </button>)}</div>
      <article className="discovery-detail" aria-label="Selected discovery track">
        <div className="detail-overline">{track.owned?'IN YOUR LIBRARY':track.upcoming?'UPCOMING RELEASE':'ON YOUR RADAR'}<span>{track.release_date||'Release date unknown'}</span></div>
        <h2>{track.title}</h2><p className="detail-artist">{track.artist}</p>
        <div className="discovery-metadata">{track.bpm&&<span>{track.bpm} BPM</span>}{track.musical_key&&<span>{track.musical_key}</span>}{track.genre&&<span>{track.genre}</span>}</div>
        <div className="discovery-reactions"><button className={`secondary ${track.favorite?'chosen':''}`} aria-pressed={track.favorite} disabled={busy} onClick={()=>void react({favorite:!track.favorite})}><Heart size={15} fill={track.favorite?'currentColor':'none'}/>{track.favorite?'Favorited':'Favorite track'}</button>
          <button className={`secondary ${track.rating===1?'chosen':''}`} aria-label="Thumbs up" aria-pressed={track.rating===1} disabled={busy} onClick={()=>void react({rating:track.rating===1?0:1})}><ThumbsUp size={15}/></button>
          <button className={`secondary ${track.rating===-1?'chosen':''}`} aria-label="Thumbs down" aria-pressed={track.rating===-1} disabled={busy} onClick={()=>void react({rating:track.rating===-1?0:-1})}><ThumbsDown size={15}/></button></div>
        <section className={`discovery-player ${active&&playing?'is-playing':''}`}><h3><Headphones size={14}/>{chosen?.kind==='local'?'Listen from your library':chosen?.kind==='soundcloud'?'Listen on SoundCloud':'Listen to the preview'}</h3>
          {chosen?<><div className="local-recording-picker">{choices.length>1?<><label htmlFor="recording-source">Recording to play</label><select id="recording-source" value={chosen.url} onChange={e=>setAudioChoice(e.target.value)}>{choices.map(c=><option value={c.url} key={c.url}>{c.kind==='local'?`Your file · ${c.format} · ${c.name}`:c.name}</option>)}</select></>:<p>{chosen.kind==='local'?`Your file · ${chosen.format} · ${chosen.name}`:chosen.kind==='soundcloud'?'Official SoundCloud player · availability is controlled by the uploader':'Online preview · not the full recording'}</p>}</div>
            <PlayControls item={{id:track.id,trackId:track.id,sources:track.sources,reasons:track.reasons,credits:track.credits,url:chosen.url,kind:chosen.kind,title:track.title,artist:track.artist,format:chosen.format,artwork:track.artwork}}/>
            <div className="cue-save"><input aria-label="Cue label" placeholder="Name this moment…" maxLength={80} value={cueName} onChange={e=>setCueName(e.target.value)}/><button className="text-button" disabled={busy||!length} onClick={()=>void act(()=>rpc('discovery_cue',{track_id:track.id,preview_url:chosen.url,seconds:Math.round(position*10)/10,label:cueName.trim()||'Saved moment'}))}><Plus size={12}/>Save {time(position)}</button></div>
            {track.cues.filter(c=>c.preview_url===chosen.url).map(c=><div className="cue-item" key={c.seconds}><button disabled={!active||!length} onClick={()=>seek(c.seconds)}>{time(c.seconds)} · {c.label}</button><button aria-label={`Remove cue ${c.label}`} disabled={busy} onClick={()=>void act(()=>rpc('discovery_cue',{track_id:track.id,...c,remove:true}))}><X size={12}/></button></div>)}
            {chosen.kind==='local'&&<button className="text-button" onClick={()=>void window.soulseek!.openLocalAudio(track.id,chosen.id).catch(e=>setError(e.message))}>Open file in your music app <ArrowUpRight size={12}/></button>}
          </>:<p>{track.owned?'Re-import this music folder to reconnect its local recordings.':'No inline preview available. Open a source below to listen.'}</p>}
        </section>
        {track.owned&&<section className="discovery-context library-uses" aria-label="Library uses"><h3>What it’s for</h3>
          <div className="use-toggles">{uses.map(([id,label])=><button key={id} className={`secondary ${track.uses.includes(id)?'chosen':''}`} aria-pressed={track.uses.includes(id)} disabled={busy} onClick={()=>void act(()=>rpc('discovery_library_mark',{track_id:track.id,uses:track.uses.includes(id)?track.uses.filter(u=>u!==id):[...track.uses,id]}))}>{track.uses.includes(id)&&<Check size={13}/>}{label}</button>)}</div>
          <p>Agents connected through MCP can find marked tracks and pick up work like stem separation.</p>
          {Object.entries(track.tasks).map(([name,task])=><p className="use-task" key={name}><strong>{name}</strong> · {task.status==='claimed'?'in progress':task.status} · {task.agent}{task.note?` · ${task.note}`:''}</p>)}
        </section>}
        <section className="discovery-context"><h3>Why it’s here</h3>{track.reasons.map(reason=><p key={reason}>{reason}</p>)}</section>
        <section className="discovery-context"><h3>People & context</h3>{track.credits.map(c=>{const profile=track.sources.flatMap(s=>s.credits||[]).find(p=>p.name===c.name&&p.url);return <div className="credit-row" key={`${c.person_key}-${c.role}`}><div><button className="text-button artist-credit" onClick={()=>showPerson(c.person_key)}>{c.name}</button><small>{c.role}</small></div>{profile&&<button className="text-button" onClick={()=>void open(profile.url)}>Profile <ArrowUpRight size={11}/></button>}<button className={`text-button ${c.followed?'chosen':''}`} disabled={busy} onClick={()=>void follow(c)}>{c.followed?'Following':'+ Follow'}</button></div>;})}
          {track.label&&<p>Label · <strong>{track.label}</strong> <button className="text-button" onClick={()=>watchProfile('label',track.label,track.sources.find(s=>s.label_url)?.label_url)}>Watch label</button></p>}{track.release&&<p>Release · {track.release}</p>}
          {track.owned&&<p>Already in your music library · a taste seed, not an automatic favorite.</p>}
        </section>
        <TrackVideos key={`videos:${track.id}`} trackId={track.id} query={track.query} rpc={rpc} open={open}/>
        <TrackResearch key={track.id} trackId={track.id} query={track.query} research={track.research} busy={busy} act={act} rpc={rpc} open={open} onSearch={onSearch}/>
        <section className="discovery-context"><h3>Listen / get this version</h3>{track.sources.filter(s=>s.uploader).map((s,i)=><p key={i}>Uploaded by {s.uploader} · {s.identity_note||'Uploader is not necessarily the recording artist.'}</p>)}<div className="source-links">{track.sources.flatMap(s=>s.source_links||[]).map(s=><button className="secondary" key={s.url} onClick={()=>void open(s.url)}>Uploader link · {s.source} <ArrowUpRight size={12}/></button>)}</div><div className="source-links">{track.sources.filter(s=>s.url).map((s,i)=><button className="secondary" key={`${s.source}-${i}`} onClick={()=>void open(s.url)}>{s.source==='Beatport'?'View on Beatport':`Open ${s.source}`}<ArrowUpRight size={12}/></button>)}</div>
          <button className="text-button attach-source" onClick={()=>{setDraft({artist:track.artist,title:track.title,url:'',source:'Manual'});setLink('');setLinkOpen(true);}}>+ Attach another source for this version</button>
          <p className="lookup-note">Look elsewhere · verify the remix before collecting</p><div className="lookup-links"><button onClick={()=>onSearch(track.query)}>Search Soulseek <ArrowUpRight size={12}/></button>{track.lookups.map(link=><button key={link.name} onClick={()=>void open(link.url)}>{link.name} <ArrowUpRight size={12}/></button>)}</div>
        </section>
      </article></div>}
    </>}
    <footer className="discovery-footer"><span>Keep what moves you. Your taste grows from here.</span><span>Watches check on schedule · {data.tracks.length} tracks collected</span></footer>
  </section>;
}
