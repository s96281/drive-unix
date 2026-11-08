/**
 * Format bytes into human-readable string (B, KB, MB, GB, TB).
 */
export function formatBytes(bytes: number | null | undefined, decimals = 1): string {
  if (bytes == null || isNaN(bytes) || bytes < 0) return '0 B';
  if (bytes === 0) return '0 B';

  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const safeI = Math.min(i, sizes.length - 1);

  return `${parseFloat((bytes / Math.pow(k, safeI)).toFixed(dm))} ${sizes[safeI]}`;
}

/**
 * Format throughput speed into human-readable string (e.g. 12.5 MB/s).
 */
export function formatSpeed(bps: number | null | undefined): string {
  if (bps == null || isNaN(bps) || bps <= 0) return '0 B/s';
  return `${formatBytes(bps)}/s`;
}

/**
 * Format estimated time remaining in seconds into (hh:mm:ss or mm:ss).
 */
export function formatEta(seconds: number | null | undefined): string {
  if (seconds == null || isNaN(seconds) || seconds <= 0 || !isFinite(seconds)) return '--';
  const sec = Math.round(seconds);
  if (sec < 60) return `${sec} 秒`;
  const mins = Math.floor(sec / 60);
  const remainingSec = sec % 60;
  if (mins < 60) {
    return `${mins} 分 ${remainingSec} 秒`;
  }
  const hours = Math.floor(mins / 60);
  const remainingMins = mins % 60;
  return `${hours} 小時 ${remainingMins} 分`;
}

/**
 * Format timestamp or ISO string into localized relative time.
 */
export function formatRelativeTime(dateInput: number | string | Date | null | undefined): string {
  if (!dateInput) return '--';

  let timestamp: number;
  if (typeof dateInput === 'number') {
    timestamp = dateInput > 1e11 ? dateInput : dateInput * 1000;
  } else if (typeof dateInput === 'string') {
    timestamp = new Date(dateInput).getTime();
  } else {
    timestamp = dateInput.getTime();
  }

  if (isNaN(timestamp)) return '--';

  const diffSeconds = Math.round((Date.now() - timestamp) / 1000);
  if (diffSeconds < 10) return '剛剛';
  if (diffSeconds < 60) return `${diffSeconds} 秒前`;
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes} 分鐘前`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours} 小時前`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays} 天前`;
  const diffMonths = Math.floor(diffDays / 30);
  if (diffMonths < 12) return `${diffMonths} 個月前`;
  return `${Math.floor(diffMonths / 12)} 年前`;
}

/**
 * Format timestamp or ISO string into localized YYYY-MM-DD HH:mm:ss.
 */
export function formatDateTime(dateInput: number | string | Date | null | undefined): string {
  if (!dateInput) return '--';

  let d: Date;
  if (typeof dateInput === 'number') {
    d = new Date(dateInput > 1e11 ? dateInput : dateInput * 1000);
  } else if (typeof dateInput === 'string') {
    d = new Date(dateInput);
  } else {
    d = dateInput;
  }

  if (isNaN(d.getTime())) return '--';

  const pad = (n: number) => String(n).padStart(2, '0');
  const year = d.getFullYear();
  const month = pad(d.getMonth() + 1);
  const day = pad(d.getDate());
  const hours = pad(d.getHours());
  const minutes = pad(d.getMinutes());
  const seconds = pad(d.getSeconds());

  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}
