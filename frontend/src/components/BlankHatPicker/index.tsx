import { useEffect, useState } from 'react'
import { listHatTypes, type HatColour, type HatType } from '../../lib/api'
import { useSessionStore } from '../../store/sessionStore'

export function BlankHatPicker() {
  const [hats, setHats] = useState<HatType[]>([])
  const [selected, setSelected] = useState<HatType | null>(null)
  const [selectedColour, setSelectedColour] = useState<HatColour | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const startCanvasBlankSession = useSessionStore(s => s.startCanvasBlankSession)

  // Selecting a hat resets the colour choice to that hat's first colourway (if any).
  function handleSelectHat(hat: HatType) {
    setSelected(hat)
    setSelectedColour(hat.colours?.[0] ?? null)
    setStartError(null)
  }

  useEffect(() => {
    setLoading(true)
    listHatTypes()
      .then(result => {
        setHats(result)
        setLoading(false)
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load hats')
        setLoading(false)
      })
  }, [])

  async function handleStart() {
    if (!selected) return
    setStartError(null)
    setStarting(true)
    try {
      await startCanvasBlankSession(selected, selectedColour ?? undefined)
    } catch (err) {
      setStartError(err instanceof Error ? err.message : 'Something went wrong starting your design. Please try again.')
    } finally {
      setStarting(false)
    }
  }

  if (loading) {
    return <div className="p-8 text-center text-gray-500">Loading hats…</div>
  }

  if (error) {
    return <div className="p-8 text-center text-gray-500">{error}</div>
  }

  if (hats.length === 0) {
    return <div className="p-8 text-center text-gray-500">No blank hats available yet.</div>
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold mb-4">Design your hat from scratch</h1>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {hats.map(h => (
          <button key={h.id} onClick={() => handleSelectHat(h)}
            className={`border rounded-lg p-3 ${selected?.id === h.id ? 'ring-2 ring-orange-500' : ''}`}>
            {h.view_images.front && <img src={h.view_images.front} alt={h.name} className="w-full h-32 object-contain" />}
            <div className="mt-2 text-sm font-medium">{h.name}</div>
          </button>
        ))}
      </div>

      {selected && (
        <div className="mt-6">
          {selected.colours && selected.colours.length > 0 ? (
            <div className="mb-4">
              <p className="text-sm font-medium text-gray-700 mb-2">
                Choose a colour{selectedColour ? `: ${selectedColour.name}` : ''}
              </p>
              <div className="flex flex-wrap gap-2">
                {selected.colours.map(c => (
                  <button
                    key={c.name}
                    type="button"
                    title={c.name}
                    aria-label={c.name}
                    aria-pressed={selectedColour?.name === c.name}
                    onClick={() => setSelectedColour(c)}
                    style={{ backgroundColor: c.hex }}
                    className={`w-9 h-9 rounded-full border transition-all ${
                      selectedColour?.name === c.name
                        ? 'ring-2 ring-offset-2 ring-orange-500 border-transparent'
                        : 'border-gray-300 hover:border-gray-500'
                    }`}
                  />
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500 mb-3">
              You'll pick the colour and everything else on the design canvas.
            </p>
          )}
          {startError && <div className="text-sm text-red-500 mb-2">{startError}</div>}
          <button onClick={() => void handleStart()} disabled={starting}
            className="bg-orange-500 text-white font-semibold px-5 py-2.5 rounded-lg disabled:opacity-50">
            {starting ? 'Starting…' : 'Start designing'}
          </button>
        </div>
      )}
    </div>
  )
}
