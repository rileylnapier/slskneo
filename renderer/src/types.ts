export type Tab = 'search' | 'downloads' | 'shares' | 'wishlist' | 'settings';
export interface SoulseekBridge {
  rpc(method: string, params?: Record<string, unknown>): Promise<any>;
  chooseDirectory(): Promise<string | null>;
  revealFile(path: string): Promise<void>;
  getCredentials(): Promise<{username: string; hasPassword: boolean}>;
  saveCredentials(credentials: {username: string; password: string}): Promise<void>;
  notify(title: string, body: string): Promise<void>;
  platform: string;
}
declare global { interface Window { soulseek?: SoulseekBridge } }
export interface SearchResult {
  result_id: string; username: string; filename: string; size_bytes: number;
  extension: string; locked: boolean; free_slots: boolean; speed_bytes_per_second: number;
  queue_size: number; attributes: Record<string, number>;
}
export interface SearchRecord {
  search_id: string; query: string; collecting: boolean; total_retained: number; created: number;
}
export interface Transfer {
  transfer_id: string; username: string; filename: string; local_path: string;
  state: string; size_bytes: number; bytes_transferred: number;
  speed_bytes_per_second: number; queue_position: number | null;
}
export interface SharedDirectory {path: string; name: string; files: number; size_bytes: number; scanning: boolean; error?: string}
export interface Wish {id: string; query: string; enabled: boolean; last_run: number | null; last_search_id: string | null; last_count: number}
export interface Snapshot {
  status: {connected: boolean; credentials_configured: boolean; username?: string; download_directory?: string; sharing_enabled?: boolean; [key: string]: any};
  searches: SearchRecord[]; transfers: Transfer[]; uploads: Transfer[];
  wishlist: Wish[]; shares: SharedDirectory[]; history: any[];
}
export interface Settings {
  username: string; credentials_configured: boolean; download_dir: string;
  listen_port: number; obfuscated_port: number; upload_slots: number;
  upload_speed_kbps: number; download_speed_kbps: number; notifications: boolean;
}
