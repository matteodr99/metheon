import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { BarChart } from './BarChart'

function bars(container: HTMLElement) {
  return [...container.querySelectorAll('rect')]
}

function heightOf(rect: Element): number {
  return Number(rect.getAttribute('height'))
}

describe('drawing the bars', () => {
  it('draws one bar per value', () => {
    const { container } = render(
      <BarChart
        title="Per day"
        bars={[
          { label: 'a', value: 1 },
          { label: 'b', value: 2 },
          { label: 'c', value: 3 },
        ]}
      />,
    )

    expect(bars(container)).toHaveLength(3)
  })

  it('scales the heights to the largest value', () => {
    const { container } = render(
      <BarChart
        title="Per day"
        bars={[
          { label: 'a', value: 5 },
          { label: 'b', value: 10 },
        ]}
      />,
    )

    const [first, second] = bars(container).map(heightOf)
    expect(second).toBeGreaterThan(first)
    expect(first / second).toBeCloseTo(0.5, 5)
  })

  it('gives the largest value the full height', () => {
    const { container } = render(
      <BarChart title="Per day" bars={[{ label: 'a', value: 7 }]} />,
    )

    expect(heightOf(bars(container)[0])).toBe(60)
  })

  it('keeps a small value visible', () => {
    /** One event out of a thousand must not round away to nothing. */
    const { container } = render(
      <BarChart
        title="Per day"
        bars={[
          { label: 'a', value: 1 },
          { label: 'b', value: 1000 },
        ]}
      />,
    )

    expect(heightOf(bars(container)[0])).toBeGreaterThan(0)
  })

  it('draws nothing for a zero', () => {
    const { container } = render(
      <BarChart
        title="Per day"
        bars={[
          { label: 'a', value: 0 },
          { label: 'b', value: 4 },
        ]}
      />,
    )

    expect(heightOf(bars(container)[0])).toBe(0)
  })

  it('handles every value being equal', () => {
    const { container } = render(
      <BarChart
        title="Per day"
        bars={[
          { label: 'a', value: 3 },
          { label: 'b', value: 3 },
        ]}
      />,
    )

    const heights = bars(container).map(heightOf)
    expect(heights[0]).toBe(heights[1])
    expect(heights[0]).toBe(60)
  })
})

describe('labels and accessibility', () => {
  it('labels every bar when there are few', () => {
    const { container } = render(
      <BarChart
        title="Per day"
        bars={[
          { label: '09-01', value: 1 },
          { label: '09-02', value: 2 },
        ]}
      />,
    )

    const labels = [...container.querySelectorAll('.bar-labels span')].map(
      (node) => node.textContent,
    )
    expect(labels).toEqual(['09-01', '09-02'])
  })

  it('thins the labels when there are many', () => {
    /** Thirty labels on one axis overlap into an unreadable smear. */
    const many = Array.from({ length: 30 }, (_unused, index) => ({
      label: `d${index}`,
      value: index + 1,
    }))
    const { container } = render(<BarChart title="Per day" bars={many} />)

    expect(bars(container)).toHaveLength(30)
    const drawn = [...container.querySelectorAll('.bar-labels span')].filter(
      (node) => node.textContent !== '',
    )
    expect(drawn.length).toBeLessThanOrEqual(12)
  })

  it('names the chart for assistive technology', () => {
    render(<BarChart title="Events per day" bars={[{ label: 'a', value: 1 }]} />)

    expect(screen.getByRole('img', { name: 'Events per day' })).toBeVisible()
  })

  it('puts the value in a tooltip on each bar', () => {
    const { container } = render(
      <BarChart title="Per day" bars={[{ label: '09-01', value: 42 }]} />,
    )

    expect(container.querySelector('rect title')?.textContent).toBe('09-01: 42')
  })

  it('says so instead of drawing an empty chart', () => {
    render(<BarChart title="Per day" bars={[]} emptyMessage="Nothing here." />)

    expect(screen.getByText('Nothing here.')).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })
})
