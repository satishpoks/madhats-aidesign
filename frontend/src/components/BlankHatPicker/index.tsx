import { useEffect, useState } from 'react'
import { listHatTypes, type HatType, type HatColour } from '../../lib/api'
import { useSessionStore } from '../../store/sessionStore'

export function BlankHatPicker() {
  const [hats, setHats] = useState<HatType[]>([])
  const [selected, setSelected] = useState<HatType | null>(null)
  const [colour, setColour] = useState<HatColour>({ name: 'Custom', hex: '#1a2b5c' })
  const startBlankSession = useSessionStore(s => s.startBlankSession)

  useEffect(() => { void listHatTypes().then(setHats).catch(() => setHats([])) }, [])

  if (hats.length === 0) {
    return <div className="p-8 text-center text-gray-500">No blank hats available yet.</div>
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold mb-4">Design your hat from scratch</h1>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {hats.map(h => (
          <button key={h.id} onClick={() => setSelected(h)}
            className={`border rounded-lg p-3 ${selected?.id === h.id ? 'ring-2 ring-orange-500' : ''}`}>
            {h.view_images.front && <img src={h.view_images.front} alt={h.name} className="w-full h-32 object-contain" />}
            <div className="mt-2 text-sm font-medium">{h.name}</div>
          </button>
        ))}
      </div>

      {selected && (
        <div className="mt-6">
          <label className="block text-sm font-medium mb-2">Hat colour</label>
          <div className="flex items-center gap-3 mb-3">
            <input type="color" value={colour.hex}
              onChange={e => setColour({ name: e.target.value, hex: e.target.value })} />
            <div className="flex gap-2">
              {selected.colours.map(c => (
                <button key={c.hex} title={c.name} onClick={() => setColour(c)}
                  className="w-7 h-7 rounded-full border" style={{ background: c.hex }} />
              ))}
            </div>
          </div>
          <button onClick={() => startBlankSession(selected.id, colour)}
            className="bg-orange-500 text-white font-semibold px-5 py-2.5 rounded-lg">
            Start designing
          </button>
        </div>
      )}
    </div>
  )
}
