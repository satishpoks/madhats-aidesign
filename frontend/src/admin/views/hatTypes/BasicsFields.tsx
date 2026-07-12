export interface BasicsValue {
  name: string
  style: string
  description: string
}

interface Props {
  value: BasicsValue
  onChange: (next: BasicsValue) => void
}

export function BasicsFields({ value, onChange }: Props) {
  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium">
        Name
        <input
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
          className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </label>
      <label className="block text-sm font-medium">
        Style <span className="font-normal text-gray-400">(e.g. trucker, dad cap)</span>
        <input
          value={value.style}
          onChange={(e) => onChange({ ...value, style: e.target.value })}
          className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </label>
      <label className="block text-sm font-medium">
        Description <span className="font-normal text-gray-400">(internal note)</span>
        <textarea
          value={value.description}
          onChange={(e) => onChange({ ...value, description: e.target.value })}
          rows={2}
          className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </label>
    </div>
  )
}
