import { describe, it, expect } from 'vitest';
import { formatBytes, formatSpeed, formatEta, formatRelativeTime } from './format';

describe('format utilities', () => {
  it('formats bytes properly', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1024)).toBe('1 KB');
    expect(formatBytes(1024 * 1024)).toBe('1 MB');
    expect(formatBytes(1024 * 1024 * 1024 * 1.5)).toBe('1.5 GB');
  });

  it('formats transfer speed properly', () => {
    expect(formatSpeed(0)).toBe('0 B/s');
    expect(formatSpeed(500 * 1024)).toBe('500 KB/s');
    expect(formatSpeed(10 * 1024 * 1024)).toBe('10 MB/s');
  });

  it('formats ETA properly', () => {
    expect(formatEta(null)).toBe('--');
    expect(formatEta(45)).toBe('45 秒');
    expect(formatEta(125)).toBe('2 分 5 秒');
    expect(formatEta(3665)).toBe('1 小時 1 分');
  });

  it('formats relative time safely', () => {
    expect(formatRelativeTime(null)).toBe('--');
    const justNow = new Date().toISOString();
    expect(formatRelativeTime(justNow)).toBe('剛剛');
  });
});
