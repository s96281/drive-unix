import { mockRouter } from './router';

export class SSESimulator {
  private subscribers = new Set<(event: string, data: unknown, id?: string) => void>();
  private timer: number | null = null;
  private seq = 100;

  constructor() {
    this.startLoop();
  }

  public subscribe(
    onMessage: (event: string, data: unknown, id?: string) => void,
    _onError?: (err: Error) => void,
    _lastEventId?: string,
  ) {
    this.subscribers.add(onMessage);

    // Initial hello
    setTimeout(() => {
      onMessage('hello', { server_time: Date.now() / 1000, replayed: false }, String(++this.seq));
    }, 50);

    return {
      close: () => {
        this.subscribers.delete(onMessage);
      },
    };
  }

  public broadcast(event: string, data: unknown) {
    const id = String(++this.seq);
    for (const sub of this.subscribers) {
      try {
        sub(event, data, id);
      } catch (err) {
        console.error('SSE subscriber error:', err);
      }
    }
  }

  private startLoop() {
    if (typeof window === 'undefined') return;

    this.timer = window.setInterval(() => {
      // 1. Progress running tasks in mockRouter
      const runningTasks = mockRouter.db.tasks.filter((t) => t.status === 'running');
      for (const task of runningTasks) {
        const increment = Math.floor(Math.random() * 20000000) + 5000000;
        task.bytes_done = Math.min(task.bytes_total, task.bytes_done + increment);
        const remaining = Math.max(0, task.bytes_total - task.bytes_done);
        task.speed_bps = Math.floor(Math.random() * 5000000) + 12000000; // 12~17 MB/s
        task.eta_seconds = Math.round(remaining / task.speed_bps);

        if (task.bytes_done >= task.bytes_total) {
          task.status = 'completed';
          task.files_done = task.files_total;
          task.speed_bps = 0;
          task.eta_seconds = 0;
          task.message = '作業已順利完成！';
          this.broadcast('task.update', task);
          this.broadcast('task.log', {
            task_id: task.id,
            level: 'INFO',
            message: `[完成] ${task.title} 順利完成`,
            ts: Date.now() / 1000,
          });
        } else {
          task.files_done = Math.min(
            task.files_total,
            Math.floor((task.bytes_done / task.bytes_total) * task.files_total) + 1,
          );
          this.broadcast('task.update', task);
        }
      }

      // 2. Occasional simulated background log
      if (Math.random() > 0.6) {
        const sampleLogs = [
          'SchedulerDaemon 巡檢中：背景守護行程狀態正常',
          '目錄快取檢查：已命中 42 個條目',
          'Upstash E2EE 憑證有效期檢查：憑證均在安全期限內',
          '健康檢查：Google Drive 連線延遲 118ms',
        ];
        const logMsg = sampleLogs[Math.floor(Math.random() * sampleLogs.length)];
        this.broadcast('log', {
          level: 'INFO',
          logger: 'drive_unix.mock',
          message: logMsg,
          ts: Date.now() / 1000,
        });
      }

      // 3. Heartbeat
      if (Math.random() > 0.8) {
        this.broadcast('heartbeat', { ts: Date.now() / 1000 });
      }
    }, 1200);
  }

  public destroy() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.subscribers.clear();
  }
}

export const sseSimulator = new SSESimulator();
