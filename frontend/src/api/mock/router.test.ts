import { describe, it, expect, beforeEach } from 'vitest';
import { mockRouter } from './router';

describe('MockRouter', () => {
  beforeEach(() => {
    mockRouter.reset();
  });

  it('lists initial seeded remotes', async () => {
    const res: any = await mockRouter.handle('GET', '/remotes');
    expect(res.remotes).toBeDefined();
    expect(res.remotes.length).toBeGreaterThanOrEqual(5);
    expect(res.default_remote).toBe('gdrive');
  });

  it('lists filesystem directory items', async () => {
    const res: any = await mockRouter.handle('GET', '/fs/gdrive/ls', {
      query: { path: '/' },
    });
    expect(res.items).toBeDefined();
    expect(res.total_count).toBeGreaterThan(0);
  });

  it('generates dry-run sync plan', async () => {
    const res: any = await mockRouter.handle('POST', '/sync/plan', {
      body: {
        source_uri: 'gdrive:/Backups',
        dest_uri: 'onedrive:/Backups',
        mode: 'sync',
      },
    });
    expect(res.total_actions).toBeDefined();
    expect(res.actions.length).toBeGreaterThan(0);
  });
});
