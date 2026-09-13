export type Theme = 'light' | 'dark' | 'system'

export const THEMES: Theme[] = ['light', 'dark', 'system']

const STORAGE_KEY = 'metheon:theme'

export function readTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') {
      return stored
    }
  } catch {
    // Private browsing and blocked storage both throw. Following the system
    // is a fine answer when the choice cannot be read.
  }
  return 'system'
}

/**
 * Reflect the theme on the root element.
 *
 * `system` removes the attribute rather than resolving it, so the page keeps
 * following the OS if it changes while the tab is open. `color-scheme` is set
 * alongside so native controls — date pickers, scrollbars — match too.
 */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement
  if (theme === 'system') {
    root.removeAttribute('data-theme')
    root.style.colorScheme = 'light dark'
  } else {
    root.setAttribute('data-theme', theme)
    root.style.colorScheme = theme
  }
}

export function storeTheme(theme: Theme): void {
  try {
    if (theme === 'system') {
      localStorage.removeItem(STORAGE_KEY)
    } else {
      localStorage.setItem(STORAGE_KEY, theme)
    }
  } catch {
    // The choice will not survive a reload, but the page still honours it.
  }
}
