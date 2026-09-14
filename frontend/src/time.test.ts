import { describe, expect, it } from 'vitest'

import { timeAgo } from './time'

const NOW = new Date('2026-09-15T12:00:00Z')

describe('timeAgo', () => {
  it('treats the zoneless API time as UTC', () => {
    expect(timeAgo('2026-09-15T10:00:00', NOW)).toBe('2 h ago')
  })

  it('accepts a zoned time too', () => {
    expect(timeAgo('2026-09-15T12:00:00+02:00', NOW)).toBe('2 h ago')
  })

  it.each([
    ['2026-09-15T11:59:40', 'just now'],
    ['2026-09-15T11:35:00', '25 min ago'],
    ['2026-09-15T09:00:00', '3 h ago'],
    ['2026-09-14T13:00:00', '23 h ago'],
    ['2026-09-12T12:00:00', '3 d ago'],
  ])('%s → %s', (iso, expected) => {
    expect(timeAgo(iso, NOW)).toBe(expected)
  })

  it('is empty for nonsense', () => {
    expect(timeAgo('yesterday', NOW)).toBe('')
  })
})
