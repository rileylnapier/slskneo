const fs = require('node:fs/promises');
const { constants } = require('node:fs');
const path = require('node:path');
const { Readable } = require('node:stream');

const types = { '.mp3':'audio/mpeg', '.flac':'audio/flac', '.wav':'audio/wav', '.m4a':'audio/mp4',
  '.ogg':'audio/ogg', '.opus':'audio/ogg', '.aif':'audio/aiff', '.aiff':'audio/aiff' };

function parseAudioURL(value) {
  const url = new URL(value);
  if (url.protocol !== 'taste-audio:' || url.host !== 'library' || url.username || url.password || url.search || url.hash) throw new Error('Invalid audio URL.');
  const match = /^\/([0-9a-f]{20})\/([0-9a-f]{20})$/.exec(url.pathname);
  if (!match) throw new Error('Invalid audio handle.');
  return { track_id: match[1], file_id: match[2] };
}

function byteRange(value, size) {
  if (!value) return { start:0, end:size-1, partial:false };
  if (size <= 0) return null;
  const match = /^bytes=(\d*)-(\d*)$/.exec(value);
  if (!match || (!match[1] && !match[2])) return null;
  let start, end;
  if (!match[1]) {
    const suffix = Number(match[2]);
    if (!Number.isSafeInteger(suffix) || suffix <= 0) return null;
    start = Math.max(0,size-suffix); end = size-1;
  } else {
    start = Number(match[1]); end = match[2] ? Number(match[2]) : size-1;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= size) return null;
    end = Math.min(end,size-1);
  }
  return { start,end,partial:true };
}

async function openAudioFile(record) {
  const mime = types[path.extname(record.path).toLowerCase()];
  if (!path.isAbsolute(record.path) || !mime) throw new Error('Unsupported library file.');
  // Refuse a file replaced with a symlink after import, including parent links.
  if (await fs.realpath(record.path) !== path.resolve(record.path)) throw new Error('Library file moved.');
  const file = await fs.open(record.path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = await file.stat({bigint:true});
    if (!stat.isFile() || stat.size !== BigInt(record.size) || stat.mtimeNs !== BigInt(record.modified_ns)) throw new Error('Library file changed.');
    return {file,mime,size:Number(stat.size)};
  } catch (error) { await file.close(); throw error; }
}

function audioHandler(resolve) {
  return async request => {
    let opened;
    try {
      if (!['GET','HEAD'].includes(request.method)) return new Response(null,{status:405,headers:{Allow:'GET, HEAD'}});
      const ids = parseAudioURL(request.url);
      const record = await resolve(ids);
      opened = await openAudioFile(record);
      const {file,mime,size} = opened;
      const headers = { 'Content-Type':mime, 'Accept-Ranges':'bytes', 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff' };
      const range = byteRange(request.headers.get('range'),size);
      if (!range) {
        await file.close(); opened=null;
        return new Response(null,{status:416,headers:{...headers,'Content-Range':`bytes */${size}`}});
      }
      headers['Content-Length'] = String(Math.max(0,range.end-range.start+1));
      if (range.partial) headers['Content-Range'] = `bytes ${range.start}-${range.end}/${size}`;
      if (request.method === 'HEAD' || !size) {
        await file.close(); opened=null;
        return new Response(null,{status:range.partial?206:200,headers});
      }
      const stream = file.createReadStream({start:range.start,end:range.end,autoClose:true});
      opened=null; // The stream now owns the file descriptor, including cancellation.
      const abort = () => stream.destroy();
      if (request.signal?.aborted) abort();
      else request.signal?.addEventListener('abort',abort,{once:true});
      stream.once('close',()=>request.signal?.removeEventListener('abort',abort));
      return new Response(Readable.toWeb(stream),{status:range.partial?206:200,headers});
    } catch {
      if (opened) await opened.file.close().catch(()=>{});
      // Never expose paths, filesystem details, or file contents in error pages.
      return new Response(null,{status:404});
    }
  };
}
module.exports = {audioHandler,parseAudioURL,byteRange,openAudioFile};
