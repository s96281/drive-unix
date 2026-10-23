import { ApiError, type HttpMethod, type RequestOptions } from '../transport';
import type { MockDatabase, MockFsItem } from './db';
import { createInitialMockDatabase } from './seed';

class MockRouter {
  public db: MockDatabase;

  constructor() {
    this.db = createInitialMockDatabase();
  }

  public reset() {
    this.db = createInitialMockDatabase();
  }

  async handle<T>(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<T> {
    // Artificial latency between 80ms - 250ms for realistic UI feel
    await new Promise((resolve) => setTimeout(resolve, Math.floor(Math.random() * 150) + 80));

    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    const [routePath] = cleanPath.split('?');
    const query = options.query || {};
    const body = options.body as any;

    // --- Remotes ---
    if (routePath === '/remotes' && method === 'GET') {
      return {
        default_remote: 'gdrive',
        supported_types: [
          'google_drive',
          'onedrive',
          'sharepoint',
          'googlephotos',
          'pikpak',
          'webdav',
          'ftp',
          'sftp',
          'local',
        ],
        remotes: Object.values(this.db.remotes),
      } as T;
    }

    if (routePath === '/remotes' && method === 'POST') {
      const name = body?.name;
      if (!name) throw new ApiError(400, '節點名稱不可為空');
      if (this.db.remotes[name]) throw new ApiError(409, `節點 '${name}' 已存在`);

      const remote = {
        name,
        type: body.type,
        is_default: !!body.is_default,
        details: body.params || {},
        health: { status: 'success', latency_ms: 45.0, read_ok: true, write_ok: true, checked_at: Date.now() / 1000 },
      };
      this.db.remotes[name] = remote;
      this.db.files[name] = [];
      this.db.quotas[name] = { total: 1000000000, used: 1000, filecount: 0, supported: true };
      return remote as T;
    }

    const testMatch = routePath.match(/^\/remotes\/([^/]+)\/test$/);
    if (testMatch && method === 'POST') {
      const name = testMatch[1];
      const remote = this.db.remotes[name];
      if (!remote) throw new ApiError(404, `找不到節點 '${name}'`);

      const res = {
        status: 'success' as const,
        name,
        read_ok: true,
        write_tested: !!body?.write,
        write_ok: !!body?.write,
        latency_ms: Math.round(Math.random() * 50 + 20),
        delete_capability: 'trash_supported',
        error: null,
      };
      remote.health = {
        status: 'success',
        latency_ms: res.latency_ms,
        read_ok: true,
        write_ok: res.write_ok,
        checked_at: Date.now() / 1000,
      };
      return res as T;
    }

    const quotaMatch = routePath.match(/^\/remotes\/([^/]+)\/quota$/);
    if (quotaMatch && method === 'GET') {
      const name = quotaMatch[1];
      const quota = this.db.quotas[name] || { total: 0, used: 0, filecount: 0, supported: false };
      return {
        supported: quota.supported,
        name,
        total: quota.total,
        used: quota.used,
        free: Math.max(0, quota.total - quota.used),
        filecount: quota.filecount,
      } as T;
    }

    const singleRemoteMatch = routePath.match(/^\/remotes\/([^/]+)$/);
    if (singleRemoteMatch) {
      const name = singleRemoteMatch[1];
      if (method === 'DELETE') {
        delete this.db.remotes[name];
        delete this.db.files[name];
        delete this.db.quotas[name];
        return { status: 'deleted', name } as T;
      }
      if (method === 'PUT') {
        const remote = this.db.remotes[name];
        if (!remote) throw new ApiError(404, `找不到節點 '${name}'`);
        if (body?.is_default) {
          Object.values(this.db.remotes).forEach((r) => (r.is_default = false));
          remote.is_default = true;
        }
        if (body?.params) {
          remote.details = { ...remote.details, ...body.params };
        }
        return remote as T;
      }
    }

    // --- Filesystem ---
    const lsMatch = routePath.match(/^\/fs\/([^/]+)\/ls$/);
    if (lsMatch && method === 'GET') {
      const remote = lsMatch[1];
      const dirPath = String(query.path || '/').replace(/\/+$/, '') || '/';
      const allItems = this.db.files[remote] || [];

      // Filter immediate children of dirPath
      const children = allItems.filter((item) => {
        if (dirPath === '/') {
          // direct root children
          return item.path.split('/').length === 2 && item.path.startsWith('/');
        }
        // children under dirPath
        return item.path.startsWith(dirPath + '/') && item.path.slice(dirPath.length + 1).split('/').length === 1;
      });

      const totalCount = children.length;
      const offset = query.offset !== undefined && query.offset !== null ? parseInt(String(query.offset), 10) : 0;
      const limit = query.limit !== undefined && query.limit !== null ? parseInt(String(query.limit), 10) : undefined;
      const pagedChildren = limit !== undefined ? children.slice(offset, offset + limit) : children.slice(offset);

      return {
        remote,
        path: dirPath,
        total_count: totalCount,
        items: pagedChildren.map((c) => ({
          name: c.name,
          path: c.path,
          is_dir: c.is_dir,
          size: c.size,
          modified_at: c.modified_at,
          thumbnail_url: c.thumbnail_url,
        })),
      } as T;
    }

    const readMatch = routePath.match(/^\/fs\/([^/]+)\/read$/);
    if (readMatch && method === 'GET') {
      const remote = readMatch[1];
      const file = (this.db.files[remote] || []).find((f) => f.path === String(query.path));
      if (!file || file.is_dir) throw new ApiError(404, '找不到檔案');
      const content = (file as { content?: string }).content ?? '';
      return { remote, path: file.path, content, size: file.size, truncated: false, is_binary: false, encoding: 'utf-8' } as T;
    }

    const linkMatch = routePath.match(/^\/fs\/([^/]+)\/(?:link|download-link)$/);
    if (linkMatch && method === 'GET') {
      const remote = linkMatch[1];
      const filePath = String(query.path);
      const file = (this.db.files[remote] || []).find((f) => f.path === filePath);
      if (!file || file.is_dir) throw new ApiError(404, '找不到檔案');
      const directUrl = file.thumbnail_url || `/api/fs/${encodeURIComponent(remote)}/raw?path=${encodeURIComponent(filePath)}`;
      return { remote, path: filePath, url: directUrl } as T;
    }

    const mkdirMatch = routePath.match(/^\/fs\/([^/]+)\/mkdir$/);
    if (mkdirMatch && method === 'POST') {
      const remote = mkdirMatch[1];
      const newPath = String(body.path);
      const name = newPath.split('/').pop() || 'new_folder';
      const items = this.db.files[remote] || (this.db.files[remote] = []);
      const newItem: MockFsItem = {
        name,
        path: newPath,
        is_dir: true,
        size: 0,
        modified_at: new Date().toISOString(),
      };
      items.push(newItem);
      return { status: 'created', remote, path: newPath } as T;
    }

    const delFileMatch = routePath.match(/^\/fs\/([^/]+)\/delete$/);
    if (delFileMatch && method === 'POST') {
      const remote = delFileMatch[1];
      const targetPath = String(body.path);
      const items = this.db.files[remote] || [];
      this.db.files[remote] = items.filter((i) => !i.path.startsWith(targetPath));
      return { status: 'deleted', remote, path: targetPath } as T;
    }

    const renameMatch = routePath.match(/^\/fs\/([^/]+)\/rename$/);
    if (renameMatch && method === 'POST') {
      const remote = renameMatch[1];
      const oldPath = String(body.path);
      const newName = String(body.new_name);
      const items = this.db.files[remote] || [];
      const item = items.find((i) => i.path === oldPath);
      if (!item) throw new ApiError(404, '找不到目標檔案');

      const parent = oldPath.substring(0, oldPath.lastIndexOf('/')) || '/';
      const newPath = parent === '/' ? `/${newName}` : `${parent}/${newName}`;
      item.name = newName;
      item.path = newPath;
      return { status: 'renamed', remote, old_path: oldPath, new_path: newPath } as T;
    }

    const moveMatch = routePath.match(/^\/fs\/([^/]+)\/move$/);
    if (moveMatch && method === 'POST') {
      const remote = moveMatch[1];
      const src = String(body.source);
      const dest = String(body.destination);
      const items = this.db.files[remote] || [];
      const item = items.find((i) => i.path === src);
      if (!item) throw new ApiError(404, '找不到來源檔案');
      item.path = dest;
      item.name = dest.split('/').pop() || item.name;
      return { status: 'moved', remote, source: src, destination: dest } as T;
    }

    const copyMatch = routePath.match(/^\/fs\/([^/]+)\/copy$/);
    if (copyMatch && method === 'POST') {
      const remote = copyMatch[1];
      const src = String(body.source);
      const dest = String(body.destination);
      const items = this.db.files[remote] || [];
      const item = items.find((i) => i.path === src);
      if (!item) throw new ApiError(404, '找不到來源檔案');
      const copyItem = { ...item, path: dest, name: dest.split('/').pop() || item.name };
      items.push(copyItem);
      return { status: 'copied', remote, source: src, destination: dest } as T;
    }

    if (routePath === '/fs/transfer' && method === 'POST') {
      const taskId = `mock-transfer-${Date.now().toString(36)}`;
      const taskRecord: any = {
        id: taskId,
        kind: 'transfer',
        title: `傳輸: ${body.sources?.length || 1} 個項目 -> ${body.dest_dir}`,
        source_uri: body.sources?.[0] || 'remote:/',
        dest_uri: body.dest_dir,
        status: 'running',
        created_at: Date.now() / 1000,
        bytes_done: 0,
        bytes_total: 85400000,
        files_done: 0,
        files_total: body.sources?.length || 1,
        errors: 0,
        speed_bps: 12500000,
        eta_seconds: 7,
        message: '開始傳輸檔案...',
        request_payload: body,
      };
      this.db.tasks.unshift(taskRecord);
      return { status: 'started', task_id: taskId } as T;
    }

    // --- Sync ---
    if (routePath === '/sync/plan' && method === 'POST') {
      return {
        source_uri: body.source_uri,
        dest_uri: body.dest_uri,
        total_actions: 5,
        has_destructive: !!body.delete,
        permanent_delete_count: body.delete ? 2 : 0,
        trash_delete_count: 0,
        actions: [
          { type: 'copy', target: '/文件1.pdf', reason: '檔案在目標端不存在', bytes: 1450000, is_dir: false },
          { type: 'update', target: '/專案備份.zip', reason: '來源端修改時間較新', bytes: 48900000, is_dir: false },
          { type: 'copy', target: '/資料夾', reason: '建立目錄', bytes: 0, is_dir: true },
          { type: 'copy', target: '/資料夾/sub.txt', reason: '檔案在目標端不存在', bytes: 12000, is_dir: false },
          ...(body.delete
            ? [{ type: 'delete_dest', target: '/舊檔案_2025.tmp', reason: '目的端多餘項目 (鏡像刪除)', bytes: 840000, is_dir: false }]
            : []),
        ],
        batches: [
          { name: '建立目錄結構', count: 1 },
          { name: '複製新增檔案', count: 3 },
          ...(body.delete ? [{ name: '清理目的端多餘項目', count: 1 }] : []),
        ],
        capabilities: {
          source_deletion: 'trash_supported',
          dest_deletion: 'permanent_only',
        },
      } as T;
    }

    if (routePath === '/sync/execute' && method === 'POST') {
      const taskId = `mock-sync-${Date.now().toString(36)}`;
      const taskRecord: any = {
        id: taskId,
        kind: 'sync',
        title: `同步: ${body.source_uri} -> ${body.dest_uri}`,
        source_uri: body.source_uri,
        dest_uri: body.dest_uri,
        status: 'running',
        created_at: Date.now() / 1000,
        bytes_done: 0,
        bytes_total: 50362000,
        files_done: 0,
        files_total: 5,
        errors: 0,
        speed_bps: 14200000,
        eta_seconds: 4,
        message: '開始同步掃描樹...',
        request_payload: body,
      };
      this.db.tasks.unshift(taskRecord);
      return { status: 'started', task_id: taskId } as T;
    }

    if (routePath === '/sync/tasks' && method === 'GET') {
      return this.db.tasks as T;
    }

    const taskActionMatch = routePath.match(/^\/sync\/tasks\/([^/]+)\/(pause|resume|cancel|retry)$/);
    if (taskActionMatch && method === 'POST') {
      const taskId = taskActionMatch[1];
      const action = taskActionMatch[2];
      const task = this.db.tasks.find((t) => t.id === taskId);
      if (!task) throw new ApiError(404, '找不到指定之工作');

      if (action === 'pause') {
        task.status = 'paused';
        task.message = '作業已手動暫停';
        return { status: 'paused', task_id: taskId } as T;
      }
      if (action === 'resume') {
        task.status = 'running';
        task.message = '作業已恢復執行';
        return { status: 'resumed', task_id: taskId } as T;
      }
      if (action === 'cancel') {
        task.status = 'cancelled';
        task.message = '作業已被取消';
        return { status: 'cancelled', task_id: taskId } as T;
      }
      if (action === 'retry') {
        const newId = `mock-retry-${Date.now().toString(36)}`;
        const retried = { ...task, id: newId, status: 'running' as const, bytes_done: 0, message: '重新開始執行...' };
        this.db.tasks.unshift(retried);
        return { status: 'started', task_id: newId } as T;
      }
    }

    // --- Schedule & Daemon ---
    if (routePath === '/schedule/daemon/status' && method === 'GET') {
      return this.db.daemon as T;
    }

    if (routePath === '/schedule/daemon/start' && method === 'POST') {
      this.db.daemon.running = true;
      this.db.daemon.pid = 19420;
      return { status: 'ok', running: true, pid: 19420 } as T;
    }

    if (routePath === '/schedule/daemon/stop' && method === 'POST') {
      this.db.daemon.running = false;
      this.db.daemon.pid = null;
      return { status: 'ok', running: false, pid: null } as T;
    }

    if (routePath === '/schedule/daemon/restart' && method === 'POST') {
      this.db.daemon.running = true;
      this.db.daemon.pid = 20110;
      return { status: 'ok', running: true, pid: 20110 } as T;
    }

    if (routePath === '/schedule' && method === 'GET') {
      return Object.values(this.db.schedules) as T;
    }

    if (routePath === '/schedule' && method === 'POST') {
      const name = body.name?.trim();
      if (!name) throw new ApiError(400, '任務名稱不可為空');
      if (this.db.schedules[name]) throw new ApiError(409, `任務 '${name}' 已經存在`);

      const newTask = {
        name,
        schedule: body.schedule,
        command: body.command,
        enabled: body.enabled !== false,
        last_run: null,
        last_attempt_at: null,
        last_success_at: null,
        last_exit_code: null,
        next_run: '2026-10-23 02:00:00',
      };
      this.db.schedules[name] = newTask;
      return newTask as T;
    }

    const schedItemMatch = routePath.match(/^\/schedule\/([^/]+)$/);
    if (schedItemMatch) {
      const name = schedItemMatch[1];
      if (method === 'DELETE') {
        delete this.db.schedules[name];
        return { status: 'deleted', name } as T;
      }
      if (method === 'PUT') {
        const item = this.db.schedules[name];
        if (!item) throw new ApiError(404, '找不到指定之排程');
        if (body.schedule) item.schedule = body.schedule;
        if (body.command) item.command = body.command;
        if (body.enabled != null) item.enabled = body.enabled;
        return item as T;
      }
    }

    const schedActionMatch = routePath.match(/^\/schedule\/([^/]+)\/(toggle|run)$/);
    if (schedActionMatch && method === 'POST') {
      const name = schedActionMatch[1];
      const action = schedActionMatch[2];
      const item = this.db.schedules[name];
      if (!item) throw new ApiError(404, '找不到指定之排程');

      if (action === 'toggle') {
        item.enabled = !!body.enabled;
        return item as T;
      }
      if (action === 'run') {
        item.last_run = new Date().toISOString().replace('T', ' ').substring(0, 19);
        item.last_exit_code = 0;
        return { status: 'triggered', name, pid: 21990 } as T;
      }
    }

    // --- Settings & Cache ---
    if (routePath === '/settings' && method === 'GET') {
      return {
        settings: this.db.settings,
        cache_stats: this.db.cacheStats,
      } as T;
    }

    if (routePath === '/settings' && method === 'PUT') {
      if (body.transfer) {
        this.db.settings.transfer = { ...this.db.settings.transfer, ...body.transfer };
      }
      if (body.ui) {
        this.db.settings.ui = { ...this.db.settings.ui, ...body.ui };
      }
      if (body.cache) {
        this.db.settings.cache = { ...this.db.settings.cache, ...body.cache };
      }
      return {
        settings: this.db.settings,
        cache_stats: this.db.cacheStats,
      } as T;
    }

    if (routePath === '/settings/cache/clear' && method === 'POST') {
      const count = this.db.cacheStats.current_entries;
      this.db.cacheStats.current_entries = 0;
      this.db.cacheStats.hits = 0;
      this.db.cacheStats.misses = 0;
      this.db.cacheStats.ratio = 0;
      return {
        status: 'cleared',
        cleared_entries: count,
        message: `已清空所有目錄快取 (${count} 項目)。`,
        stats: this.db.cacheStats,
      } as T;
    }

    // --- Upstash ---
    if (routePath === '/upstash/config' && method === 'GET') {
      return this.db.upstashConfig as T;
    }

    if (routePath === '/upstash/config' && method === 'POST') {
      this.db.upstashConfig = { ...this.db.upstashConfig, ...body };
      return this.db.upstashConfig as T;
    }

    if (routePath === '/upstash/tokens' && method === 'GET') {
      return this.db.upstashTokens as T;
    }

    const delTokenMatch = routePath.match(/^\/upstash\/tokens\/([^/]+)$/);
    if (delTokenMatch && method === 'DELETE') {
      const key = delTokenMatch[1];
      this.db.upstashTokens = this.db.upstashTokens.filter((t) => t.identity_key !== key);
      return { status: 'ok', deleted: key } as T;
    }

    const delLockMatch = routePath.match(/^\/upstash\/locks\/([^/]+)$/);
    if (delLockMatch && method === 'DELETE') {
      const key = delLockMatch[1];
      const tok = this.db.upstashTokens.find((t) => t.identity_key === key);
      if (tok) {
        tok.is_locked = false;
        tok.locked_by = null;
      }
      return { status: 'ok', released: key } as T;
    }

    if (routePath === '/upstash/test' && method === 'POST') {
      return { status: 'ok', ping: 'PONG', latency_ms: 68.2, url: this.db.upstashConfig.rest_url } as T;
    }

    if (routePath === '/upstash/push' && method === 'POST') {
      return { status: 'ok', uploaded: true, remotes_count: Object.keys(this.db.remotes).length } as T;
    }

    if (routePath === '/upstash/pull' && method === 'POST') {
      return { status: 'ok', merged_remotes: Object.keys(this.db.remotes).length, dry_run: !!body?.dry_run } as T;
    }

    if (routePath === '/upstash/renew-tokens' && method === 'POST') {
      return {
        renewed: ['sharepoint'],
        skipped: ['gdrive'],
        cloud_synced: ['sharepoint'],
        errors: {},
      } as T;
    }

    throw new ApiError(404, `Mock 端點未找到: ${method} ${routePath}`);
  }
}

export const mockRouter = new MockRouter();
