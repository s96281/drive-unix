import { describe, it, expect } from 'vitest';
import { describeCron } from './cron';

describe('cron utilities', () => {
  it('converts common cron expressions to Traditional Chinese', () => {
    expect(describeCron('0 2 * * *')).toContain('02:00');
    expect(describeCron('0 * * * *')).toBeTruthy();
  });

  it('handles empty or invalid inputs gracefully', () => {
    expect(describeCron('')).toBe('未設定排程');
    expect(describeCron(null)).toBe('未設定排程');
    expect(describeCron('invalid_cron')).toBe('invalid_cron');
  });
});
