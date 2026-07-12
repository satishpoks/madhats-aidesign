interface Colour {
  name: string
  hex: string
}

interface Props {
  value: Colour[]
  onChange: (next: Colour[]) => void
}

export function ColourwayEditor({ value, onChange }: Props) {
  function patch(i: number, next: Partial<Colour>) {
    onChange(value.map((c, idx) => (idx === i ? { ...c, ...next } : c)))
  }
  function remove(i: number) {
    onChange(value.filter((_, idx) => idx !== i))
  }
  function add() {
    onChange([...value, { name: '', hex: '#000000' }])
  }

  return (
    <div className="space-y-2">
      {value.map((c, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            type="color"
            aria-label={`Colour ${i + 1} swatch`}
            value={c.hex}
            onChange={(e) => patch(i, { hex: e.target.value })}
            className="h-8 w-8 rounded border border-gray-300"
          />
          <input
            aria-label={`Colour ${i + 1} name`}
            value={c.name}
            placeholder="e.g. Black"
            onChange={(e) => patch(i, { name: e.target.value })}
            className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
          />
          <button
            type="button"
            aria-label={`Remove colour ${i + 1}`}
            onClick={() => remove(i)}
            className="rounded px-2 py-1 text-sm text-gray-400 hover:text-red-500"
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="rounded-lg border border-dashed border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:border-[#ff5c00] hover:text-[#ff5c00]"
      >
        + Add colour
      </button>
    </div>
  )
}
