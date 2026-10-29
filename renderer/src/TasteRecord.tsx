/** A little record-store character, drawn in SVG so it stays crisp at any size. */
export default function TasteRecord({playing=false}:{playing?:boolean}) {
  return <svg className={`taste-record ${playing?'is-playing':''}`} viewBox="0 0 220 220" fill="none" aria-hidden="true">
    <circle cx="110" cy="110" r="99" fill="currentColor"/>
    <g stroke="#FFF6DE" strokeOpacity=".24" strokeWidth="1.3">
      {[89,81,73,65].map(r=><circle key={r} cx="110" cy="110" r={r}/>)}
    </g>
    <path d="M36 87a79 79 0 0 1 45-49M139 182a79 79 0 0 0 45-49" stroke="#FFF6DE" strokeWidth="6" strokeLinecap="round" opacity=".28"/>
    <circle cx="110" cy="110" r="49" fill="#EEC6AC"/>
    <circle cx="110" cy="110" r="42" fill="#F8DF83"/>
    <path d="M92 104v8m36-8v8" stroke="#362C24" strokeWidth="6" strokeLinecap="round"/>
    <path d="M93 123c9 12 25 12 34 0" stroke="#362C24" strokeWidth="4" strokeLinecap="round"/>
    <circle cx="110" cy="89" r="3" fill="#B8323B"/>
  </svg>;
}
