import { useEffect, useState } from 'react'
import { listHatTypes, type HatType } from '../../lib/api'
import { useSessionStore } from '../../store/sessionStore'

export function BlankHatPicker() {
  const [hats, setHats] = useState<HatType[]>([])
  const [selected, setSelected] = useState<HatType | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const startBlankSession = useSessionStore(s => s.startBlankSession)

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
      await startBlankSession(selected)
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
          <button key={h.id} onClick={() => setSelected(h)}
            className={`border rounded-lg p-3 ${selected?.id === h.id ? 'ring-2 ring-orange-500' : ''}`}>
            {h.view_images.front && <img src={h.view_images.front} alt={h.name} className="w-full h-32 object-contain" />}
            <div className="mt-2 text-sm font-medium">{h.name}</div>
          </button>
        ))}
      </div>

      {selected && (
        <div className="mt-6">
          <p className="text-sm text-gray-500 mb-3">
            You'll choose the colour and everything else as you design with Ricardo.
          </p>
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
