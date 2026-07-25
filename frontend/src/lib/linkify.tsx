import type { ReactNode } from 'react'

const URL_RE = /(https?:\/\/[^\s]+)/g

/**
 * Split text into plain strings and clickable <a> nodes for any http(s) URL.
 * Chat bubbles render assistant text as plain (whitespace-pre-wrap) — this makes
 * URLs (e.g. the colour reference links) clickable. Trailing sentence
 * punctuation is kept out of the href.
 */
export function linkify(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let key = 0
  let m: RegExpExecArray | null
  URL_RE.lastIndex = 0
  while ((m = URL_RE.exec(text)) !== null) {
    let url = m[0]
    const trail = url.match(/[.,;:!?)]+$/)
    const tail = trail ? trail[0] : ''
    if (tail) url = url.slice(0, -tail.length)
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(
      <a key={key++} href={url} target="_blank" rel="noopener noreferrer"
         className="underline break-all">{url}</a>,
    )
    if (tail) out.push(tail)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}
