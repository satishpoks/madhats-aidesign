import type { ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  loading?: boolean
  empty?: string
  onRowClick?: (row: T) => void
}

export function DataTable<T>({ columns, rows, loading, empty, onRowClick }: DataTableProps<T>) {
  if (loading) {
    return <div className="rounded-xl border border-[#e0e1ea] bg-white py-10 text-center text-sm text-[#6b6b80]">Loading…</div>
  }
  if (rows.length === 0) {
    return <div className="rounded-xl border border-[#e0e1ea] bg-white py-10 text-center text-sm text-[#6b6b80]">{empty ?? 'No records'}</div>
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-[#e0e1ea] bg-white">
      <table className="min-w-full text-sm">
        <thead className="bg-[#f0f1f5]">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className="px-4 py-3 text-left text-[11px] font-semibold text-[#6b6b80]">{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={`border-t border-[#e0e1ea] odd:bg-white even:bg-[#f8f9fa] ${onRowClick ? 'cursor-pointer hover:bg-[#fff7f2]' : ''}`}
            >
              {columns.map((c) => (
                <td key={c.key} className="px-4 py-3 text-[13px] text-[#1a1a2e]">{c.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
