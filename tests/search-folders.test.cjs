const test = require('node:test');
const assert = require('node:assert/strict');

test('album exploration keeps different peers and same-named albums in different paths separate', async () => {
  const { groupSearchFolders } = await import('../renderer/src/search-folders.ts');
  const rows = [
    {result_id:'1', username:'alice', filename:'Music/1975/Album/01.flac'},
    {result_id:'2', username:'alice', filename:'Music\\1975\\Album\\02.flac', locked:true},
    {result_id:'3', username:'bob', filename:'Music/1975/Album/01.flac'},
    {result_id:'4', username:'alice', filename:'Other/Album/01.flac'},
    {result_id:'5', username:'alice', filename:'loose.mp3'},
  ];
  const groups = groupSearchFolders(rows);
  assert.equal(groups.length, 4);
  assert.deepEqual(groups[0].rows.map(r=>r.result_id), ['1','2']);
  assert.equal(groups[0].rows[1].locked, true);
  assert.equal(new Set(groups.map(g=>g.key)).size, 4);
  assert.equal(groups[3].path, '.');
  assert.equal(groups.flatMap(g=>g.rows).length, rows.length);
  assert.deepEqual(groupSearchFolders([]), []);
});
