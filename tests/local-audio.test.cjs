const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {audioHandler,parseAudioURL,byteRange}=require('../electron/local-audio.cjs');
const url='taste-audio://library/'+'a'.repeat(20)+'/'+'b'.repeat(20);
async function fixture(t){
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'taste-audio-'));
  t.after(()=>fs.rm(dir,{recursive:true,force:true}));
  const file=path.join(await fs.realpath(dir),'test.mp3');
  await fs.writeFile(file,'0123456789');
  const stat=await fs.stat(file,{bigint:true});
  return {path:file,size:10,modified_ns:String(stat.mtimeNs)};
}

test('media handles cannot carry arbitrary paths, credentials or query strings',()=>{
  assert.deepEqual(parseAudioURL(url),{track_id:'a'.repeat(20),file_id:'b'.repeat(20)});
  for(const value of ['file:///etc/passwd',url+'?path=/etc/passwd',url+'#x',url.replace('library','other'),url.replace('library','user@library'),url.replace('library','library:444'),url.replace('a'.repeat(20),'..'),url.replace('b'.repeat(20),'%2fetc')])assert.throws(()=>parseAudioURL(value));
});

test('ranges support seeking and suffix reads while refusing invalid or multipart ranges',()=>{
  assert.equal(byteRange('bytes=-4',0),null);
  assert.deepEqual(byteRange('bytes=3-6',10),{start:3,end:6,partial:true});
  assert.deepEqual(byteRange('bytes=7-',10),{start:7,end:9,partial:true});
  assert.deepEqual(byteRange('bytes=-4',10),{start:6,end:9,partial:true});
  assert.deepEqual(byteRange('bytes=3-100',10),{start:3,end:9,partial:true});
  for(const value of ['bytes=10-','bytes=5-2','bytes=-0','bytes=-','bytes=0-1,4-5','bytes=9007199254740992-','bad'])assert.equal(byteRange(value,10),null);
});

test('full recordings, byte ranges and HEAD responses have accurate media headers',async t=>{
  const record=await fixture(t);
  const serve=audioHandler(async ids=>{assert.equal(ids.track_id,'a'.repeat(20));return record;});
  const full=await serve(new Request(url));
  assert.equal(full.status,200);assert.equal(full.headers.get('content-type'),'audio/mpeg');assert.equal(await full.text(),'0123456789');
  const partial=await serve(new Request(url,{headers:{Range:'bytes=3-6'}}));
  assert.equal(partial.status,206);assert.equal(partial.headers.get('content-range'),'bytes 3-6/10');assert.equal(partial.headers.get('content-length'),'4');assert.equal(await partial.text(),'3456');
  const head=await serve(new Request(url,{method:'HEAD'}));
  assert.equal(head.headers.get('content-length'),'10');assert.equal(await head.text(),'');
  const invalid=await serve(new Request(url,{headers:{Range:'bytes=11-'}}));
  assert.equal(invalid.status,416);assert.equal(invalid.headers.get('content-range'),'bytes */10');
});

test('unknown, moved, modified, or symlinked files cannot be streamed',async t=>{
  const record=await fixture(t);
  assert.equal((await audioHandler(async()=>{throw new Error('private/path');})(new Request(url))).status,404);
  assert.equal((await audioHandler(async()=>record)(new Request(url,{method:'POST'}))).status,405);
  await fs.writeFile(record.path,'changed recording');
  const changed=await audioHandler(async()=>record)(new Request(url));assert.equal(changed.status,404);assert.equal(await changed.text(),'');
  const moved=record.path+'.moved';await fs.rename(record.path,moved);
  assert.equal((await audioHandler(async()=>record)(new Request(url))).status,404);
  await fs.symlink(moved,record.path);
  assert.equal((await audioHandler(async()=>record)(new Request(url))).status,404);
});

test('cancelling a large response releases its stream',async t=>{
  const record=await fixture(t);await fs.writeFile(record.path,Buffer.alloc(1024*1024));
  const stat=await fs.stat(record.path,{bigint:true});record.size=Number(stat.size);record.modified_ns=String(stat.mtimeNs);
  const result=await audioHandler(async()=>record)(new Request(url));
  const reader=result.body.getReader();assert.equal((await reader.read()).done,false);await reader.cancel();
});
