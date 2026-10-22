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

  it('lists filesystem directory items with pagination', async () => {
    const allRes: any = await mockRouter.handle('GET', '/fs/gdrive/ls', {
      query: { path: '/' },
    });
    expect(allRes.items.length).toBeGreaterThanOrEqual(2);

    const pagedRes: any = await mockRouter.handle('GET', '/fs/gdrive/ls', {
      query: { path: '/', offset: 0, limit: 1 },
    });
    expect(pagedRes.items.length).toBe(1);
    expect(pagedRes.total_count).toBe(allRes.total_count);
    expect(pagedRes.items[0].path).toBe(allRes.items[0].path);

    const pagedRes2: any = await mockRouter.handle('GET', '/fs/gdrive/ls', {
      query: { path: '/', offset: 1, limit: 1 },
    });
    expect(pagedRes2.items.length).toBe(1);
    expect(pagedRes2.items[0].path).toBe(allRes.items[1].path);
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
