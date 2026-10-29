import { useEffect, useState } from 'react';
export default function SoundCloudWatches({rpc,people,onAdded,initialPerson}:{rpc:(method:string,params?:Record<string,unknown>)=>Promise<any>;people:{name:string;person_key:string}[];onAdded:()=>Promise<void>;initialPerson?:string}) {
  const [configured,setConfigured]=useState(false);
  const [setup,setSetup]=useState(false);
  const [clientId,setClientId]=useState('');const [secret,setSecret]=useState('');
  const [url,setUrl]=useState('');const [person,setPerson]=useState(initialPerson||'');
  const [profile,setProfile]=useState<{name:string;url:string}|null>(null);
  const [confirmed,setConfirmed]=useState(false);const [hours,setHours]=useState(24);
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('');
  useEffect(()=>{void rpc('discovery_soundcloud_status').then(s=>setConfigured(s.configured)).catch(e=>setError(e.message));},[rpc]);
  async function act(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await fn();}catch(e:any){setError(e.message||'SoundCloud could not be reached.');}finally{setBusy(false);}}
  return <section className="soundcloud-watch" aria-label="SoundCloud upload watches"><h3>Follow the edits, flips, and rabbit holes.</h3><p>Link a collected artist to their SoundCloud profile. Public uploads arrive for review, including artist-provided Hypeddit and purchase links.</p>
    <div className="watch-actions"><span>{configured?'App credentials saved':'SoundCloud API connection needed'}</span><button className="text-button" onClick={()=>setSetup(!setup)}>{configured?'Update connection':'Set up SoundCloud'}</button>{configured&&<button className="text-button" disabled={busy} onClick={()=>void act(async()=>{await rpc('discovery_soundcloud_test');setNotice('SoundCloud connection verified.');})}>Test connection</button>}</div>
    {setup&&<form className="soundcloud-setup" onSubmit={e=>{e.preventDefault();void act(async()=>{await window.soulseek!.saveSoundCloud({client_id:clientId,client_secret:secret});setConfigured(true);setClientId('');setSecret('');setSetup(false);setNotice('App credentials encrypted and saved locally. Test the connection to verify access.');});}}>
      <p>Use credentials from your registered SoundCloud app. New app registration requires Artist Pro. <button type="button" className="text-button" onClick={()=>void window.soulseek!.openMusicLink('https://developers.soundcloud.com/docs/api/register-app').catch(e=>setError(e.message))}>Official setup guide ↗</button></p>
      <label>Client ID<input aria-label="SoundCloud app client ID" type="password" autoComplete="off" value={clientId} onChange={e=>setClientId(e.target.value)} maxLength={512}/></label>
      <label>Client secret<input aria-label="SoundCloud app client secret" type="password" autoComplete="off" value={secret} onChange={e=>setSecret(e.target.value)} maxLength={512}/></label>
      <button className="primary" disabled={busy||!clientId.trim()||!secret.trim()}>Save encrypted connection</button><p>App secrets stay on this Mac and are sent only to SoundCloud’s official authentication endpoint.</p>
    </form>}
    <form className="watch-search" onSubmit={e=>{e.preventDefault();void act(async()=>{setProfile(await rpc('discovery_soundcloud_profile',{url:url.trim()}));setConfirmed(false);});}}>
      <select aria-label="Taste artist to link to SoundCloud" value={person} onChange={e=>{setPerson(e.target.value);setConfirmed(false);}}><option value="">Choose a collected artist…</option>{people.map(p=><option key={p.person_key} value={p.person_key}>{p.name}</option>)}</select>
      <input aria-label="SoundCloud artist profile URL" placeholder="https://soundcloud.com/artist" value={url} onChange={e=>{setUrl(e.target.value);setProfile(null);setConfirmed(false);}} maxLength={2048}/>
      <button className="primary" disabled={busy||!configured||!person||!url.trim()}>Read profile</button>
    </form>
    {profile&&<div className="watch-profile-results"><strong>{profile.name}</strong><button className="text-button" onClick={()=>void window.soulseek!.openMusicLink(profile.url).catch(e=>setError(e.message))}>View SoundCloud profile ↗</button>
      <label className="profile-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I confirm this is the SoundCloud profile for {people.find(p=>p.person_key===person)?.name}.</label>
      <div className="watch-actions"><select aria-label="SoundCloud watch frequency" value={hours} onChange={e=>setHours(Number(e.target.value))}><option value={24}>Daily</option><option value={72}>Every 3 days</option><option value={168}>Weekly</option></select><button className="primary" disabled={busy||!confirmed} onClick={()=>void act(async()=>{const r=await rpc('discovery_soundcloud_watch_add',{url:profile.url,person_key:person,identity_confirmed:confirmed,interval_hours:hours});await onAdded();if(!r.existing)await rpc('discovery_watch_check',{watch_id:r.id});setNotice(r.existing?'This profile is already watched.':'SoundCloud watch added. The first check records existing uploads; subsequent checks find new entries.');setProfile(null);})}>Watch public uploads</button></div>
    </div>}
    <p className="watch-note">Only public uploads, up to the latest 100; reposts and playlists are excluded. Uploader names are not recording credits. Taste asks you to confirm artist and version before saving a find. You can still add and play individual SoundCloud links without API credentials.</p>
    {error&&<p className="discovery-message error" role="alert">{error}</p>}{notice&&<p className="discovery-message" role="status">{notice}</p>}
  </section>;
}
