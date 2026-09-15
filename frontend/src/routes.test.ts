import { describe, expect, it } from 'vitest'

import { pageFor } from './routes'

describe('pageFor', () => {
  it.each([
    ['/', 'landing'],
    ['/index.html', 'landing'],
    ['/about', 'landing'],
    ['/app', 'app'],
    ['/app/', 'app'],
    ['/app/anything', 'app'],
    ['/application', 'landing'],
  ])('%s → %s', (path, page) => {
    expect(pageFor(path)).toBe(page)
  })
})
