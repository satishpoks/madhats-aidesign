import { render, screen, fireEvent } from '@testing-library/react'
import { expect, test, beforeEach, vi } from 'vitest'
import { MilestoneBar } from './MilestoneBar'
import { useChatStore } from '../../store/chatStore'
import { restartUrl } from '../../lib/restartFlow'

const SECTIONS = ['Intro', 'Logo & Image', 'Text & Graphics', 'Review', 'Quote request']

beforeEach(() => {
  useChatStore.getState().reset()
})

test('renders nothing when progress has no sections (v1 / non-canvas)', () => {
  useChatStore.setState({ progress: { step: 3, total: 9 } })
  const { container } = render(<MilestoneBar />)
  expect(container.firstChild).toBeNull()
})

test('renders nothing when progress is null', () => {
  useChatStore.setState({ progress: null })
  const { container } = render(<MilestoneBar />)
  expect(container.firstChild).toBeNull()
})

test('renders all five labels for a v2 canvas session', () => {
  useChatStore.setState({ progress: { step: 5, total: 8, sections: SECTIONS, section: 2 } })
  render(<MilestoneBar />)
  for (const label of SECTIONS) expect(screen.getByText(label)).toBeInTheDocument()
})

test('marks earlier sections complete, the current one active, later ones upcoming', () => {
  useChatStore.setState({ progress: { step: 5, total: 8, sections: SECTIONS, section: 2 } })
  render(<MilestoneBar />)
  // data-state is one of: complete | current | upcoming, keyed by label.
  expect(screen.getByTestId('milestone-Intro')).toHaveAttribute('data-state', 'complete')
  expect(screen.getByTestId('milestone-Logo & Image')).toHaveAttribute('data-state', 'complete')
  expect(screen.getByTestId('milestone-Text & Graphics')).toHaveAttribute('data-state', 'current')
  expect(screen.getByTestId('milestone-Review')).toHaveAttribute('data-state', 'upcoming')
  expect(screen.getByTestId('milestone-Quote request')).toHaveAttribute('data-state', 'upcoming')
})

test('sets aria-current="step" on the active milestone only', () => {
  useChatStore.setState({ progress: { step: 5, total: 8, sections: SECTIONS, section: 2 } })
  render(<MilestoneBar />)
  expect(screen.getByTestId('milestone-Text & Graphics')).toHaveAttribute('aria-current', 'step')
  expect(screen.getByTestId('milestone-Intro')).not.toHaveAttribute('aria-current')
  expect(screen.getByTestId('milestone-Review')).not.toHaveAttribute('aria-current')
})

test('marks every section complete once section index is past the last (section == length)', () => {
  useChatStore.setState({ progress: { step: 8, total: 8, sections: SECTIONS, section: 5 } })
  render(<MilestoneBar />)
  for (const label of SECTIONS)
    expect(screen.getByTestId(`milestone-${label}`)).toHaveAttribute('data-state', 'complete')
})

// --- Start over -------------------------------------------------------------

test('renders a "Start over" control alongside the stepper', () => {
  useChatStore.setState({ progress: { step: 5, total: 8, sections: SECTIONS, section: 2 } })
  render(<MilestoneBar />)
  expect(screen.getByRole('button', { name: /start over/i })).toBeInTheDocument()
})

test('the first click only asks to confirm — it never navigates', () => {
  const assign = vi.fn()
  vi.spyOn(window, 'location', 'get').mockReturnValue({
    ...window.location,
    pathname: '/',
    search: '?product_id=abc',
    assign,
  } as unknown as Location)

  useChatStore.setState({ progress: { step: 5, total: 8, sections: SECTIONS, section: 2 } })
  render(<MilestoneBar />)
  fireEvent.click(screen.getByRole('button', { name: /start over/i }))

  expect(assign).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: /yes, start over/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument()
})

test('confirming navigates to a fresh start; cancelling backs out', () => {
  const assign = vi.fn()
  vi.spyOn(window, 'location', 'get').mockReturnValue({
    ...window.location,
    pathname: '/',
    search: '?product_id=abc',
    assign,
  } as unknown as Location)

  useChatStore.setState({ progress: { step: 5, total: 8, sections: SECTIONS, section: 2 } })
  render(<MilestoneBar />)

  fireEvent.click(screen.getByRole('button', { name: /start over/i }))
  fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
  expect(assign).not.toHaveBeenCalled()

  fireEvent.click(screen.getByRole('button', { name: /start over/i }))
  fireEvent.click(screen.getByRole('button', { name: /yes, start over/i }))
  expect(assign).toHaveBeenCalledWith('/?product_id=abc')
})

// restartUrl is the pure half: entry params survive, the resume token does not.
test('restartUrl keeps the entry params so the customer lands where they came in', () => {
  expect(restartUrl('/', '?product_id=abc')).toBe('/?product_id=abc')
  expect(restartUrl('/', '?mode=blank')).toBe('/?mode=blank')
  expect(restartUrl('/', '')).toBe('/')
})

test('restartUrl drops ?session= so a resume link cannot rehydrate the abandoned session', () => {
  expect(restartUrl('/', '?session=tok123')).toBe('/')
  expect(restartUrl('/', '?product_id=abc&session=tok123')).toBe('/?product_id=abc')
})
