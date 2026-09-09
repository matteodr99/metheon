import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ThemeToggle } from './ThemeToggle'
import { applyTheme, readTheme, storeTheme } from './theme'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.style.colorScheme = ''
})

describe('choosing a theme', () => {
  it('follows the system until a choice is made', () => {
    render(<ThemeToggle />)

    expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(document.documentElement).not.toHaveAttribute('data-theme')
  })

  it('marks the chosen theme on the root element', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)

    await user.click(screen.getByRole('button', { name: 'Dark' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  })

  it('sets color-scheme so native controls match', async () => {
    /** Without it the date pickers stay light on a dark page. */
    const user = userEvent.setup()
    render(<ThemeToggle />)

    await user.click(screen.getByRole('button', { name: 'Dark' }))

    expect(document.documentElement.style.colorScheme).toBe('dark')
  })

  it('remembers the choice', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)

    await user.click(screen.getByRole('button', { name: 'Light' }))

    expect(readTheme()).toBe('light')
  })

  it('shows only one theme as pressed', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)

    await user.click(screen.getByRole('button', { name: 'Light' }))

    const pressed = screen
      .getAllByRole('button')
      .filter((button) => button.getAttribute('aria-pressed') === 'true')
    expect(pressed).toHaveLength(1)
    expect(pressed[0]).toHaveTextContent('Light')
  })

  it('goes back to following the system', async () => {
    /** Removing the attribute, not resolving it, so a later OS change is
        picked up while the tab stays open. */
    const user = userEvent.setup()
    render(<ThemeToggle />)

    await user.click(screen.getByRole('button', { name: 'Dark' }))
    await user.click(screen.getByRole('button', { name: 'System' }))

    expect(document.documentElement).not.toHaveAttribute('data-theme')
    expect(localStorage.getItem('metheon:theme')).toBeNull()
  })
})

describe('reading a stored choice', () => {
  it('starts from what was saved', () => {
    localStorage.setItem('metheon:theme', 'dark')

    render(<ThemeToggle />)

    expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('ignores a value it does not recognise', () => {
    localStorage.setItem('metheon:theme', 'neon')

    expect(readTheme()).toBe('system')
  })
})

describe('when storage is unavailable', () => {
  it('still applies the theme', () => {
    /** Private browsing throws on both read and write. */
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage')
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('blocked')
      },
    })

    try {
      expect(readTheme()).toBe('system')
      expect(() => storeTheme('dark')).not.toThrow()
      applyTheme('dark')
      expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    } finally {
      if (original !== undefined) {
        Object.defineProperty(window, 'localStorage', original)
      }
    }
  })
})
