import type { MockDatabase, MockFsItem } from './db';

const photoSvg1 = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" viewBox="0 0 300 200"><rect width="300" height="200" fill="%231e293b"/><circle cx="150" cy="100" r="50" fill="%2338bdf8"/><text x="150" y="180" font-size="14" fill="%2394a3b8" text-anchor="middle">Demo Photo 1</text></svg>`;
const photoSvg2 = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" viewBox="0 0 300 200"><rect width="300" height="200" fill="%230f172a"/><polygon points="150,40 220,160 80,160" fill="%2310b981"/><text x="150" y="185" font-size="14" fill="%2394a3b8" text-anchor="middle">Demo Photo 2</text></svg>`;

export function createInitialMockDatabase(): MockDatabase {
  const gdriveFiles: MockFsItem[] = [
    { name: '工作文件', path: '/工作文件', is_dir: true, size: 0, modified_at: '2026-10-20T08:30:00Z' },
    { name: '備份資料夾', path: '/備份資料夾', is_dir: true, size: 0, modified_at: '2026-10-18T14:15:00Z' },
    { name: '專案架構規劃.pdf', path: '/專案架構規劃.pdf', is_dir: false, size: 4528192, modified_at: '2026-10-21T09:12:00Z' },
    { name: '季度財務報表.xlsx', path: '/工作文件/季度財務報表.xlsx', is_dir: false, size: 842100, modified_at: '2026-10-19T11:00:00Z' },
    { name: '系統規格書_v2.md', path: '/工作文件/系統規格書_v2.md', is_dir: false, size: 48120, modified_at: '2026-10-21T16:45:00Z', content: '# drive-unix 規格說明書\n\n- 支援多雲儲存同步\n- 包含 E2EE 加密保護\n- 自動排程與即時事件推播' },
    { name: '測試截圖.png', path: '/備份資料夾/測試截圖.png', is_dir: false, size: 1240500, modified_at: '2026-10-20T10:05:00Z', thumbnail_url: photoSvg1 },
  ];

  const localFiles: MockFsItem[] = [
    { name: 'data', path: '/data', is_dir: true, size: 0, modified_at: '2026-10-21T10:00:00Z' },
    { name: 'logs', path: '/logs', is_dir: true, size: 0, modified_at: '2026-10-22T02:00:00Z' },
    { name: 'app_config.json', path: '/data/app_config.json', is_dir: false, size: 1240, modified_at: '2026-10-22T08:15:00Z', content: '{\n  "app": "drive-unix",\n  "env": "production"\n}' },
    { name: 'sync.log', path: '/logs/sync.log', is_dir: false, size: 89410, modified_at: '2026-10-22T09:40:00Z', content: '[INFO] Daily sync executed smoothly at 02:00' },
  ];

  const photosFiles: MockFsItem[] = [
    { name: '2026家庭相簿', path: '/2026家庭相簿', is_dir: true, size: 0, modified_at: '2026-10-15T12:00:00Z' },
    { name: 'IMG_20261001.jpg', path: '/2026家庭相簿/IMG_20261001.jpg', is_dir: false, size: 3410000, modified_at: '2026-10-01T15:20:00Z', thumbnail_url: photoSvg1 },
    { name: 'IMG_20261002.jpg', path: '/2026家庭相簿/IMG_20261002.jpg', is_dir: false, size: 4120000, modified_at: '2026-10-02T16:10:00Z', thumbnail_url: photoSvg2 },
  ];

  const sharepointFiles: MockFsItem[] = [
    { name: 'Shared Documents', path: '/Shared Documents', is_dir: true, size: 0, modified_at: '2026-10-19T09:00:00Z' },
    { name: '公司產品目錄.pdf', path: '/Shared Documents/公司產品目錄.pdf', is_dir: false, size: 15420000, modified_at: '2026-10-20T11:30:00Z' },
  ];

  return {
    remotes: {
      gdrive: {
        name: 'gdrive',
        type: 'google_drive',
        is_default: true,
        details: { root_folder_id: 'root' },
        health: { status: 'success', latency_ms: 125.4, read_ok: true, write_ok: true, checked_at: Date.now() / 1000 },
      },
      onedrive: {
        name: 'onedrive',
        type: 'onedrive',
        is_default: false,
        details: { tenant: 'common', client_id: 'od-client-id-demo' },
        health: { status: 'success', latency_ms: 180.2, read_ok: true, write_ok: true, checked_at: Date.now() / 1000 - 300 },
      },
      sharepoint: {
        name: 'sharepoint',
        type: 'sharepoint',
        is_default: false,
        details: { base_url: 'https://company.sharepoint.com', site: '/sites/backup', email: 'admin@company.com' },
        health: { status: 'success', latency_ms: 240.5, read_ok: true, write_ok: true, checked_at: Date.now() / 1000 - 600 },
      },
      photos: {
        name: 'photos',
        type: 'googlephotos',
        is_default: false,
        details: { default_album: '2026家庭相簿' },
        health: { status: 'success', latency_ms: 145.8, read_ok: true, write_ok: false, checked_at: Date.now() / 1000 - 1200 },
      },
      pikpak: {
        name: 'pikpak',
        type: 'pikpak',
        is_default: false,
        details: { username: 'user@pikpak.me' },
        health: { status: 'success', latency_ms: 310.0, read_ok: true, write_ok: true, checked_at: Date.now() / 1000 - 1800 },
      },
      webdav: {
        name: 'webdav',
        type: 'webdav',
        is_default: false,
        details: { base_url: 'https://nas.internal:5005', username: 'synology' },
        health: { status: 'success', latency_ms: 45.2, read_ok: true, write_ok: true, checked_at: Date.now() / 1000 - 2400 },
      },
      ftp: {
        name: 'ftp',
        type: 'ftp',
        is_default: false,
        details: { host: 'ftp.backup.local', port: 21, username: 'backup_user' },
        health: { status: 'success', latency_ms: 32.1, read_ok: true, write_ok: true, checked_at: Date.now() / 1000 - 3600 },
      },
      sftp: {
        name: 'sftp',
        type: 'sftp',
        is_default: false,
        details: { host: 'vps.cloud.com', port: 22, username: 'root' },
        health: { status: 'success', latency_ms: 88.5, read_ok: true, write_ok: true, checked_at: Date.now() / 1000 - 4200 },
      },
      local: {
        name: 'local',
        type: 'local',
        is_default: false,
        details: { root_path: '/var/data/drive-unix' },
        health: { status: 'success', latency_ms: 1.2, read_ok: true, write_ok: true, checked_at: Date.now() / 1000 },
      },
    },
    quotas: {
      gdrive: { total: 2147483648000, used: 842100293120, filecount: 45120, supported: true }, // 2TB, ~39% used
      onedrive: { total: 1073741824000, used: 324100582000, filecount: 12450, supported: true }, // 1TB, ~30% used
      sharepoint: { total: 5368709120000, used: 2147483648000, filecount: 89100, supported: true }, // 5TB, 40% used
      webdav: { total: 4294967296000, used: 3120000000000, filecount: 154200, supported: true },
      photos: { total: 0, used: 0, filecount: 0, supported: false },
      pikpak: { total: 10995116277760, used: 4398046511104, filecount: 3200, supported: true }, // 10TB
      ftp: { total: 0, used: 0, filecount: 0, supported: false },
      sftp: { total: 0, used: 0, filecount: 0, supported: false },
      local: { total: 1000000000000, used: 550000000000, filecount: 24100, supported: true },
    },
    files: {
      gdrive: gdriveFiles,
      local: localFiles,
      photos: photosFiles,
      sharepoint: sharepointFiles,
      onedrive: [],
      pikpak: [],
      webdav: [],
      ftp: [],
      sftp: [],
    },
    tasks: [
      {
        id: 'mock-task-1',
        kind: 'sync',
        title: '同步: gdrive:/工作文件 -> onedrive:/backup',
        source_uri: 'gdrive:/工作文件',
        dest_uri: 'onedrive:/backup',
        status: 'running',
        created_at: Date.now() / 1000 - 120,
        bytes_done: 452819200,
        bytes_total: 1073741824,
        files_done: 45,
        files_total: 120,
        errors: 0,
        speed_bps: 15482910, // ~15.4 MB/s
        eta_seconds: 40,
        message: '傳輸中: 專案架構規劃.pdf (45%)',
      },
      {
        id: 'mock-task-2',
        kind: 'sync',
        title: '每日排程備份: local:/data -> sharepoint:/Shared Documents',
        source_uri: 'local:/data',
        dest_uri: 'sharepoint:/Shared Documents',
        status: 'completed',
        created_at: Date.now() / 1000 - 3600 * 2,
        finished_at: Date.now() / 1000 - 3600 * 2 + 180,
        bytes_done: 842100293,
        bytes_total: 842100293,
        files_done: 180,
        files_total: 180,
        errors: 0,
        speed_bps: 0,
        eta_seconds: 0,
        message: '同步順利完成！成功執行 180 項操作。',
      },
    ],
    schedules: {
      daily_backup: {
        name: 'daily_backup',
        schedule: '0 2 * * *',
        command: 'drive-unix sync local:/data gdrive:/backup --delete',
        enabled: true,
        last_run: '2026-10-22 02:00:00',
        last_attempt_at: '2026-10-22 02:00:00',
        last_success_at: '2026-10-22 02:03:15',
        last_exit_code: 0,
        next_run: '2026-10-23 02:00:00',
      },
      hourly_photos_sync: {
        name: 'hourly_photos_sync',
        schedule: '0 * * * *',
        command: 'drive-unix sync photos:/ onedrive:/photos_mirror',
        enabled: true,
        last_run: '2026-10-22 13:00:00',
        last_attempt_at: '2026-10-22 13:00:00',
        last_success_at: '2026-10-22 13:02:40',
        last_exit_code: 0,
        next_run: '2026-10-22 14:00:00',
      },
      weekly_archive: {
        name: 'weekly_archive',
        schedule: '0 4 * * 0',
        command: 'drive-unix sync gdrive:/archive pikpak:/cold_storage',
        enabled: false,
        last_run: '2026-10-18 04:00:00',
        last_attempt_at: '2026-10-18 04:00:00',
        last_success_at: '2026-10-18 04:45:10',
        last_exit_code: 0,
        next_run: null,
      },
    },
    daemon: {
      installed: true,
      running: true,
      pid: 14820,
      backend: 'TaskScheduler (Windows)',
      log_path: 'C:\\Users\\User\\.config\\drive-unix\\scheduler\\scheduler.log',
      log_tail: [
        '[2026-10-22 02:00:00] [INFO] Starting scheduled job: daily_backup',
        '[2026-10-22 02:03:15] [INFO] Job daily_backup completed with exit code 0',
        '[2026-10-22 13:00:00] [INFO] Starting scheduled job: hourly_photos_sync',
        '[2026-10-22 13:02:40] [INFO] Job hourly_photos_sync completed with exit code 0',
        '[2026-10-22 14:00:00] [INFO] Scheduler daemon heartbeat: healthy (3 active rules)',
      ],
    },
    settings: {
      cache: {
        enabled: true,
        ttl_seconds: 300,
        max_entries: 1000,
        persist_to_disk: true,
        cache_dir: null,
      },
      ui: {
        site_title: 'drive-unix',
        default_view_mode: 'dual',
        default_display_layout: 'list',
        enable_preview: true,
      },
      security: {
        max_upload_size_mb: 2048,
        allow_guest_download: true,
      },
      transfer: {
        max_workers: 4,
        bandwidth_limit_kbps: 0,
        log_level: 'INFO',
      },
      extra_options: {},
    },
    cacheStats: {
      enabled: true,
      ttl_seconds: 300,
      max_entries: 1000,
      current_entries: 42,
      hits: 320,
      misses: 45,
      ratio: 87.7,
      remotes_cached: ['gdrive', 'local', 'photos', 'sharepoint'],
      persisted_dirs: 42,
      persisted_thumbs: 18,
    },
    upstashConfig: {
      rest_url: 'https://us1-clean-whale-38291.upstash.io',
      has_token: true,
      has_passphrase: true,
      sync_key: 'drive-unix:sync:default',
      auto_sync_tokens: true,
      auto_push_tokens: true,
      renew_leeway_minutes: 30,
    },
    upstashTokens: [
      {
        identity: 'sharepoint:admin@company.com:https://company.sharepoint.com',
        identity_key: 'sp-main-ident-3982',
        remotes: ['sharepoint'],
        expires_at: Math.floor(Date.now() / 1000) + 3600 * 5, // 5 hours remaining
        updated_at: Math.floor(Date.now() / 1000) - 1800,
        device_id: 'workstation-win11-8f2a',
        is_locked: false,
        locked_by: null,
      },
      {
        identity: 'google_drive:user@gmail.com',
        identity_key: 'gdrive-main-ident-1029',
        remotes: ['gdrive', 'photos'],
        expires_at: Math.floor(Date.now() / 1000) + 3600 * 48,
        updated_at: Math.floor(Date.now() / 1000) - 3600,
        device_id: 'workstation-win11-8f2a',
        is_locked: false,
        locked_by: null,
      },
    ],
  };
}
