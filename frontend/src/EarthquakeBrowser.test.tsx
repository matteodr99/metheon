import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { EarthquakeBrowser } from './EarthquakeBrowser'
import {
  deferred,
  makeEarthquake,
  makePage,
  mockFetch,
  urlsOf,
} from './test/helpers'

function manyEvents(count: number, offset = 0) {
  return Array.from({ length: count }, (_unused, index) =>
    makeEarthquake({
      id: offset + index + 1,
      external_id: `eq${offset + index + 1}`,
      place: `place ${offset + index + 1}`,
    }),
  )
}

describe('rendering the events', () => {
  it('shows a row per event', async () => {
    mockFetch(() => makePage([makeEarthquake({ place: 'Anza, CA' })]))

    render(<EarthquakeBrowser datasetId={1} />)

    expect(await screen.findByText('Anza, CA')).toBeInTheDocument()
  })

  it('shows a dash when the magnitude is missing', async () => {
    /** The feed omits it legitimately; printing 0 would be a lie. */
    mockFetch(() =>
      makePage([makeEarthquake({ magnitude: null, magnitude_type: null })]),
    )

    render(<EarthquakeBrowser datasetId={1} />)

    expect(await screen.findByText('—')).toBeInTheDocument()
  })

  it('links to the event page when the feed gives a url', async () => {
    mockFetch(() =>
      makePage([
        makeEarthquake({ place: 'Anza, CA', url: 'https://example.invalid/e' }),
      ]),
    )

    render(<EarthquakeBrowser datasetId={1} />)

    const link = await screen.findByRole('link', { name: 'Anza, CA' })
    expect(link).toHaveAttribute('href', 'https://example.invalid/e')
  })

  it('says so when nothing matches', async () => {
    mockFetch(() => makePage([]))

    render(<EarthquakeBrowser datasetId={1} />)

    expect(
      await screen.findByText('No events match these filters.'),
    ).toBeInTheDocument()
  })

  it('reports a failing request', async () => {
    mockFetch(() => null, { ok: false, status: 500 })

    render(<EarthquakeBrowser datasetId={1} />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The API answered 500',
    )
  })
})

describe('applying filters', () => {
  it('does not request while the user types', async () => {
    /** Otherwise typing 4.5 would be three requests instead of one. */
    const { calls } = mockFetch(() => makePage([makeEarthquake()]))
    const user = userEvent.setup()

    render(<EarthquakeBrowser datasetId={1} />)
    await screen.findByText('somewhere')
    const before = calls.length

    await user.type(screen.getByLabelText('Min magnitude'), '4.5')

    expect(calls.length).toBe(before)
  })

  it('requests once the form is submitted', async () => {
    const { calls } = mockFetch(() => makePage([makeEarthquake()]))
    const user = userEvent.setup()

    render(<EarthquakeBrowser datasetId={1} />)
    await screen.findByText('somewhere')

    await user.type(screen.getByLabelText('Min magnitude'), '4.5')
    await user.click(screen.getByRole('button', { name: 'Apply' }))

    await waitFor(() => {
      expect(urlsOf(calls).some((url) => url.includes('min_magnitude=4.5'))).toBe(
        true,
      )
    })
  })

  it('returns to the first page when the filters change', async () => {
    /** The old offset may be past the end of the narrower result. */
    const { calls } = mockFetch(() =>
      makePage(manyEvents(25), { total: 200, offset: 0 }),
    )
    const user = userEvent.setup()

    render(<EarthquakeBrowser datasetId={1} />)
    await screen.findByText('place 1')

    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => {
      expect(urlsOf(calls).some((url) => url.includes('offset=25'))).toBe(true)
    })

    await user.type(screen.getByLabelText('Min magnitude'), '4')
    await user.click(screen.getByRole('button', { name: 'Apply' }))

    await waitFor(() => {
      const last = urlsOf(calls).at(-1) ?? ''
      expect(last).toContain('min_magnitude=4')
      expect(last).toContain('offset=0')
    })
  })

  it('clears the filters on reset', async () => {
    const { calls } = mockFetch(() => makePage([makeEarthquake()]))
    const user = userEvent.setup()

    render(<EarthquakeBrowser datasetId={1} />)
    await screen.findByText('somewhere')

    await user.type(screen.getByLabelText('Min magnitude'), '4')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => {
      expect(urlsOf(calls).at(-1)).toContain('min_magnitude=4')
    })

    await user.click(screen.getByRole('button', { name: 'Reset' }))

    await waitFor(() => {
      expect(urlsOf(calls).at(-1)).not.toContain('min_magnitude')
    })
    expect(screen.getByLabelText('Min magnitude')).toHaveValue(null)
  })
})

describe('paging', () => {
  it('disables Previous on the first page', async () => {
    mockFetch(() => makePage(manyEvents(25), { total: 200 }))

    render(<EarthquakeBrowser datasetId={1} />)
    await screen.findByText('place 1')

    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  it('disables Next when the result fits on one page', async () => {
    mockFetch(() => makePage(manyEvents(3), { total: 3 }))

    render(<EarthquakeBrowser datasetId={1} />)
    await screen.findByText('place 1')

    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
  })

  it('asks for the next offset', async () => {
    const { calls } = mockFetch(() => makePage(manyEvents(25), { total: 200 }))
    const user = userEvent.setup()

    render(<EarthquakeBrowser datasetId={1} />)
    await screen.findByText('place 1')

    await user.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => {
      expect(urlsOf(calls).at(-1)).toContain('offset=25')
    })
  })
})

describe('the caption', () => {
  it('counts the page on screen', async () => {
    mockFetch(() => makePage(manyEvents(25), { total: 200, offset: 25 }))

    render(<EarthquakeBrowser datasetId={1} />)

    expect(await screen.findByText(/Showing 26–50 of 200/)).toBeInTheDocument()
  })

  it('keeps counting the old page while the next one loads', async () => {
    /**
     * Regression: the caption used to count the offset being requested, so
     * during a page change it read "Showing 26-50" above the rows 1-25 that
     * were still displayed.
     */
    const second = deferred<unknown>()
    let call = 0
    mockFetch(() => {
      call += 1
      if (call === 1) {
        return makePage(manyEvents(25), { total: 200, offset: 0 })
      }
      return second.promise
    })
    const user = userEvent.setup()

    render(<EarthquakeBrowser datasetId={1} />)
    await screen.findByText(/Showing 1–25 of 200/)

    await user.click(screen.getByRole('button', { name: 'Next' }))

    expect(screen.getByText(/Showing 1–25 of 200/)).toBeInTheDocument()
    expect(screen.getByText('place 1')).toBeInTheDocument()

    second.resolve(makePage(manyEvents(25, 25), { total: 200, offset: 25 }))
    expect(await screen.findByText(/Showing 26–50 of 200/)).toBeInTheDocument()
  })
})

describe('overlapping requests', () => {
  it('does not let a slow earlier response replace a newer one', async () => {
    /**
     * Without cancellation the first response could land last and show rows
     * that contradict the filters on screen.
     */
    const slow = deferred<unknown>()
    let call = 0
    mockFetch(() => {
      call += 1
      if (call === 1) {
        return makePage([makeEarthquake({ place: 'first response' })])
      }
      if (call === 2) {
        return slow.promise
      }
      return makePage([makeEarthquake({ place: 'newest response' })])
    })
    const user = userEvent.setup()

    render(<EarthquakeBrowser datasetId={1} />)
    await screen.findByText('first response')

    await user.type(screen.getByLabelText('Min magnitude'), '4')
    await user.click(screen.getByRole('button', { name: 'Apply' }))

    await user.clear(screen.getByLabelText('Min magnitude'))
    await user.type(screen.getByLabelText('Min magnitude'), '5')
    await user.click(screen.getByRole('button', { name: 'Apply' }))

    await screen.findByText('newest response')

    slow.resolve(makePage([makeEarthquake({ place: 'stale response' })]))

    await waitFor(() => {
      expect(screen.getByText('newest response')).toBeInTheDocument()
    })
    expect(screen.queryByText('stale response')).not.toBeInTheDocument()
  })
})
