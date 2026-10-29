const test=require('node:test');
const assert=require('node:assert/strict');
const item=(id,url=id)=>({id,url,title:id,artist:'Artist',kind:'preview'});
test('queue preserves filtered order, deduplicates recordings, and has bounded navigation',async()=>{
  const {makeQueue,queueStep}=await import('../renderer/src/listening-queue.ts');
  const q=makeQueue([item('a'),item('b'),item('same recording','a'),item('no preview','')],'b');
  assert.deepEqual(q.items.map(i=>i.id),['a','b']);assert.equal(q.index,1);
  assert.equal(queueStep(q,1),null);assert.equal(queueStep(q,-1),0);
  assert.deepEqual(makeQueue([]),{items:[],index:-1});
});
test('enqueue and remove never change the active recording or mutate the original queue',async()=>{
  const {makeQueue,appendQueue,removeQueued}=await import('../renderer/src/listening-queue.ts');
  const q=makeQueue([item('a'),item('b'),item('c')],'b');
  const appended=appendQueue(q,[item('c'),item('d')]);
  assert.equal(appended.items[appended.index].id,'b');assert.equal(appended.items.length,4);assert.equal(q.items.length,3);
  const removed=removeQueued(appended,0);assert.equal(removed.index,0);assert.equal(removed.items[removed.index].id,'b');
  assert.equal(removeQueued(removed,0),removed);assert.equal(removeQueued(removed,99),removed);
  assert.deepEqual(removeQueued(removed,2).items.map(i=>i.id),['b','c']);
});
test('local recordings take priority, previews are a fallback, and unplayable tracks are omitted',async()=>{
  const {trackPlayable}=await import('../renderer/src/listening-queue.ts');
  const t={id:'owned',title:'Song',artist:'Artist',preview_url:'https://preview',local_audio:[{url:'taste-audio://library/track/file',format:'FLAC'}],reasons:['An artist you follow']};
  assert.equal(trackPlayable(t).kind,'local');assert.equal(trackPlayable(t).format,'FLAC');assert.equal(trackPlayable(t).trackId,'owned');
  assert.equal(trackPlayable({...t,local_audio:[]}).kind,'preview');
  assert.equal(trackPlayable({...t,local_audio:[],preview_url:''}),null);
  assert.deepEqual(trackPlayable(t).reasons,t.reasons);
});
test('SoundCloud uses the official player and yields to owned files and Beatport previews',async()=>{
  const {trackPlayable}=await import('../renderer/src/listening-queue.ts');
  const track={id:'sc',artist:'Artist',title:'Edit',soundcloud_url:'https://soundcloud.com/artist/edit'};
  assert.equal(trackPlayable(track).kind,'soundcloud');
  assert.equal(trackPlayable({...track,preview_url:'https://geo-samples.beatport.com/preview.mp3'}).kind,'preview');
  assert.equal(trackPlayable({...track,local_audio:[{url:'taste-audio://library/id/file',format:'MP3'}]}).kind,'local');
});
