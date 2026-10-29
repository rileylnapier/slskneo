import type { SearchResult } from './types';

// Keep peers and full paths separate: matching folder names need not be the same album.
export function groupSearchFolders(rows: SearchResult[]) {
  const groups = new Map<string, {key:string; path:string; username:string; rows:SearchResult[]}>();
  for (const row of rows) {
    const normalized = row.filename.replaceAll('/', '\\');
    const path = normalized.includes('\\') ? normalized.slice(0, normalized.lastIndexOf('\\')) : '.';
    const key = JSON.stringify([row.username, path]);
    const group = groups.get(key) || {key, path, username:row.username, rows:[]};
    group.rows.push(row);
    groups.set(key, group);
  }
  return [...groups.values()];
}
