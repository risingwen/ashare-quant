import {describe, expect, it} from 'vitest';
import {pageFromPath, pagePaths} from './routing';

describe('shareable page routing', () => {
  it('maps every navigation target to a stable path', () => {
    for (const [page, path] of Object.entries(pagePaths)) {
      expect(pageFromPath(path)).toBe(page);
      expect(pageFromPath(`${path}/`)).toBe(page);
    }
  });

  it('keeps root and unknown paths safe', () => {
    expect(pageFromPath('/')).toBe('overview');
    expect(pageFromPath('/not-a-page')).toBe('overview');
  });
});
