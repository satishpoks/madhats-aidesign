import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChatColumn } from '../components/CustomiseStudio/ChatColumn'
import { useChatStore } from '../store/chatStore'

function seed(msgs: { role: 'user' | 'assistant'; text: string }[]) {
  useChatStore.setState({
    messages: msgs.map((m, i) => ({ id: String(i), role: m.role, text: m.text })),
    chatState: 'ask_quantity', options: [], sending: false,
  })
}

describe('chat attribution', () => {
  it('gives every message a lane', () => {
    seed([
      { role: 'assistant', text: 'How many caps do you need?' },
      { role: 'user', text: '45' },
      { role: 'assistant', text: 'When do you need these by?' },
      { role: 'assistant', text: 'Select an option below.' },
    ])
    render(<ChatColumn />)
    expect(screen.getAllByTestId('msg-lane')).toHaveLength(4)
  })

  it('names the speaker only when the speaker changes', () => {
    seed([
      { role: 'assistant', text: 'When do you need these by?' },
      { role: 'assistant', text: 'Select an option below.' },
      { role: 'user', text: '2 weeks' },
      { role: 'assistant', text: 'Noted.' },
    ])
    render(<ChatColumn />)
    // Two assistant runs -> two assistant name lines, not three.
    expect(screen.getAllByText(/Design assistant/)).toHaveLength(2)
    expect(screen.getAllByText('You')).toHaveLength(1)
  })

  it('labels the customer "You", never their captured name', () => {
    // The name is PII and this element repeats on every run of their messages.
    useChatStore.setState({ collectedName: 'Satish' })
    seed([{ role: 'user', text: '45' }])
    render(<ChatColumn />)
    expect(screen.getByText('You')).toBeInTheDocument()
    expect(screen.queryByText(/Satish/)).not.toBeInTheDocument()
  })

  it('lanes the assistant in the brand primary and the customer in their own colour', () => {
    // The two speakers must be told apart by more than position. Ricardo carries
    // the store's primary colour; the customer carries the bubble colour the
    // admin set for them. Canvas accent belongs to the design tools only.
    seed([
      { role: 'assistant', text: 'Hello' },
      { role: 'user', text: 'Hi' },
    ])
    render(<ChatColumn />)
    const lanes = screen.getAllByTestId('msg-lane')
    expect(lanes[0].className).toContain('border-accent')
    expect(lanes[0].className).not.toContain('border-canvasAccent')
    expect(lanes[1].className).toContain('border-chatUserBubble')
  })
})
