import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import {
  ArrowDown, ArrowDownToLine, ArrowRight, ArrowUp, ArrowUpRight, Bell, Check,
  CheckCircle2, ChevronLeft, ChevronRight, CircleHelp, Clock3, Download, ExternalLink,
  Folder, FolderDown, FolderOpen, HardDrive, Heart, Info, ListFilter, Loader2,
  LockKeyhole, Music2, Pause, Play, Plus, Power, Radio, RefreshCw, Search,
  Settings2, ShieldCheck, SlidersHorizontal, Trash2, Upload, UserRound, Wifi, X,
} from 'lucide-react';
import type { SearchRecord, SearchResult, Settings, Snapshot, Tab, Transfer, Wish } from './types';
import Discovery, { uses } from './Discovery';
import { groupSearchFolders } from './search-folders';

const initial: Snapshot = {status: {connected: false, credentials_configured: false}, searches: [], transfers: [], uploads: [], wishlist: [], shares: [], history: []};
const nav = [{id:'discover',title:'Discover',icon:Radio}, {id:'search', title:'Search', icon:Search}, {id:'downloads',title:'Downloads',icon:ArrowDownToLine}, {id:'shares',title:'Shared Files',icon:FolderOpen}, {id:'wishlist',title:'Wishlist',icon:Heart}, {id:'settings',title:'Settings',icon:Settings2}] as const;
const titles: Record<Tab,string> = {discover:'Discover',search:'Search',downloads:'Downloads',shares:'Shared Files',wishlist:'Wishlist',settings:'Settings'};
function filename(path = '') { return path.split(/[\\/]/).pop() || path; }
function folder(path = '') { const normalized=path.replaceAll('/', '\\'); return normalized.includes('\\')?normalized.replace(/[\\][^\\]*$/, ''):'.'; }
function formatBytes(value: number | null | undefined) {
  const n = Number(value || 0); if (n < 1024) return `${n} B`;
  const index = Math.min(Math.floor(Math.log(n) / Math.log(1024)), 4);
  return `${(n / 1024 ** index).toFixed(index === 1 ? 0 : 1)} ${['B','KB','MB','GB','TB'][index]}`;
}
function formatDate(value: any) {
  if (!value) return 'Not searched yet';
  const time = typeof value === 'number' ? value * (value < 1e12 ? 1000 : 1) : value;
  const date = new Date(time); return Number.isNaN(date.getTime()) ? 'Recently' : date.toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
}
function duration(seconds: number) { return `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`; }
function iconButton(icon: ReactNode, title: string, action: () => void, disabled=false, extra='') {
  return <button type="button" className={`icon-button ${extra}`} title={title} aria-label={title} onClick={action} disabled={disabled}>{icon}</button>;
}
function Badge({children, tone='muted'}: {children:ReactNode;tone?:string}) { return <span className={`badge ${tone}`}>{children}</span>; }
function Empty({icon, title, description, action}: {icon:ReactNode; title:string; description:string; action?:ReactNode}) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{description}</p>{action}</div>;
}
function Toggle({checked,onChange,label,disabled=false}: {checked:boolean;onChange:()=>void;label:string;disabled?:boolean}) {
  return <button type="button" className={`toggle ${checked ? 'on' : ''}`} role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={onChange}><span /></button>;
}
export default function App() {
  const [tab,setTab] = useState<Tab>('discover');
  const [snapshot,setSnapshot] = useState<Snapshot>(initial);
  const [ready,setReady] = useState(false);
  const [backendError,setBackendError] = useState('');
  const [busy,setBusy] = useState<Record<string,boolean>>({});
  const [toast,setToast] = useState<{message:string;type:'success'|'error'}|null>(null);
  const [query,setQuery] = useState('');
  const [researchIntent,setResearchIntent] = useState<{query:string;trackId:string}|null>(null);
  const [searchId,setSearchId] = useState('');
  const [filter,setFilter] = useState('');
  const [extension,setExtension] = useState('');
  const [minBitrate,setMinBitrate] = useState(0);
  const [sort,setSort] = useState('filename');
  const [offset,setOffset] = useState(0);
  const [results,setResults] = useState<SearchResult[]>([]);
  const [resultView,setResultView] = useState('files');
  const [resultPage,setResultPage] = useState<any>(null);
  const [resultError,setResultError] = useState('');
  const [resultsLoading,setResultsLoading] = useState(false);
  const [selected,setSelected] = useState<Set<string>>(new Set());
  const [downloadUses,setDownloadUses] = useState<string[]>([]);
  const [downloadFilter,setDownloadFilter] = useState('all');
  const [wishlistQuery,setWishlistQuery] = useState('');
  const [browse,setBrowse] = useState<{username:string;loading:boolean;results:SearchResult[];search_id?:string;error?:string;truncated?:boolean;total_retained?:number;total_filtered?:number;next_offset?:number|null}|null>(null);
  const [browseOffset,setBrowseOffset] = useState(0);
  const [browsePageLoading,setBrowsePageLoading] = useState(false);
  const [browseFilter,setBrowseFilter] = useState('');
  const [settings,setSettings] = useState<Settings|null>(null);
  const [password,setPassword] = useState('');
  const [hasPassword,setHasPassword] = useState(false);
  const [settingsDirty,setSettingsDirty] = useState(false);
  const [showAdvanced,setShowAdvanced] = useState(false);
  const searchInput = useRef<HTMLInputElement>(null);
  const savedUsername = useRef('');
  const connected = snapshot.status.connected;
  const searchRecord = snapshot.searches.find(s => s.search_id === searchId);
  const activeDownloads = snapshot.transfers.filter(t => !['COMPLETE','FAILED','ABORTED','PAUSED','REMOVED','INCOMPLETE','INTERRUPTED'].includes(t.state));
  const completed = snapshot.transfers.filter(t => t.state === 'COMPLETE');
  const speed = snapshot.transfers.reduce((sum,t)=>sum+(t.speed_bytes_per_second||0),0);
  const visibleTransfers = snapshot.transfers.filter(t => downloadFilter === 'all' || (downloadFilter === 'complete' ? t.state === 'COMPLETE' : t.state !== 'COMPLETE'));

  const rpc = useCallback(async (method:string,params:Record<string,unknown>={}) => {
    if (!window.soulseek) throw new Error('Open Taste from the desktop app to use the local client.');
    return window.soulseek.rpc(method,params);
  },[]);
  const refresh = useCallback(async () => {
    try {
      const next = await rpc('snapshot');
      const value:Snapshot = {...initial,...next,status:{...initial.status,...next.status}};
      setSnapshot(value); setReady(true); setBackendError(''); return value;
    } catch(error:any) { setBackendError(error.message || 'The local client is unavailable.'); return undefined; }
  },[rpc]);
  useEffect(()=>{let active=true;let timer:ReturnType<typeof setTimeout>;const tick=async()=>{await refresh();if(active)timer=setTimeout(tick,2000);};void tick();return()=>{active=false;clearTimeout(timer);};},[refresh]);
  useEffect(()=>{if(!toast)return;const t=setTimeout(()=>setToast(null),6000);return()=>clearTimeout(t);},[toast]);
  useEffect(()=>{
    const handler=(event:KeyboardEvent)=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();setTab('search');setTimeout(()=>searchInput.current?.focus(),40);}if(event.key==='Escape')setBrowse(null);};
    window.addEventListener('keydown',handler);return()=>window.removeEventListener('keydown',handler);
  },[]);

  async function run<T>(name:string,action:()=>Promise<T>,message?:string):Promise<T|undefined>{
    setBusy(previous=>({...previous,[name]:true}));
    try{const result=await action();if(message)setToast({message,type:'success'});await refresh();return result;}
    catch(error:any){setToast({message:error.message||'Something went wrong. Try again.',type:'error'});return undefined;}
    finally{setBusy(previous=>({...previous,[name]:false}));}
  }
  const loadSettings = useCallback(async()=>{
    try{const value=await rpc('settings_get');setSettings(value);const credentials=await window.soulseek?.getCredentials();setHasPassword(Boolean(credentials?.hasPassword||value.credentials_configured));savedUsername.current=credentials?.username||value.username||'';if(credentials?.username&&!value.username)setSettings({...value,username:credentials.username});}
    catch(error:any){setToast({message:error.message,type:'error'});}
  },[rpc]);
  useEffect(()=>{if(ready&&!settings)void loadSettings();},[ready,settings,loadSettings]);
  useEffect(()=>{
    if(!searchId){setResults([]);setResultPage(null);setResultError('');return;}
    let active=true;let timer:ReturnType<typeof setTimeout>;setResultsLoading(true);
    const tick=async()=>{
      try{const response=await rpc('results',{search_id:searchId,offset,limit:100,filter,extension,min_bitrate:minBitrate,sort});if(active){setResults(response.results||[]);setResultPage(response);setResultError('');}}
      catch(error:any){if(active)setResultError(error.message);}
      finally{if(active){setResultsLoading(false);timer=setTimeout(tick,2000);}}
    };void tick();return()=>{active=false;clearTimeout(timer);};
  },[searchId,offset,filter,extension,minBitrate,sort,rpc]);
  useEffect(()=>{setOffset(0);setSelected(new Set());},[searchId,filter,extension,minBitrate,sort]);
  useEffect(()=>{setBrowseOffset(0);},[browseFilter]);
  useEffect(()=>{
    if(!browse?.search_id)return;
    const id=browse.search_id;let active=true;setBrowsePageLoading(true);
    const timer=setTimeout(()=>{void rpc('results',{search_id:id,offset:browseOffset,limit:100,filter:browseFilter}).then(value=>{if(active)setBrowse(current=>current?.search_id===id?{...current,...value,error:undefined}:current);}).catch(error=>{if(active)setBrowse(current=>current?.search_id===id?{...current,error:error.message}:current);}).finally(()=>{if(active)setBrowsePageLoading(false);});},150);
    return()=>{active=false;clearTimeout(timer);};
  },[browse?.search_id,browseFilter,browseOffset,rpc]);


  async function toggleConnection(){
    if(!connected&&!snapshot.status.credentials_configured){setTab('settings');setToast({message:'Add your Soulseek account to connect.',type:'success'});return;}
    await run('connection',()=>rpc(connected?'disconnect':'connect'),connected?'Disconnected. Your saved queue is kept.':'You’re connected to Soulseek.');
  }
  async function startSearch(event?:FormEvent,term=query,trackId:string|null=researchIntent?.query===term?researchIntent.trackId:null){
    event?.preventDefault();if(!term.trim())return;
    if(!connected){setToast({message:'Connect your Soulseek account before searching.',type:'error'});return;}
    const result=await run('search',()=>trackId?rpc('discovery_research_search',{track_id:trackId}):rpc('search',{query:term.trim()}));
    if(result){setResearchIntent(null);setSearchId(result.search_id);setQuery(result.query||term.trim());setTab('search');setSelected(new Set());setFilter('');setExtension('');setOffset(0);}
  }
  function chooseSearch(search:SearchRecord){setResearchIntent(null);setSearchId(search.search_id);setQuery(search.query);setSelected(new Set());setOffset(0);setTab('search');}
  async function downloadResults(ids:string[]){
    if(!ids.length)return;
    await run('download',async()=>{
      const failed:string[]=[];let count=0;let firstError='';
      for(const id of ids){try{await rpc('download',{result_id:id,uses:downloadUses});count++;}catch(error:any){failed.push(id);firstError ||= error.message;}}
      setSelected(new Set(failed));
      setToast({message:failed.length?`${count} queued, ${failed.length} not added. ${firstError}`:`${count} ${count===1?'file':'files'} added to downloads.`,type:failed.length?'error':'success'});
      return count;
    });
  }
  async function downloadFolder(row:SearchResult,id=searchId){
    await run('folder',async()=>{const value=await rpc('download_folder',{search_id:id,username:row.username,folder:folder(row.filename),uses:downloadUses});const failures=value.errors?.length||0;setToast({message:failures?`${value.queued_count} files queued; ${failures} could not be added.`:`${value.queued_count} folder files added to downloads.`,type:failures?'error':'success'});return value;});
  }
  async function browseUser(username:string){
    setBrowse({username,loading:true,results:[]});setBrowseFilter('');setBrowseOffset(0);
    try{const response=await rpc('browse_user',{username});setBrowse(current=>current?.username===username?{...response,username,loading:false,results:response.results||[]}:current);}
    catch(error:any){setBrowse(current=>current?.username===username?{...current,loading:false,error:error.message}:current);}
  }
  async function addWish(term:string){const response=await run('wish-add',()=>rpc('wishlist_add',{query:term.trim()}),'Added to your wishlist.');if(response)setWishlistQuery('');}
  function updateSetting(key:keyof Settings,value:any){setSettings(current=>current?{...current,[key]:value}:current);setSettingsDirty(true);}
  async function saveSettings(event?:FormEvent,connectAfter=false){
    event?.preventDefault();if(!settings)return;
    if(password&&!settings.username.trim()){setToast({message:'Enter your username to save your password.',type:'error'});return;}
    if(hasPassword&&settings.username.trim()!==savedUsername.current&&!password){setToast({message:'Enter your password to change accounts.',type:'error'});return;}
    await run('settings',async()=>{
      if(password){await window.soulseek!.saveCredentials({username:settings.username.trim(),password});setHasPassword(true);setPassword('');}
      await rpc('configure',{username:settings.username.trim(),download_dir:settings.download_dir,listen_port:Number(settings.listen_port),obfuscated_port:Number(settings.obfuscated_port),upload_slots:Number(settings.upload_slots),upload_speed_kbps:Number(settings.upload_speed_kbps),download_speed_kbps:Number(settings.download_speed_kbps),notifications:settings.notifications});
      setSettingsDirty(false);await loadSettings();
      if(connectAfter)await rpc('connect');
    },connectAfter?'You’re connected to Soulseek.':'Settings saved.');
  }
  async function addSharedFolder(){await run('share-add',async()=>{const path=await window.soulseek!.chooseDirectory();if(path)await rpc('share_add',{path});});}
  function selectRow(id:string){setSelected(previous=>{const next=new Set(previous);next.has(id)?next.delete(id):next.add(id);return next;});}
  const downloadable=results.filter(row=>!row.locked);
  const allSelected=downloadable.length>0&&downloadable.every(row=>selected.has(row.result_id));

  const fileTable=(rows:SearchResult[],browsing=false)=> <div className="table-scroll"><table className="files-table"><thead><tr>
    {!browsing&&<th className="check-cell"><input type="checkbox" aria-label="Select all visible downloadable results" checked={allSelected} onChange={()=>setSelected(allSelected?new Set():new Set(downloadable.map(row=>row.result_id)))} disabled={!downloadable.length}/></th>}
    <th>File</th><th>Format</th><th>Size</th>{!browsing&&<th>Peer</th>}<th>{browsing?'Length':'Availability'}</th><th className="actions-heading">Actions</th>
    </tr></thead><tbody>{rows.map(row=><tr key={row.result_id} className={selected.has(row.result_id)?'selected':''}>
      {!browsing&&<td className="check-cell"><input type="checkbox" aria-label={`Select ${filename(row.filename)}`} checked={selected.has(row.result_id)} onChange={()=>selectRow(row.result_id)} disabled={row.locked}/></td>}
      <td className="file-cell"><span className={`file-symbol ${row.locked?'locked':''}`}>{row.locked?<LockKeyhole size={16}/>:<Music2 size={17}/>}</span><div><strong title={row.filename}>{filename(row.filename)}</strong><span title={folder(row.filename)}>{folder(row.filename)}</span></div></td>
      <td><span className={`format ${row.extension?.toLowerCase()==='flac'?'lossless':''}`}>{(row.extension||filename(row.filename).split('.').pop()||'FILE').toUpperCase()}</span>{row.attributes?.['0']>0&&<small className="bitrate">{row.attributes['0']} kbps</small>}</td>
      <td className="mono">{formatBytes(row.size_bytes)}</td>
      {!browsing&&<td><button className="peer-link" onClick={()=>void browseUser(row.username)}><UserRound size={13}/>{row.username}<ArrowUpRight size={11}/></button></td>}
      <td>{browsing?<span className="muted mono">{row.attributes?.['1']?duration(row.attributes['1']):'—'}</span>:row.locked?<Badge><LockKeyhole size={10}/>Private</Badge>:row.free_slots?<Badge tone="green"><span className="tiny-dot"/>Available</Badge>:<span className="muted queue-label"><Clock3 size={12}/>{row.queue_size} queued</span>}</td>
      <td><div className="row-actions">{iconButton(<FolderDown size={15}/>,'Download entire folder',()=>void downloadFolder(row,browsing?browse?.search_id:searchId),row.locked||busy.folder||!connected)}{iconButton(<Download size={15}/>,'Download file',()=>void downloadResults([row.result_id]),row.locked||busy.download||!connected,'download-action')}</div></td>
    </tr>)}</tbody></table></div>;

  return <div className="app-shell">
    <div className="workspace">
      <header className="titlebar"><button className="app-wordmark" onClick={()=>setTab('discover')} aria-label="Taste home"><span className="taste-wordmark">taste<span className="taste-period">.</span></span></button><div className="titlebar-middle">{titles[tab]}</div><div className="titlebar-actions"><button className="keyboard-shortcut" onClick={()=>{setTab('search');setTimeout(()=>searchInput.current?.focus(),20);}} aria-label="Focus search"><Search size={13}/><kbd>⌘ K</kbd></button><button className={`connection-button ${connected?'connected':''}`} onClick={()=>void toggleConnection()} disabled={busy.connection||!ready}>{busy.connection?<Loader2 size={12} className="spin"/>:<span className={`connection-dot ${connected?'online':''}`}/>}<span>{busy.connection?(connected?'Disconnecting…':'Connecting…'):connected?'Connected':'Connect account'}</span><Power size={12}/></button></div></header>
      <nav className="main-navigation" aria-label="Main navigation">{nav.map(item=><button key={item.id} className={`nav-item ${tab===item.id?'active':''}`} onClick={()=>setTab(item.id)}><item.icon size={15} strokeWidth={1.7}/><span>{item.title}</span>{item.id==='downloads'&&activeDownloads.length>0&&<span className="nav-count">{activeDownloads.length}</span>}{item.id==='wishlist'&&snapshot.wishlist.length>0&&<span className="nav-count">{snapshot.wishlist.length}</span>}</button>)}<span className="navigation-account">{connected?(snapshot.status.username||settings?.username||'Online'):'Offline'}<span className={`connection-dot ${connected?'online':''}`}/></span></nav>
      {backendError&&<div className="backend-error"><Info size={15}/><span>{backendError}</span><button onClick={()=>void refresh()}>Retry</button></div>}
      <main className={`main-content ${tab==='search'?'search-page':''}`}>
      {tab==='discover'&&ready&&<Discovery rpc={rpc} onSearch={(term,trackId)=>{setResearchIntent(trackId?{query:term,trackId}:null);setQuery(term);setTab('search');if(connected)void startSearch(undefined,term,trackId||null);else {setSearchId('');setToast({message:'Connect Soulseek to search. Your query is ready.',type:'success'});}}}/>}
      {tab==='search'&&<>
        <div className="page-heading"><div><h1>Search</h1><p>Find files across the Soulseek network.</p></div><span className="page-reference">GLOBAL SEARCH</span></div>
        <form className="search-bar" onSubmit={event=>void startSearch(event)}><Search size={21}/><input ref={searchInput} aria-label="Search the Soulseek network" value={query} onChange={event=>{setQuery(event.target.value);setResearchIntent(null);}} placeholder="Artist, album, track, or filename" maxLength={256}/>{query&&iconButton(<X size={15}/>,'Clear search',()=>{setQuery('');setResearchIntent(null);searchInput.current?.focus();})}<button className="primary search-submit" disabled={!query.trim()||busy.search||!connected}>{busy.search?<Loader2 className="spin" size={16}/>:<ArrowRight size={17}/>}<span>Search</span></button></form>
        {searchId?<>
          <div className="search-tabs">{[...snapshot.searches].map(item=><button key={item.search_id} className={item.search_id===searchId?'active':''} onClick={()=>chooseSearch(item)}>{item.collecting?<span className="tiny-dot pulse"/>:<Search size={12}/>}<span>{item.query}</span><small>{item.total_retained}</small></button>)}</div>
          <section className="results-card"><div className="results-toolbar"><div className="result-heading"><h2>{resultPage?.query||query}</h2><Badge>{resultPage?.total_retained??searchRecord?.total_retained??0} results</Badge>{(resultPage?.collecting||searchRecord?.collecting)&&<span className="collecting"><span className="tiny-dot pulse"/>Searching</span>}</div><div className="toolbar-right">{(resultPage?.collecting||searchRecord?.collecting)&&<button className="text-button" onClick={()=>void run('stop',()=>rpc('stop_search',{search_id:searchId}))} disabled={busy.stop}>Stop search</button>}<button className="secondary compact" onClick={()=>void addWish(resultPage?.query||query)} disabled={busy['wish-add']}><Heart size={14}/>Save to wishlist</button></div></div>
          {resultPage?.research_track_id&&<div className="research-search-banner"><div><strong>Researching a collected track version</strong><p>Record all retained results as an availability sample after this search finishes. Filters below don’t change the sample. Filename matches are unverified.</p></div><button className="secondary" disabled={busy['research-capture']||resultPage.collecting} onClick={()=>void run('research-capture',()=>rpc('discovery_research_capture',{search_id:searchId}),'Availability sample saved in the track’s research history.')}>Record availability sample</button></div>}
          <div className="filters"><select aria-label="Search results view" value={resultView} onChange={e=>setResultView(e.target.value)}><option value="files">Files</option><option value="folders">Folders</option></select><div className="filter-input"><ListFilter size={14}/><input aria-label="Filter search results" placeholder="Filter these results…" value={filter} onChange={e=>setFilter(e.target.value)}/></div><select aria-label="File format filter" value={extension} onChange={e=>setExtension(e.target.value)}><option value="">All formats</option><option value="flac">FLAC</option><option value="mp3">MP3</option><option value="wav">WAV</option><option value="aiff">AIFF</option><option value="m4a">M4A</option><option value="ogg">OGG</option></select><select aria-label="Minimum bitrate" value={minBitrate} onChange={e=>setMinBitrate(Number(e.target.value))}><option value="0">Any bitrate</option><option value="192">192 kbps +</option><option value="256">256 kbps +</option><option value="320">320 kbps +</option></select><select aria-label="Sort results" value={sort} onChange={e=>setSort(e.target.value)}><option value="filename">File name</option><option value="size">File size</option><option value="username">Peer</option><option value="speed">Peer speed</option></select><div className="download-uses" role="group" aria-label="Mark downloads for"><span>For</span>{uses.map(([id,label])=><button key={id} type="button" className={downloadUses.includes(id)?'active':''} aria-pressed={downloadUses.includes(id)} onClick={()=>setDownloadUses(current=>current.includes(id)?current.filter(u=>u!==id):[...current,id])}>{label}</button>)}</div>{selected.size>0&&<button className="primary compact selection-download" onClick={()=>void downloadResults([...selected])} disabled={busy.download||!connected}>{busy.download?<Loader2 className="spin" size={14}/>:<Download size={14}/>}Download {selected.size}</button>}</div>
          {resultError?<Empty icon={<Info size={25}/>} title="These results are no longer available" description={resultError} action={<button className="secondary" onClick={()=>void startSearch(undefined,query)} disabled={!connected||busy.search}><RefreshCw size={14}/>Search again</button>}/>:results.length?(resultView==='folders'?<div className="search-folder-list"><p>Folders in this results page · matching files may be only part of an album.</p>{groupSearchFolders(results).map(group=><details key={group.key} className="search-folder"><summary><Folder size={18}/><span><strong>{filename(group.path)}</strong><small>{group.username} · {group.rows.length} matching files · {group.path}</small></span></summary><div className="search-folder-actions"><button className="secondary" onClick={()=>void browseUser(group.username)}>Browse peer’s collection</button><button className="secondary" disabled={group.rows.every(r=>r.locked)||busy.folder||!connected} onClick={()=>void downloadFolder(group.rows.find(r=>!r.locked)!,searchId)}>Download entire folder</button></div>{fileTable(group.rows)}</details>)}</div>:fileTable(results)):<Empty icon={resultsLoading||resultPage?.collecting?<Radio size={26}/>:<Search size={26}/>} title={resultsLoading||resultPage?.collecting?'Listening for results…':'No matching files yet'} description={filter||extension||minBitrate?'Try widening your filters or searching another phrase.':'Peers reply at different speeds. Save this search to your wishlist to check again later.'}/>}
          <div className="table-footer"><span>{resultPage?.truncated?'Result limit reached · narrow your query':selected.size?`${selected.size} selected`:'Choose a file to start a download'}</span><div>{resultPage?.total_retained>0&&<span>{offset+1}–{offset+results.length}</span>}{iconButton(<ChevronLeft size={15}/>,'Previous page',()=>setOffset(Math.max(0,offset-100)),offset===0)}{iconButton(<ChevronRight size={15}/>,'Next page',()=>setOffset(resultPage.next_offset),resultPage?.next_offset==null)}</div></div></section>
        </>:<>
          {snapshot.history.length>0&&<section className="history-strip"><span>History</span>{snapshot.history.slice(0,6).map((item:any,index:number)=><button key={`${item.query||item}-${index}`} onClick={()=>void startSearch(undefined,typeof item==='string'?item:item.query)} disabled={!connected}>{typeof item==='string'?item:item.query}</button>)}</section>}
          <section className="results-card catalogue-empty"><div className="results-toolbar"><div className="result-heading"><h2>Search results</h2><span className="result-count">0 files</span></div><button className="secondary compact" disabled><Download size={13}/>Download selected</button></div>
            <div className="filters"><div className="filter-input"><ListFilter size={14}/><input aria-label="Filter search results" placeholder="Filter results" disabled/></div><select aria-label="File format filter" disabled><option>All formats</option></select><select aria-label="Minimum bitrate" disabled><option>Any bitrate</option></select><span className="toolbar-note">Results appear here as peers respond</span></div>
            {fileTable([])}
            <div className="table-placeholder"><Search size={23} strokeWidth={1.3}/><h3>No search selected</h3><p>{connected?'Enter a query above to search the network.':'Connect your account to start searching.'}</p>{!connected&&<button className="secondary compact" onClick={()=>void toggleConnection()} disabled={busy.connection||!ready}>Connect account</button>}</div>
            <div className="table-footer"><span>0 files selected</span><span>Choose files or folders to download</span></div>
          </section>
        </>}
      </>}
      {tab==='downloads'&&<>
        <div className="page-heading"><div><h1>Downloads</h1><p>Transfer queue and completed files.</p></div><button className="secondary" onClick={()=>void run('reveal-downloads',async()=>{const path=snapshot.status.download_directory||settings?.download_dir;if(path)await window.soulseek!.revealFile(path);})}><FolderOpen size={15}/>Open downloads</button></div>
        <div className="stats-row"><div><span className="stat-label"><ArrowDown size={14}/>DOWNLOADING</span><strong>{activeDownloads.length}<small>files</small></strong></div><div><span className="stat-label"><Radio size={14}/>CURRENT SPEED</span><strong>{formatBytes(speed)}<small>/s</small></strong></div><div><span className="stat-label"><CheckCircle2 size={14}/>COMPLETED</span><strong>{completed.length}<small>files</small></strong></div><div><span className="stat-label"><HardDrive size={14}/>RECEIVED</span><strong>{formatBytes(snapshot.transfers.reduce((sum,t)=>sum+(t.bytes_transferred||0),0))}</strong></div></div>
        <section className="results-card"><div className="results-toolbar"><div className="segmented">{[['all','All downloads'],['active','In progress'],['complete','Completed']].map(([value,label])=><button key={value} className={downloadFilter===value?'active':''} onClick={()=>setDownloadFilter(value)}>{label}</button>)}</div><Badge>{visibleTransfers.length} files</Badge></div>
        {visibleTransfers.length?<div className="transfer-list">{visibleTransfers.map(item=>{
          const percent=item.size_bytes?Math.min(100,item.bytes_transferred/item.size_bytes*100):0;const paused=item.state==='PAUSED';const done=item.state==='COMPLETE';const failed=['FAILED','ABORTED','INCOMPLETE','INTERRUPTED'].includes(item.state);
          return <div className="transfer-row" key={item.transfer_id}><div className={`transfer-art ${done?'done':''}`}>{done?<Check size={21}/>:<Music2 size={22} strokeWidth={1.4}/>}</div><div className="transfer-main"><div className="transfer-title"><strong title={item.filename}>{filename(item.filename)}</strong><Badge tone={done?'green':failed?'red':paused?'amber':'muted'}>{item.state.toLowerCase().replaceAll('_',' ')}</Badge></div><span className="transfer-peer"><UserRound size={11}/>{item.username}<span>·</span>{formatBytes(item.bytes_transferred)} / {formatBytes(item.size_bytes)}{item.queue_position!=null&&item.queue_position>0&&<><span>·</span>Queue position {item.queue_position}</>}</span><div className={`progress-track ${paused?'paused':''}`}><span style={{width:`${percent}%`}}/></div></div><div className="transfer-speed">{done?<span className="green-text">Complete</span>:<><strong>{paused||failed?'—':`${formatBytes(item.speed_bytes_per_second)}/s`}</strong><span>{percent.toFixed(0)}%</span></>}</div><div className="row-actions">{item.state==='ABORTED'?null:done?iconButton(<FolderOpen size={16}/>,'Show in Finder',()=>void run(`reveal-${item.transfer_id}`,()=>window.soulseek!.revealFile(item.local_path))):failed?iconButton(<RefreshCw size={16}/>,'Retry download',()=>void run(item.transfer_id,()=>rpc('retry_transfer',{transfer_id:item.transfer_id})),!connected||busy[item.transfer_id]):iconButton(paused?<Play size={16}/>:<Pause size={16}/>,paused?'Resume download':'Pause download',()=>void run(item.transfer_id,()=>rpc(paused?'resume_transfer':'pause_transfer',{transfer_id:item.transfer_id})),!connected||busy[item.transfer_id])}{iconButton(<X size={16}/>,'Remove from queue, keep the file',()=>void run(item.transfer_id,()=>rpc('remove_transfer',{transfer_id:item.transfer_id})),busy[item.transfer_id])}</div></div>;
        })}</div>:<Empty icon={<ArrowDownToLine size={29}/>} title={downloadFilter==='complete'?'No completed downloads':'The download queue is empty'} description={downloadFilter==='complete'?'Completed files will be listed here.':'Select files from search results to add them to the queue.'} action={<button className="secondary" onClick={()=>setTab('search')}>Go to search<ArrowRight size={14}/></button>}/>}</section>
        <div className="quiet-note"><Info size={13}/>Queue saved locally. Reconnect to resume interrupted transfers.</div>
      </>}
      {tab==='shares'&&<>
        <div className="page-heading"><div><h1>Shared files</h1><p>Folders available to other Soulseek users.</p></div><button className="primary" onClick={()=>void addSharedFolder()} disabled={busy['share-add']||!ready}>{busy['share-add']?<Loader2 className="spin" size={15}/>:<Plus size={17}/>}Add a folder</button></div>
        <div className="sharing-banner"><Info size={14}/><p>Only the folders listed below are shared. Removing a folder here does not delete your files.</p><Badge tone={connected?'green':'muted'}>{connected?'Online':'Offline'}</Badge></div>
        <section className="results-card"><div className="results-toolbar"><div className="result-heading"><h2>Shared folders</h2><Badge>{snapshot.shares.length}</Badge></div><button className="secondary compact" onClick={()=>void run('rescan',()=>rpc('shares_rescan'))} disabled={busy.rescan||!snapshot.shares.length||snapshot.shares.some(item=>item.scanning)}><RefreshCw size={13} className={busy.rescan||snapshot.shares.some(item=>item.scanning)?'spin':''}/>Rescan files</button></div>{snapshot.shares.length?<div className="shared-list">{snapshot.shares.map(item=><div className="shared-row" key={item.path}><div className="shared-folder-icon"><Folder size={24} strokeWidth={1.5}/></div><div className="shared-details"><strong>{item.name||filename(item.path)}</strong><span title={item.path}>{item.path}</span>{item.error&&<span className="red-text">{item.error}</span>}</div><div className="shared-count">{item.scanning?<span className="collecting"><Loader2 className="spin" size={13}/>Indexing…</span>:<><strong>{Number(item.files||0).toLocaleString()} files</strong><span>{formatBytes(item.size_bytes)}</span></>}</div>{iconButton(<ExternalLink size={15}/>,'Show folder in Finder',()=>void run('show-share',()=>window.soulseek!.revealFile(item.path)))}{iconButton(<Trash2 size={15}/>,'Stop sharing this folder',()=>void run(item.path,()=>rpc('share_remove',{path:item.path}),'Folder is no longer shared.'),busy[item.path])}</div>)}</div>:<Empty icon={<FolderOpen size={31}/>} title="No shared folders" description="Choose a folder to make its files available on the network." action={<button className="secondary" onClick={()=>void addSharedFolder()} disabled={busy['share-add']}><Plus size={15}/>Choose a folder</button>}/>}</section>
        <section className="results-card uploads-card"><div className="results-toolbar"><div className="result-heading"><h2>Upload activity</h2><Badge>{snapshot.uploads.length}</Badge></div><span className="muted small-text">Outgoing transfers</span></div>{snapshot.uploads.length?<div className="transfer-list">{snapshot.uploads.map((item,index)=><div className="transfer-row" key={item.transfer_id||index}><div className="transfer-art"><Upload size={20}/></div><div className="transfer-main"><div className="transfer-title"><strong>{filename(item.filename)}</strong><Badge>{item.state.toLowerCase()}</Badge></div><span className="transfer-peer">To {item.username} · {formatBytes(item.bytes_transferred)} / {formatBytes(item.size_bytes)}</span></div><span className="mono muted">{formatBytes(item.speed_bytes_per_second)}/s</span></div>)}</div>:<div className="compact-empty"><Upload size={18}/><span>{connected?'No active uploads.':'Connect to make your shared collection available.'}</span></div>}</section>
      </>}
      {tab==='wishlist'&&<>
        <div className="page-heading"><div><h1>Wishlist</h1><p>Recurring searches for files you want to find.</p></div></div>
        <form className="wishlist-add" onSubmit={event=>{event.preventDefault();if(wishlistQuery.trim())void addWish(wishlistQuery);}}><Heart size={18}/><input aria-label="New wishlist search" placeholder="Add an artist, album, track, or filename" maxLength={256} value={wishlistQuery} onChange={event=>setWishlistQuery(event.target.value)}/><button className="primary" disabled={!wishlistQuery.trim()||busy['wish-add']}><Plus size={16}/>Add to wishlist</button></form>
        <div className="section-intro"><h2>Saved searches <span>{snapshot.wishlist.length}</span></h2><span><span className={`tiny-dot ${connected?'online':''}`}/>{connected?'Checking while you’re connected':'Checks resume when you connect'}</span></div>
        {snapshot.wishlist.length?<div className="wishlist-list">{snapshot.wishlist.map(item=><div className={`wish-row ${!item.enabled?'disabled':''}`} key={item.id}><div className="wish-icon"><Heart size={20} fill={item.enabled?'currentColor':'none'}/></div><div className="wish-details"><strong>{item.query}</strong><span>{item.last_run?`Last checked ${formatDate(item.last_run)}`:'Waiting for its first search'}{item.last_count>0&&<> · {item.last_count} results</>}</span></div>{item.last_search_id&&snapshot.searches.some(search=>search.search_id===item.last_search_id)&&<button className="text-button" onClick={()=>chooseSearch(snapshot.searches.find(search=>search.search_id===item.last_search_id)!)}>View results<ArrowUpRight size={13}/></button>}{iconButton(<Play size={15}/>,'Search now',()=>void run(item.id,async()=>{const value=await rpc('wishlist_run',{id:item.id});if(value?.search_id){setSearchId(value.search_id);setQuery(item.query);setTab('search');}return value;}),!connected||busy[item.id])}<Toggle checked={item.enabled} onChange={()=>void run(item.id,()=>rpc('wishlist_update',{id:item.id,enabled:!item.enabled}))} label={`${item.enabled?'Pause':'Enable'} wishlist search ${item.query}`} disabled={busy[item.id]}/>{iconButton(<Trash2 size={15}/>,'Remove wishlist search',()=>void run(item.id,()=>rpc('wishlist_remove',{id:item.id})),busy[item.id])}</div>)}</div>:<div className="wishlist-empty"><div className="list-column-headings"><span>Search query</span><span>Last checked</span><span>Matches</span><span>Status</span></div><div className="table-placeholder"><h3>No saved searches</h3><p>Add a query above. Searches run while connected; files are never downloaded automatically.</p></div></div>}
        <div className="quiet-note"><Info size={13}/>Wishlist searches follow the network’s search interval. Leave the app running and connected to keep checking.</div>
      </>}
      {tab==='settings'&&<>
        <div className="page-heading"><div><h1>Settings</h1><p>Account, file locations, and transfer limits.</p></div><Badge tone={connected?'green':'muted'}><span className="tiny-dot"/>{connected?'Connected':'Offline'}</Badge></div>
        {!settings?<Empty icon={<Loader2 size={25} className="spin"/>} title="Loading your settings" description="Connecting to the local client…"/>:<form className="settings-form" onSubmit={event=>void saveSettings(event)}>
          {connected&&<div className="inline-notice"><Info size={15}/><span>Disconnect to edit your account and connection settings.</span><button type="button" className="text-button" onClick={()=>void toggleConnection()} disabled={busy.connection}>Disconnect</button></div>}
          <section className="settings-section"><div className="settings-section-title"><div className="section-icon"><UserRound size={19}/></div><div><h2>Soulseek account</h2><p>Choose an unused username and your own password, or use your existing Soulseek account.</p></div></div><div className="form-grid"><label>Username<input value={settings.username||''} autoComplete="username" placeholder="Your username" maxLength={256} onChange={event=>updateSetting('username',event.target.value)} disabled={connected}/></label><label>Password<span className="input-wrap"><input type="password" autoComplete="current-password" value={password} placeholder={hasPassword?'Saved securely · leave blank to keep':'Your password'} onChange={event=>{setPassword(event.target.value);setSettingsDirty(true);}} disabled={connected}/><LockKeyhole size={14}/></span></label></div><div className="setting-helper"><ShieldCheck size={13}/>Your password is encrypted on this Mac and never sent to MCP.</div><div className="account-connect"><span className="muted small-text">{connected?'Connected to Soulseek.':snapshot.status.credentials_configured&&!settingsDirty?'Account saved. Ready to connect.':'New usernames are created when you connect. No separate signup needed.'}</span><button type="button" className="primary compact" onClick={()=>void (connected||(!settingsDirty&&snapshot.status.credentials_configured)?toggleConnection():saveSettings(undefined,true))} disabled={busy.connection||busy.settings||(!connected&&(!settings.username.trim()||(!password&&(!snapshot.status.credentials_configured||settings.username.trim()!==savedUsername.current))))}>{busy.connection||busy.settings?<Loader2 className="spin" size={14}/>:<Power size={14}/>} {connected?'Disconnect':settingsDirty||!snapshot.status.credentials_configured?'Save and connect':'Connect'}</button></div></section>
          <section className="settings-section"><div className="settings-section-title"><div className="section-icon"><FolderDown size={19}/></div><div><h2>Downloads and uploads</h2><p>File destination and bandwidth settings.</p></div></div><label>Save downloads to<div className="path-input"><input value={settings.download_dir||''} readOnly aria-label="Download directory"/><button type="button" className="secondary compact" disabled={connected} onClick={()=>void run('choose-downloads',async()=>{const path=await window.soulseek!.chooseDirectory();if(path)updateSetting('download_dir',path);})}><FolderOpen size={14}/>Choose folder</button></div></label><div className="form-grid narrow-grid"><label>Download limit <span className="label-note">KB/s · 0 is unlimited</span><input type="number" min="0" max="1000000" value={settings.download_speed_kbps??0} onChange={event=>updateSetting('download_speed_kbps',Number(event.target.value))} disabled={connected}/></label><label>Upload limit <span className="label-note">KB/s · 0 is unlimited</span><input type="number" min="0" max="1000000" value={settings.upload_speed_kbps??0} onChange={event=>updateSetting('upload_speed_kbps',Number(event.target.value))} disabled={connected}/></label><label>Upload slots <span className="label-note">Simultaneous uploads</span><input type="number" min="1" max="100" value={settings.upload_slots??2} onChange={event=>updateSetting('upload_slots',Number(event.target.value))} disabled={connected}/></label></div></section>
          <section className="settings-section"><div className="setting-toggle-row"><div className="settings-section-title"><div className="section-icon"><Bell size={19}/></div><div><h2>Download notifications</h2><p>Show a system notification when a download finishes.</p></div></div><Toggle checked={Boolean(settings.notifications)} onChange={()=>updateSetting('notifications',!settings.notifications)} label="Download completion notifications"/></div></section>
          <section className="settings-section advanced-section"><button type="button" className="advanced-toggle" onClick={()=>setShowAdvanced(!showAdvanced)}><SlidersHorizontal size={17}/><span>Advanced connection settings</span><ChevronRight size={16} className={showAdvanced?'rotate':''}/></button>{showAdvanced&&<><div className="form-grid advanced-fields"><label>Listening port<input type="number" min="1" max="65535" value={settings.listen_port} onChange={event=>updateSetting('listen_port',Number(event.target.value))} disabled={connected}/></label><label>Obfuscated port<input type="number" min="1" max="65535" value={settings.obfuscated_port} onChange={event=>updateSetting('obfuscated_port',Number(event.target.value))} disabled={connected}/></label></div><p className="setting-helper"><Info size={13}/>Use different ports for this app and any other Soulseek client running on your Mac.</p></>}</section>
          <div className="settings-footer"><span>{settingsDirty?'You have unsaved changes.':'All changes saved locally.'}</span><button type="submit" className="primary" disabled={!settingsDirty||busy.settings}>{busy.settings?<Loader2 className="spin" size={15}/>:<Check size={15}/>}Save settings</button></div>
        </form>}
      </>}
      </main>
      <footer className="statusbar"><div><span className={`connection-dot ${connected?'online':''}`}/>{connected?'Connected to Soulseek':ready?'Not connected':'Starting local client…'}{connected&&<><span className="footer-divider"/><ArrowDown size={11}/>{formatBytes(speed)}/s</>}</div><div><span>MCP enabled</span><span className="footer-divider"/><span>Local session</span></div></footer>
    </div>
    {toast&&<div role={toast.type==='error'?'alert':'status'} className={`toast ${toast.type}`}>{toast.type==='success'?<CheckCircle2 size={18}/>:<Info size={18}/>}<span>{toast.message}</span>{iconButton(<X size={14}/>,'Dismiss notification',()=>setToast(null))}</div>}
    {browse&&<div className="modal-backdrop" onMouseDown={event=>{if(event.target===event.currentTarget)setBrowse(null);}}><section className="browse-modal" role="dialog" aria-modal="true" aria-labelledby="browse-title"><header><div className="browse-user-icon"><UserRound size={23}/></div><div><div className="eyebrow">USER FILES</div><h2 id="browse-title">{browse.username}</h2></div>{iconButton(<X size={20}/>,'Close collection',()=>setBrowse(null))}</header>{browse.loading?<Empty icon={<Loader2 className="spin" size={28}/>} title="Opening this collection…" description="Waiting for the peer to share their file list."/>:browse.error?<Empty icon={<Info size={27}/>} title="Couldn’t open this collection" description={browse.error} action={<button className="secondary" onClick={()=>void browseUser(browse.username)}><RefreshCw size={14}/>Try again</button>}/>:<><div className="browse-tools"><div className="filter-input"><Search size={14}/><input aria-label="Filter user collection" placeholder="Filter this collection…" value={browseFilter} onChange={event=>setBrowseFilter(event.target.value)}/></div>{browsePageLoading&&<Loader2 size={14} className="spin"/>}<Badge>{browse.total_filtered??browse.total_retained??browse.results.length} files</Badge></div>{browse.results.length?fileTable(browse.results,true):<Empty icon={<FolderOpen size={26}/>} title="No visible shared files" description="This user may have a private collection or no shared folders."/>}<div className="table-footer"><span>{browse.truncated?'This large collection was capped. Search the network for more specific results.':'Choose a file to add it to your downloads.'}</span><div><span>{browse.results.length?browseOffset+1:0}–{browseOffset+browse.results.length}</span>{iconButton(<ChevronLeft size={15}/>, 'Previous collection page',()=>setBrowseOffset(Math.max(0,browseOffset-100)),browseOffset===0||browsePageLoading)}{iconButton(<ChevronRight size={15}/>, 'Next collection page',()=>setBrowseOffset(browse.next_offset!),browse.next_offset==null||browsePageLoading)}</div></div></>}</section></div>}
  </div>;
}
