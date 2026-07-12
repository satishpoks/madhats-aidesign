import { useState } from 'react'
import { uploadHatAngle } from '../../adminApi'
import { VIEWS } from './shared'

interface Props {
  hatId: string
  storeKey: string
  viewImages: Record<string, string>
  onUploaded: (view: string, url: string) => void
}

export function AngleUploader({ hatId, storeKey, viewImages, onUploaded }: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handle(view: string, file: File) {
    setBusy(view)
    setError(null)
    try {
      const res = await uploadHatAngle(hatId, view, file, storeKey)
      const url = res.view_images[view]
      if (url) {
        onUploaded(view, url)
      } else {
        setError('Upload succeeded but no image URL was returned')
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {VIEWS.map((v) => (
          <div key={v} className="rounded-lg border border-gray-200 p-2 text-center">
            <div className="mb-1 text-xs font-medium uppercase text-gray-500">
              {v} {viewImages[v] && <span className="text-green-600">✓</span>}
            </div>
            <div className="flex h-24 items-center justify-center overflow-hidden rounded bg-gray-50">
              {viewImages[v] ? (
                <img src={viewImages[v]} alt={v} className="max-h-24 object-contain" />
              ) : (
                <span className="text-2xl text-gray-300">＋</span>
              )}
            </div>
            <label className="mt-2 block cursor-pointer text-xs text-[#ff5c00] hover:underline">
              {busy === v ? 'Uploading…' : viewImages[v] ? 'Replace' : 'Upload'}
              <input
                type="file"
                accept="image/*"
                aria-label={`Upload ${v}`}
                className="hidden"
                onChange={(e) => e.target.files?.[0] && handle(v, e.target.files[0])}
              />
            </label>
          </div>
        ))}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  )
}
