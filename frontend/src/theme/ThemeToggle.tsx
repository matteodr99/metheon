import { useState } from 'react'

import { applyTheme, readTheme, storeTheme, THEMES, type Theme } from './theme'

const LABELS: Record<Theme, string> = {
  light: 'Light',
  dark: 'Dark',
  system: 'System',
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme)

  function choose(next: Theme) {
    setTheme(next)
    applyTheme(next)
    storeTheme(next)
  }

  return (
    <div className="theme-toggle" role="group" aria-label="Colour theme">
      {THEMES.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={theme === option}
          onClick={() => choose(option)}
        >
          {LABELS[option]}
        </button>
      ))}
    </div>
  )
}
