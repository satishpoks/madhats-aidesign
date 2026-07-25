import { render, screen } from '@testing-library/react'
import { expect, test, beforeEach } from 'vitest'
import { MilestoneBar } from './MilestoneBar'
import { useChatStore } from '../../store/chatStore'

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
