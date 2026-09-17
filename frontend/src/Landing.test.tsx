import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'

import { Landing } from './Landing'

describe('the landing page', () => {
  it('states the offer once and leads to the dashboard', () => {
    render(<Landing />)

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Public natural-event data, agency by agency.',
    )
    const doors = screen.getAllByRole('link', { name: 'Open the dashboard' })
    expect(doors.length).toBeGreaterThanOrEqual(2)
    for (const door of doors) {
      expect(door).toHaveAttribute('href', '/app/')
    }
  })

  it('wears the mark and offers the theme toggle', () => {
    render(<Landing />)

    expect(screen.getAllByRole('img', { name: 'Metheon' }).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByRole('button', { name: 'Dark' })).toBeInTheDocument()
  })

  it('links the code and the API docs', () => {
    render(<Landing />)

    const footer = screen.getByRole('navigation', { name: 'Elsewhere' })
    expect(within(footer).getByRole('link', { name: 'GitHub' })).toHaveAttribute(
      'href',
      'https://github.com/matteodr99/metheon',
    )
    expect(within(footer).getByRole('link', { name: 'API docs' }).getAttribute('href')).toMatch(/\/docs$/)
  })

  it('names all four agencies', () => {
    render(<Landing />)

    // The agencies also appear in the Vanuatu readings; the sources list
    // is where each is introduced.
    const sources = screen.getByRole('heading', { name: 'Four agencies, one table.' }).closest('section')!
    for (const agency of ['USGS', 'INGV', 'NASA EONET', 'GDACS']) {
      expect(within(sources).getByText(agency)).toBeInTheDocument()
    }
  })
})
