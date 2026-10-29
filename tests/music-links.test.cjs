const { test } = require('node:test');
const assert = require('node:assert/strict');
const { musicLink } = require('../electron/music-links.cjs');
test('music destinations accept supported HTTPS pages only', () => {
  assert.equal(musicLink('https://www.beatport.com/track/test/123'), 'https://www.beatport.com/track/test/123');
  assert.equal(musicLink('https://artist.bandcamp.com/track/test'), 'https://artist.bandcamp.com/track/test');
  for (const value of ['file:///tmp/test', 'javascript:alert(1)', 'https://beatport.com.evil.test/a', 'https://user:pass@beatport.com/a', 'https://127.0.0.1/a', 'https://beatport.com:8080/a']) {
    assert.throws(() => musicLink(value));
  }
});
