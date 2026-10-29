const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs/promises');const os=require('node:os');const path=require('node:path');
const {saveYouTube,readYouTube,validate}=require('../electron/youtube-credentials.cjs');
test('YouTube keys are encrypted, private, and restored only in main',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'taste-yt-'));let plain;
  const storage={isAsyncEncryptionAvailable:async()=>true,encryptStringAsync:async(v)=>{plain=v;return Buffer.from('encrypted');},decryptStringAsync:async()=>({result:plain})};
  try{await saveYouTube(storage,dir,'fixture-key-only');const file=path.join(dir,'youtube.enc');assert(!(await fs.readFile(file,'utf8')).includes('fixture-key'));assert.deepEqual(await readYouTube(storage,dir),{api_key:'fixture-key-only'});assert.equal((await fs.stat(file)).mode&0o777,0o600);assert.throws(()=>validate(''));}
  finally{await fs.rm(dir,{recursive:true,force:true});}
});
