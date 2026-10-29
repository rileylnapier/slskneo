const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const os=require('node:os');const path=require('node:path');
const {saveSoundCloud,readSoundCloud,validate}=require('../electron/soundcloud-credentials.cjs');
test('SoundCloud app credentials are written through system encryption and restored only in main',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'taste-sc-'));let plaintext;
  const storage={isAsyncEncryptionAvailable:async()=>true,encryptStringAsync:async(value)=>{plaintext=value;return Buffer.from('encrypted fixture');},decryptStringAsync:async()=>({result:plaintext})};
  try{
    const values={client_id:'fixture-id',client_secret:'fixture-secret'};
    await saveSoundCloud(storage,dir,values);
    const file=await fs.readFile(path.join(dir,'soundcloud.enc'),'utf8');assert(!file.includes(values.client_id));assert(!file.includes(values.client_secret));
    assert.deepEqual(await readSoundCloud(storage,dir),values);
    assert.equal((await fs.stat(path.join(dir,'soundcloud.enc'))).mode&0o777,0o600);
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});
test('empty or oversized connection fields cannot be saved',()=>{
  assert.throws(()=>validate({client_id:'',client_secret:'x'}));assert.throws(()=>validate({client_id:'x',client_secret:'x'.repeat(513)}));
});
