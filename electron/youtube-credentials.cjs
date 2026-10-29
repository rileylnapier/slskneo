const path = require('node:path');
const fs = require('node:fs/promises');
const { decryptCredential } = require('./credentials.cjs');
function validate(api_key) {
  if (typeof api_key !== 'string' || api_key.trim().length < 10 || api_key.length > 512) throw new Error('Enter a YouTube Data API key.');
  return {api_key:api_key.trim()};
}
async function saveYouTube(safeStorage,directory,key) {
  const values=validate(key);
  if (!(await safeStorage.isAsyncEncryptionAvailable())) throw new Error('Unlock your keychain to save the connection.');
  const encrypted=await safeStorage.encryptStringAsync(JSON.stringify(values));
  await fs.mkdir(directory,{recursive:true,mode:0o700});
  const file=path.join(directory,'youtube.enc');
  await fs.writeFile(file+'.tmp',JSON.stringify({secret:encrypted.toString('base64')}),{mode:0o600});
  await fs.chmod(file+'.tmp',0o600);
  await fs.rename(file+'.tmp',file);
  return values;
}
async function readYouTube(safeStorage,directory) {
  let record;
  try {record=JSON.parse(await fs.readFile(path.join(directory,'youtube.enc'),'utf8'));}
  catch(e){if(e.code==='ENOENT')return null;throw new Error('YouTube connection could not be restored.');}
  return validate(JSON.parse(await decryptCredential(safeStorage,record)).api_key);
}
module.exports={saveYouTube,readYouTube,validate};
