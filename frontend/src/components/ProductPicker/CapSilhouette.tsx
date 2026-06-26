import type { CapStyle } from '../../data/products'

interface Props {
  style: CapStyle
  colour: string
}

export function CapSilhouette({ style, colour }: Props) {
  const fill = colour
  const shadow = 'rgba(0,0,0,0.35)'

  if (style === 'snapback') return (
    <svg viewBox="0 0 200 130" fill="none" className="w-full h-full">
      <ellipse cx="100" cy="85" rx="72" ry="14" fill={shadow} />
      <path d="M35 82 Q28 38 100 30 Q172 38 165 82 Z" fill={fill} />
      <rect x="24" y="80" width="118" height="13" rx="4" fill={fill} />
      <rect x="142" y="83" width="34" height="7" rx="3" fill={fill} opacity="0.55" />
      <line x1="100" y1="30" x2="100" y2="82" stroke="rgba(255,255,255,0.07)" strokeWidth="1" />
      <ellipse cx="100" cy="31" rx="6" ry="4" fill="rgba(255,255,255,0.1)" />
    </svg>
  )

  if (style === 'trucker') return (
    <svg viewBox="0 0 200 130" fill="none" className="w-full h-full">
      <ellipse cx="100" cy="85" rx="72" ry="14" fill={shadow} />
      <path d="M35 82 Q28 35 100 28 Q136 28 138 82 Z" fill={fill} />
      <path d="M138 32 Q172 42 168 82 L138 82 Z" fill={fill} opacity="0.28" />
      {[38,45,52,59,66].map(y => (
        <line key={y} x1="142" y1={y} x2="166" y2={y+3} stroke="rgba(255,255,255,0.12)" strokeWidth="1.5" strokeDasharray="3 2" />
      ))}
      <rect x="22" y="80" width="112" height="13" rx="4" fill={fill} />
      <ellipse cx="100" cy="29" rx="6" ry="4" fill="rgba(255,255,255,0.1)" />
    </svg>
  )

  if (style === 'bucket') return (
    <svg viewBox="0 0 200 130" fill="none" className="w-full h-full">
      <ellipse cx="100" cy="88" rx="80" ry="12" fill={shadow} />
      <path d="M55 80 Q50 30 100 25 Q150 30 145 80 Z" fill={fill} />
      <ellipse cx="100" cy="80" rx="45" ry="8" fill={fill} />
      <ellipse cx="100" cy="80" rx="72" ry="12" fill={fill} stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
      <ellipse cx="100" cy="27" rx="8" ry="5" fill="rgba(255,255,255,0.08)" />
    </svg>
  )

  if (style === 'beanie') return (
    <svg viewBox="0 0 200 130" fill="none" className="w-full h-full">
      <ellipse cx="100" cy="95" rx="60" ry="10" fill={shadow} />
      <path d="M42 90 Q38 25 100 20 Q162 25 158 90 Z" fill={fill} />
      <rect x="38" y="85" width="124" height="16" rx="4" fill={fill} opacity="0.75" />
      <line x1="38" y1="85" x2="162" y2="85" stroke="rgba(255,255,255,0.1)" strokeWidth="1.5" />
      <ellipse cx="100" cy="22" rx="7" ry="5" fill="rgba(255,255,255,0.15)" />
    </svg>
  )

  if (style === 'visor') return (
    <svg viewBox="0 0 200 130" fill="none" className="w-full h-full">
      <ellipse cx="100" cy="80" rx="72" ry="12" fill={shadow} />
      <path d="M35 68 Q38 52 100 50 Q162 52 165 68 L160 78 Q100 88 40 78 Z" fill={fill} />
      <path d="M40 78 Q100 70 160 78 L162 88 Q100 98 38 88 Z" fill={fill} opacity="0.7" />
      <ellipse cx="100" cy="52" rx="58" ry="6" fill="rgba(255,255,255,0.06)" />
    </svg>
  )

  return null
}
