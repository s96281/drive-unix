import type {
  CacheStatsResponse,
  DaemonStatusResponse,
  FileItemResponse,
  RemoteSummary,
  TaskItemResponse,
  TaskRecord,
  UpstashConfigResponse,
  UpstashTokenItem,
  WebSettings,
} from '../types';

export interface MockFsItem {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  modified_at: string;
  thumbnail_url?: string;
  content?: string;
}

export interface MockDatabase {
  remotes: Record<string, RemoteSummary>;
  quotas: Record<string, { total: number; used: number; filecount: number; supported: boolean }>;
  files: Record<string, MockFsItem[]>; // remoteName -> items
  tasks: TaskRecord[];
  schedules: Record<string, TaskItemResponse>;
  daemon: DaemonStatusResponse;
  settings: WebSettings;
  cacheStats: CacheStatsResponse;
  upstashConfig: UpstashConfigResponse;
  upstashTokens: UpstashTokenItem[];
}
