// Figma admin palette — pill = bg + matching border/text.
const STYLES: Record<string, string> = {
  pending: 'bg-[#fff2cc] border-[#996600] text-[#996600]',
  approved: 'bg-[#e5f7ed] border-[#0a7a3a] text-[#0a7a3a]',
  active: 'bg-[#e5f7ed] border-[#0a7a3a] text-[#0a7a3a]',
  complete: 'bg-[#e5f7ed] border-[#0a7a3a] text-[#0a7a3a]',
  needs_changes: 'bg-[#ebebff] border-[#3333cc] text-[#3333cc]',
  rejected: 'bg-[#ffebeb] border-[#bf0d0d] text-[#bf0d0d]',
  failed: 'bg-[#ffebeb] border-[#bf0d0d] text-[#bf0d0d]',
}

export function StatusBadge({ status }: { status: string }) {
  const cls = STYLES[status] ?? 'bg-[#f0f1f5] border-[#e0e1ea] text-[#6b6b80]'
  return (
    <span className={`inline-block whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${cls}`}>
      {status}
    </span>
  )
}
