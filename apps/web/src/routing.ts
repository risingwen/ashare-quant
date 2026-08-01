export type PageId = 'overview' | 'popularity' | 'moneyflow' | 'lhb' | 'research' | 'strategies' | 'portfolio' | 'system';

export const pagePaths: Record<PageId, string> = {
  overview: '/overview',
  popularity: '/popularity',
  moneyflow: '/moneyflow',
  lhb: '/lhb',
  research: '/research',
  strategies: '/strategies',
  portfolio: '/portfolio',
  system: '/system',
};

export function pageFromPath(pathname: string): PageId {
  const normalized = pathname.replace(/\/+$/, '') || '/';
  if (normalized === '/') return 'overview';
  const match = (Object.entries(pagePaths) as [PageId, string][])
    .find(([, path]) => path === normalized);
  return match?.[0] ?? 'overview';
}
