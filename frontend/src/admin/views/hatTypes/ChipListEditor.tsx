import { useState } from 'react'

interface Props {
  label: string
  value: string[]
  onChange: (next: string[]) => void
  suggestions?: string[]
  placeholder?: string
}

export function ChipListEditor({ label, value, onChange, suggestions = [], placeholder }: Props) {
  const [draft, setDraft] = useState('')

  function add(raw: string) {
    const item = raw.trim()
    if (!item || value.includes(item)) return
    onChange([...value, item])
  }

  function remove(item: string) {
    onChange(value.filter((v) => v !== item))
  }

  const available = suggestions.filter((s) => !value.includes(s))

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium">
        {label}
        <input
          value={draft}
          placeholder={placeholder ?? 'Type and press Enter'}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add(draft)
              setDraft('')
            }
          }}
          className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </label>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map((item) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 rounded-full bg-[#fff2ea] px-2 py-0.5 text-xs text-[#ff5c00]"
            >
              {item}
              <button
                type="button"
                aria-label={`Remove ${item}`}
                onClick={() => remove(item)}
                className="text-[#ff5c00] hover:text-[#e64f00]"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {available.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {available.map((s) => (
            <button
              key={s}
              type="button"
              aria-label={`Add ${s}`}
              onClick={() => add(s)}
              className="rounded-full border border-dashed border-gray-300 px-2 py-0.5 text-xs text-gray-500 hover:border-[#ff5c00] hover:text-[#ff5c00]"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
