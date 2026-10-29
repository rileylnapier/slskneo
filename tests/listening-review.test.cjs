const test=require('node:test');const assert=require('node:assert/strict');
test('rating a research finding saves its catalog identity before applying only the requested feedback',async()=>{
  const {saveListeningReview}=await import('../renderer/src/listening-review.ts');const calls=[];
  const rpc=async(method,params)=>{calls.push([method,params]);return {track_id:'saved-id'};};
  assert.equal(await saveListeningReview(rpc,{candidateId:'finding'},undefined,{rating:-1}),'saved-id');
  assert.deepEqual(calls,[['discovery_library_research_review',{candidate_id:'finding',decision:'keep'}],['discovery_react',{track_id:'saved-id',rating:-1}]]);
});
test('known tracks and resolved findings reuse their identity; following is independent of ratings',async()=>{
  const {saveListeningReview}=await import('../renderer/src/listening-review.ts');const calls=[];
  const rpc=async(...args)=>{calls.push(args);return {};};
  await saveListeningReview(rpc,{candidateId:'finding'},'existing',undefined,{name:'Remixer',followed:false});
  await saveListeningReview(rpc,{trackId:'owned'},undefined,{favorite:false});
  assert.deepEqual(calls,[['discovery_follow',{name:'Remixer',enabled:true}],['discovery_react',{track_id:'owned',favorite:false}]]);
});
test('failed saves never send feedback against an unresolved identity',async()=>{
  const {saveListeningReview}=await import('../renderer/src/listening-review.ts');let calls=0;
  await assert.rejects(()=>saveListeningReview(async()=>{calls++;throw Error('Offline');},{candidateId:'finding'},undefined,{rating:1}),/Offline/);
  assert.equal(calls,1);
  await assert.rejects(()=>saveListeningReview(async()=>({}),{candidateId:'finding'},undefined,{rating:1}),/could not be saved/);
});
