import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { EMPTY_FILTERS, type Insights } from '../api'
import { InsightsPanel } from './InsightsPanel'
import { mockFetch } from '../test/helpers'

const ON = { configured: true, model: 'gemini-3.8-flash' }

function makeInsights(overrides: Partial<Insights> = {}): Insights {
  return {
    dataset_id: 1,
    filters: {},
    model: 'gemini-3.8-flash',
    summary: 'A quiet week with one notable event.',
    key_trends: ['Activity peaked on 09-10.'],
    anomalies: ['An M6.3 event far above the rest.'],
    recommendations: ['Filter to M3+ to see the significant events.'],
    agency_comparison: '',
    other_id: null,
    ...overrides,
  }
}

/** Serve the status and, for the insights URL, whatever the test decides. */
function mockAI(ai: { configured: boolean; model: string }, insights: () => unknown, options = {}) {
  return mockFetch(
    (url) => (url.includes('/insights') ? insights() : null),
    { ai, ...options },
  )
}

describe('when AI is not configured', () => {
  it('says so and offers no button', async () => {
    mockAI({ configured: false, model: '' }, () => null)

    render(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)

    expect(await screen.findByText(/Not configured/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('treats a failing status call as not configured', async () => {
    mockFetch(() => null, { ok: false, status: 500 })

    render(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)

    expect(await screen.findByText(/Not configured/)).toBeInTheDocument()
  })
})

describe('when AI is configured', () => {
  it('does not ask the model until the reader does', async () => {
    /** Every call is metered; changing filters must not spend it. */
    const { calls } = mockAI(ON, () => makeInsights())

    render(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)
    await screen.findByRole('button', { name: 'Analyse this view' })

    expect(calls.some((c) => c.url.includes('/insights'))).toBe(false)
  })

  it('shows the model it will use', async () => {
    mockAI(ON, () => makeInsights())

    render(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)

    expect(await screen.findByText('gemini-3.8-flash')).toBeInTheDocument()
  })

  it('asks with the current filters and renders the four parts', async () => {
    const { calls } = mockAI(ON, () => makeInsights())
    const user = userEvent.setup()

    render(
      <InsightsPanel
        datasetId={7}
        filters={{ ...EMPTY_FILTERS, min_magnitude: '4' }}
      />,
    )
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))

    expect(await screen.findByText('A quiet week with one notable event.')).toBeInTheDocument()
    expect(screen.getByText('Activity peaked on 09-10.')).toBeInTheDocument()
    expect(screen.getByText('An M6.3 event far above the rest.')).toBeInTheDocument()
    expect(screen.getByText(/Filter to M3\+/)).toBeInTheDocument()
    const request = calls.find((c) => c.url.includes('/insights'))
    expect(request?.url).toContain('/api/datasets/7/insights')
    expect(request?.url).toContain('min_magnitude=4')
  })

  it('leaves out an empty section rather than a heading with nothing under it', async () => {
    mockAI(ON, () => makeInsights({ anomalies: [] }))
    const user = userEvent.setup()

    render(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))
    await screen.findByText('A quiet week with one notable event.')

    expect(screen.queryByText('Anomalies')).not.toBeInTheDocument()
    expect(screen.getByText('Key trends')).toBeInTheDocument()
  })

  it('offers to analyse again once an answer is shown', async () => {
    mockAI(ON, () => makeInsights())
    const user = userEvent.setup()

    render(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))

    expect(await screen.findByRole('button', { name: 'Analyse again' })).toBeInTheDocument()
  })

  it('shows the reason when the model call fails', async () => {
    /**
     * The API puts the cause in `detail`; the reader must see it. The
     * status call must succeed while the insights call fails, which the
     * shared stand-in cannot express, so this one is routed by hand.
     */
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/ai') {
          return { ok: true, status: 200, json: async () => ON } as Response
        }
        return {
          ok: false,
          status: 502,
          json: async () => ({ detail: 'Gemini answered 429: quota exceeded' }),
        } as Response
      }),
    )
    const user = userEvent.setup()

    render(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('quota exceeded')
    expect(screen.getByRole('button', { name: 'Analyse this view' })).toBeEnabled()
  })
})

describe('comparing with another agency', () => {
  it('asks with the compared dataset and its window, and shows the answer', async () => {
    const { calls } = mockAI(ON, () =>
      makeInsights({
        other_id: 5,
        agency_comparison: 'GDACS reported 45 of these fires, on average 4 km away.',
      }),
    )
    const user = userEvent.setup()

    render(
      <InsightsPanel
        datasetId={3}
        filters={EMPTY_FILTERS}
        comparison={{ otherId: 5, window: { windowSeconds: 259200, radiusKm: 50 } }}
      />,
    )
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))

    expect(await screen.findByText('GDACS reported 45 of these fires, on average 4 km away.')).toBeInTheDocument()
    expect(screen.getByText('Agencies compared')).toBeInTheDocument()
    const request = calls.find((c) => c.url.includes('/insights'))!
    expect(request.url).toBe('/api/datasets/3/insights?other=5&window_seconds=259200&radius_km=50')
  })

  it('asks for nothing of the sort without a comparison, and shows no heading', async () => {
    const { calls } = mockAI(ON, () => makeInsights())
    const user = userEvent.setup()

    render(<InsightsPanel datasetId={3} filters={EMPTY_FILTERS} />)
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))

    await screen.findByText('A quiet week with one notable event.')
    expect(screen.queryByText('Agencies compared')).not.toBeInTheDocument()
    expect(calls.find((c) => c.url.includes('/insights'))!.url).toBe('/api/datasets/3/insights?')
  })

  it('drops the answer when the compared dataset changes', async () => {
    mockAI(ON, () => makeInsights())
    const user = userEvent.setup()
    const window = { windowSeconds: 60, radiusKm: 100 }

    const { rerender } = render(
      <InsightsPanel datasetId={3} filters={EMPTY_FILTERS} comparison={{ otherId: 5, window }} />,
    )
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))
    await screen.findByText('A quiet week with one notable event.')

    rerender(<InsightsPanel datasetId={3} filters={EMPTY_FILTERS} comparison={{ otherId: 6, window }} />)

    expect(screen.queryByText('A quiet week with one notable event.')).not.toBeInTheDocument()
  })
})

describe('an answer belongs to the view it described', () => {
  it('disappears when the filters change', async () => {
    mockAI(ON, () => makeInsights())
    const user = userEvent.setup()

    const { rerender } = render(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))
    await screen.findByText('A quiet week with one notable event.')

    rerender(
      <InsightsPanel datasetId={1} filters={{ ...EMPTY_FILTERS, min_magnitude: '5' }} />,
    )

    expect(screen.queryByText('A quiet week with one notable event.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyse this view' })).toBeInTheDocument()
  })

  it('disappears when the data changes underneath it', async () => {
    mockAI(ON, () => makeInsights())
    const user = userEvent.setup()

    const { rerender } = render(
      <InsightsPanel datasetId={1} filters={EMPTY_FILTERS} dataVersion={0} />,
    )
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))
    await screen.findByText('A quiet week with one notable event.')

    rerender(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} dataVersion={1} />)

    expect(screen.queryByText('A quiet week with one notable event.')).not.toBeInTheDocument()
  })

  it('comes back if the reader returns to the same view', async () => {
    /** No refetch: the answer for that view is still valid. */
    const { calls } = mockAI(ON, () => makeInsights())
    const user = userEvent.setup()

    const { rerender } = render(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)
    await user.click(await screen.findByRole('button', { name: 'Analyse this view' }))
    await screen.findByText('A quiet week with one notable event.')
    const asked = calls.filter((c) => c.url.includes('/insights')).length

    rerender(<InsightsPanel datasetId={1} filters={{ ...EMPTY_FILTERS, event_type: 'x' }} />)
    rerender(<InsightsPanel datasetId={1} filters={EMPTY_FILTERS} />)

    expect(screen.getByText('A quiet week with one notable event.')).toBeInTheDocument()
    expect(calls.filter((c) => c.url.includes('/insights')).length).toBe(asked)
  })
})
