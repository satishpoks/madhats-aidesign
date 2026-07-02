import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DataTable } from '../admin/components/DataTable'
import { ErrorBanner } from '../admin/components/ErrorBanner'
import { StatusBadge } from '../admin/components/StatusBadge'

describe('ErrorBanner', () => {
  it('renders the message', () => {
    render(<ErrorBanner message="Boom" />)
    expect(screen.getByText('Boom')).toBeInTheDocument()
  })
})

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="pending" />)
    expect(screen.getByText('pending')).toBeInTheDocument()
  })
})

describe('DataTable', () => {
  interface Row { id: string; name: string }
  const columns = [
    { key: 'name', header: 'Name', render: (r: Row) => r.name },
  ]

  it('renders a loading state', () => {
    render(<DataTable<Row> columns={columns} rows={[]} loading />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('renders the empty message when there are no rows', () => {
    render(<DataTable<Row> columns={columns} rows={[]} empty="Nothing here" />)
    expect(screen.getByText('Nothing here')).toBeInTheDocument()
  })

  it('renders one row per item', () => {
    render(<DataTable<Row> columns={columns} rows={[{ id: '1', name: 'Alice' }, { id: '2', name: 'Bob' }]} />)
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
  })
})
