const path = require('node:path');
const fs = require('node:fs/promises');
const { decryptCredential } = require('./credentials.cjs');
function validate(values) {
  if (!values || !['client_id','client_secret'].every(key => typeof values[key] === 'string' && values[key].trim().length > 0 && values[key].length <= 512)) throw new Error('Enter both SoundCloud app credentials.');
  return {client_id:values.client_id.trim(),client_secret:values.client_secret.trim()};
}
async function saveSoundCloud(safeStorage, directory, values) {
  const credentials=validate(values);
  if (!(await safeStorage.isAsyncEncryptionAvailable())) throw new Error('Unlock your keychain to save the connection.');
  const encrypted=await safeStorage.encryptStringAsync(JSON.stringify(credentials));
  await fs.mkdir(directory,{recursive:true,mode:0o700});
  const file=path.join(directory,'soundcloud.enc');
  await fs.writeFile(file+'.tmp',JSON.stringify({secret:encrypted.toString('base64')}),{mode:0o600});
  await fs.chmod(file+'.tmp',0o600);
  await fs.rename(file+'.tmp',file);
  return credentials;
}
async function readSoundCloud(safeStorage,directory) {
  let record;
  try {record=JSON.parse(await fs.readFile(path.join(directory,'soundcloud.enc'),'utf8'));}
  catch(e){if(e.code==='ENOENT')return null;throw new Error('SoundCloud connection could not be restored.');}
  return validate(JSON.parse(await decryptCredential(safeStorage,record)));
}
module.exports={saveSoundCloud,readSoundCloud,validate};
