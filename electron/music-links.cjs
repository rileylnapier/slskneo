const domains = ['beatport.com', 'hypeddit.com', 'livedjservice.com', 'youtube.com', 'youtu.be', 'bandcamp.com', 'soundcloud.com', '1001tracklists.com'];
function musicLink(value) {
  if (typeof value !== 'string' || value.length > 4096) throw new Error('Invalid music link.');
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.port ||
      !domains.some(domain => url.hostname === domain || url.hostname.endsWith('.' + domain))) {
    throw new Error('Only HTTPS links to supported music sources can be opened.');
  }
  return url.href;
}
module.exports = { musicLink };
