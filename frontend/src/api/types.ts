export interface RemoteSummary {
  name: string;
  type: string;
  is_default: boolean;
  details: Record<string, unknown>;
  health?: {
    status: string;
    latency_ms: number;
    read_ok: boolean;
    write_ok: boolean;
    checked_at: number;
    error?: string | null;
  } | null;
}

export interface RemoteListResponse {
  default_remote: string | null;
  supported_types: string[];
  remotes: RemoteSummary[];
}

export interface QuotaResponse {
  supported: boolean;
  name: string;
  total: number;
  used: number;
  free: number;
  filecount: number;
}

export interface TestRemoteResponse {
  status: 'success' | 'failed';
  name: string;
  read_ok: boolean;
  write_tested: boolean;
  write_ok: boolean;
  delete_capability?: string | null;
  latency_ms: number;
  error?: string | null;
}

export interface FileItemResponse {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  modified_at: string | null;
  thumbnail_url?: string | null;
}

export interface ListDirResponse {
  remote: string;
  path: string;
  total_count: number;
  items: FileItemResponse[];
}

export interface SyncActionDto {
  type: string;
  target: string;
  reason: string;
  bytes: number;
  is_dir: boolean;
}

export interface SyncDiffItem {
  action: 'add' | 'update' | 'delete' | 'identical';
  path: string;
  size: number;
  reason: string;
}

export interface SyncPlanResponse {
  source_uri: string;
  dest_uri: string;
  source?: string;
  destination?: string;
  mode?: string;
  to_add?: number;
  to_update?: number;
  to_delete?: number;
  bytes_to_transfer?: number;
  items?: SyncDiffItem[];
  total_actions: number;
  has_destructive: boolean;
  permanent_delete_count: number;
  trash_delete_count: number;
  actions: SyncActionDto[];
  batches: { name: string; count: number }[];
  capabilities: {
    source_deletion: string;
    dest_deletion: string;
  };
}

export interface TaskRecord {
  id: string;
  task_id?: string;
  kind: 'sync' | 'transfer' | 'renew';
  title: string;
  source_uri?: string | null;
  dest_uri?: string | null;
  source?: string;
  destination?: string;
  status: 'running' | 'pausing' | 'paused' | 'completed' | 'failed' | 'cancelled' | 'queued';
  created_at: number;
  finished_at?: number | null;
  ended_at?: number | null;
  bytes_done: number;
  bytes_total: number;
  bytes_transferred?: number;
  files_done: number;
  files_total: number;
  files_transferred?: number;
  errors: number;
  speed_bps: number;
  eta_seconds?: number | null;
  message: string;
  logs?: string[];
  request_payload?: Record<string, unknown> | null;
}

export interface TaskItemResponse {
  name: string;
  schedule: string;
  cron?: string;
  command: string;
  enabled: boolean;
  last_run: string | null;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_exit_code: number | null;
  next_run?: string | null;
}

export interface DaemonStatusResponse {
  installed: boolean;
  running: boolean;
  status?: 'running' | 'stopped';
  pid: number | null;
  backend: string;
  log_path: string;
  log_tail: string[];
  logs?: string[];
}

export interface CacheStatsResponse {
  enabled: boolean;
  ttl_seconds: number;
  max_entries: number;
  current_entries: number;
  total_entries?: number;
  hits: number;
  misses: number;
  ratio: number;
  hit_ratio?: number;
  remotes_cached: string[];
  persisted_dirs?: number;
  persisted_thumbs?: number;
}

export interface WebSettings {
  cache: {
    enabled: boolean;
    ttl_seconds: number;
    max_entries: number;
    persist_to_disk: boolean;
    cache_dir?: string | null;
  };
  ui: {
    site_title: string;
    default_view_mode: string;
    default_display_layout: string;
    enable_preview: boolean;
  };
  security: {
    max_upload_size_mb: number;
    allow_guest_download: boolean;
  };
  transfer: {
    max_workers: number;
    bandwidth_limit_kbps: number;
    log_level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
  };
  extra_options: Record<string, unknown>;
}

export interface SettingsResponse {
  settings: WebSettings;
  cache_stats: CacheStatsResponse;
}

export interface UpstashConfigResponse {
  rest_url: string | null;
  has_token: boolean;
  has_passphrase: boolean;
  sync_key: string;
  auto_sync_tokens: boolean;
  auto_push_tokens: boolean;
  renew_leeway_minutes: number;
}

export interface UpstashTokenItem {
  identity: string;
  identity_key: string;
  remotes: string[];
  expires_at?: number | null;
  updated_at?: number | null;
  device_id?: string | null;
  is_locked: boolean;
  locked_by?: string | null;
}

export interface ActivityEvent {
  id: string;
  type: 'task.update' | 'task.log' | 'log' | 'system' | 'heartbeat' | 'hello' | 'resync';
  level?: string;
  message: string;
  data?: unknown;
  timestamp: number;
}

export type RemoteItem = RemoteSummary;
export type FsItem = FileItemResponse & { mime_type?: string };
export type FsListResponse = ListDirResponse;
export type TransferSettings = WebSettings['transfer'];
export type CacheStats = CacheStatsResponse;

