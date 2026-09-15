/**
 * Two pages, no router: the landing at the root and the dashboard under
 * /app/. A pure function of the path so it can be tested without a window;
 * Cloudflare Pages serves index.html for /app/ through public/_redirects
 * (and sends the bare /app there), and Vite's dev server does so for any
 * path.
 */
export type Page = 'landing' | 'app'

export function pageFor(pathname: string): Page {
  return pathname === '/app' || pathname.startsWith('/app/') ? 'app' : 'landing'
}
