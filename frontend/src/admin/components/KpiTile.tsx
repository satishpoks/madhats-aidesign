export type KpiTone = 'amber' | 'green' | 'indigo' | 'red' | 'neutral'

const TONES: Record<KpiTone, { bg: string; num: string }> = {
  amber: { bg: 'bg-[#fff2cc]', num: 'text-[#996600]' },
  green: { bg: 'bg-[#e5f7ed]', num: 'text-[#0a7a3a]' },
  indigo: { bg: 'bg-[#ebebff]', num: 'text-[#3333b2]' },
  red: { bg: 'bg-[#ffebeb]', num: 'text-[#bf0d0d]' },
  neutral: { bg: 'bg-white', num: 'text-[#1a1a2e]' },
}

export function KpiTile({ label, value, tone = 'neutral' }: { label: string; value: number | string; tone?: KpiTone }) {
  const t = TONES[tone]
  return (
    <div className={`rounded-xl border border-[#e0e1ea] px-5 py-3 ${t.bg}`}>
      <div className={`text-[32px] font-semibold leading-tight ${t.num}`}>{value}</div>
      <div className="text-[12px] text-[#6b6b80]">{label}</div>
    </div>
  )
}
