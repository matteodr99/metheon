import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'

import { EMPTY_FILTERS } from './api'
import { SummaryPanel } from './Summary'
import { makeSummary, mockFetch } from './test/helpers'

function renderPanel(summary = makeSummary(), filters = EMPTY_FILTERS) {
  mockFetch(() => summary, { summary })
  return render(<SummaryPanel datasetId={1} filters={filters} />)
}

function tile(label: string) {
  const node = screen.getByText(label).closest('.tile')
  if (node === null) {
    throw new Error(`No tile labelled ${label}`)
  }
  return node as HTMLElement
}

describe('the tiles', () => {
  it('shows the number of matching events', async () => {
    renderPanel(makeSummary({ total: 272 }))

    await waitFor(() => {
      expect(within(tile('Events')).getByText('272')).toBeInTheDocument()
    })
  })

  it('shows the magnitude range', async () => {
    renderPanel(
      makeSummary({
        magnitude: { min: 0.19, max: 5.3, average: 1.65, unknown: 0 },
      }),
    )

    await waitFor(() => {
      expect(
        within(tile('Magnitude range')).getByText('0.2 – 5.3'),
      ).toBeInTheDocument()
    })
  })

  it('counts the events with no magnitude', async () => {
    /** Their absence must be on screen, not buried in the total. */
    renderPanel(
      makeSummary({
        total: 10,
        magnitude: { min: 1, max: 5, average: 3, unknown: 4 },
      }),
    )

    await waitFor(() => {
      expect(
        within(tile('Without magnitude')).getByText('4'),
      ).toBeInTheDocument()
    })
  })

  it('shows a dash when there is no magnitude at all', async () => {
    renderPanel(
      makeSummary({
        total: 0,
        magnitude: { min: null, max: null, average: null, unknown: 0 },
        by_day: [],
        by_event_type: [],
      }),
    )

    await waitFor(() => {
      expect(within(tile('Magnitude range')).getByText('—')).toBeInTheDocument()
    })
    expect(
      within(tile('Average magnitude')).getByText('—'),
    ).toBeInTheDocument()
  })
})

describe('the charts', () => {
  it('draws a bar per day', async () => {
    const { container } = renderPanel(
      makeSummary({
        by_day: [
          { day: '2026-09-01', count: 1 },
          { day: '2026-09-02', count: 3 },
          { day: '2026-09-03', count: 2 },
        ],
      }),
    )

    await waitFor(() => {
      expect(
        screen.getByRole('img', { name: 'Events per day (UTC)' }),
      ).toBeInTheDocument()
    })
    const perDay = container.querySelector('.charts figure svg')
    expect(perDay?.querySelectorAll('rect')).toHaveLength(3)
  })

  it('drops the year from the day labels', async () => {
    renderPanel(
      makeSummary({ by_day: [{ day: '2026-09-08', count: 1 }] }),
    )

    await waitFor(() => {
      expect(screen.getByText('09-08')).toBeInTheDocument()
    })
    expect(screen.queryByText('2026-09-08')).not.toBeInTheDocument()
  })

  it('draws a bar per event type', async () => {
    renderPanel(
      makeSummary({
        by_event_type: [
          { event_type: 'earthquake', count: 270 },
          { event_type: 'quarry blast', count: 1 },
        ],
      }),
    )

    await waitFor(() => {
      expect(screen.getByText('earthquake')).toBeInTheDocument()
    })
    expect(screen.getByText('quarry blast')).toBeInTheDocument()
  })

  it('says so when there is nothing to plot', async () => {
    renderPanel(
      makeSummary({ total: 0, by_day: [], by_event_type: [] }),
    )

    await waitFor(() => {
      expect(screen.getAllByText('No events to plot.')).toHaveLength(2)
    })
  })
})

describe('following the filters', () => {
  it('sends the applied filters to the summary endpoint', async () => {
    const summary = makeSummary()
    const { calls } = mockFetch(() => summary, { summary })

    render(
      <SummaryPanel
        datasetId={7}
        filters={{ ...EMPTY_FILTERS, min_magnitude: '4' }}
      />,
    )

    await waitFor(() => {
      expect(calls.length).toBeGreaterThan(0)
    })
    expect(calls[0].url).toContain('/api/datasets/7/earthquakes/summary')
    expect(calls[0].url).toContain('min_magnitude=4')
  })

  it('stays silent when the summary cannot be loaded', async () => {
    /** The table below already reports the outage; two alerts is noise. */
    mockFetch(() => null, { ok: false, status: 500 })

    const { container } = render(
      <SummaryPanel datasetId={1} filters={EMPTY_FILTERS} />,
    )

    await waitFor(() => {
      expect(container.querySelector('.summary-panel')).toBeNull()
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
