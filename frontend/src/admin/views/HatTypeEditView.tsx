import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { listHatTypes, updateHatType, type HatType } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores, allAngles } from './hatTypes/shared'
import { BasicsFields, type BasicsValue } from './hatTypes/BasicsFields'
import { AngleUploader } from './hatTypes/AngleUploader'
import { ColourwayEditor } from './hatTypes/ColourwayEditor'
import { ChipListEditor } from './hatTypes/ChipListEditor'

const ZONE_SUGGESTIONS = ['Front panel', 'Left side', 'Right side', 'Back', 'Under-brim']
const DECORATION_SUGGESTIONS = ['Embroidery', 'Print', 'Patch']

const sectionCls = 'rounded-lg border border-gray-200 bg-white p-5 space-y-4'
const primary = 'rounded-lg bg-[#ff5c00] px-4 py-2 text-sm text-white hover:bg-[#e64f00] disabled:opacity-50'

export function HatTypeEditView() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const { stores, loading: storesLoading } = useStores()
  const storeKey = stores.find((s) => s.id === storeId)?.public_key ?? null

  const [hat, setHat] = useState<HatType | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)

  const [basics, setBasics] = useState<BasicsValue>({ name: '', style: '', description: '' })
  const [colours, setColours] = useState<{ name: string; hex: string }[]>([])
  const [zones, setZones] = useState<string[]>([])
  const [decoration, setDecoration] = useState<string[]>([])

  useEffect(() => {
    if (!storeKey || !id) return
    listHatTypes(storeKey)
      .then((rows) => {
        const found = rows.find((r) => r.id === id) ?? null
        setHat(found)
        if (found) {
          setBasics({ name: found.name, style: found.style ?? '', description: found.description ?? '' })
          setColours(found.colours ?? [])
          setZones(found.placement_zones ?? [])
          setDecoration(found.decoration_types ?? [])
        } else {
          setError('Hat type not found')
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load hat type'))
  }, [storeKey, id])

  async function save(section: string, patch: Partial<HatType>) {
    if (!storeKey || !hat) return
    setSaving(section)
    setError(null)
    try {
      const updated = await updateHatType(hat.id, patch, storeKey)
      // Backend PATCH response does not include view_images (defaults to {})
      // — preserve the locally-known angle state so uploaded thumbnails
      // survive a section save (including the Active toggle, which also
      // goes through this function).
      setHat({ ...updated, view_images: hat.view_images, blank_view_images: hat.blank_view_images })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(null)
    }
  }

  if (!hat) {
    return (
      <div className="space-y-4">
        {error && <ErrorBanner message={error} />}
        {!error && !storesLoading && !storeKey && (
          <>
            <ErrorBanner message="Unknown or missing store — open this from the Hat Types list." />
            <Link to="/admin/hat-types" className="text-sm text-[#ff5c00] hover:underline">
              ← Back to Hat Types
            </Link>
          </>
        )}
        {!error && (storesLoading || storeKey) && <p className="text-sm text-gray-500">Loading…</p>}
      </div>
    )
  }

  const canActivate = allAngles(hat)

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Edit: {hat.name}</h1>
        <Link to={`/admin/hat-types?store=${storeId}`} className="text-sm text-[#ff5c00] hover:underline">
          ← Back to list
        </Link>
      </div>
      {error && <ErrorBanner message={error} />}

      <section className={sectionCls}>
        <h2 className="font-medium">Basics</h2>
        <BasicsFields value={basics} onChange={setBasics} />
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={hat.active}
              disabled={!canActivate}
              onChange={(e) => save('active', { active: e.target.checked })}
            />
            Active {!canActivate && <span className="text-xs text-gray-400">(needs all 4 angles)</span>}
          </label>
          <button
            className={primary}
            disabled={saving === 'basics'}
            onClick={() => save('basics', { name: basics.name, style: basics.style, description: basics.description })}
          >
            {saving === 'basics' ? 'Saving…' : 'Save basics'}
          </button>
        </div>
      </section>

      <section className={sectionCls}>
        <h2 className="font-medium">Angle images</h2>
        <AngleUploader
          hatId={hat.id}
          storeKey={storeKey!}
          viewImages={hat.view_images}
          onUploaded={(view, url) =>
            setHat({
              ...hat,
              view_images: { ...hat.view_images, [view]: url },
              blank_view_images: { ...hat.blank_view_images, [view]: url },
            })
          }
        />
      </section>

      <section className={sectionCls}>
        <h2 className="font-medium">Colourways</h2>
        <ColourwayEditor value={colours} onChange={setColours} />
        <div className="flex justify-end">
          <button className={primary} disabled={saving === 'colours'} onClick={() => save('colours', { colours })}>
            {saving === 'colours' ? 'Saving…' : 'Save colourways'}
          </button>
        </div>
      </section>

      <section className={sectionCls}>
        <h2 className="font-medium">Zones &amp; decoration</h2>
        <ChipListEditor label="Placement zones" value={zones} onChange={setZones} suggestions={ZONE_SUGGESTIONS} />
        <ChipListEditor label="Decoration types" value={decoration} onChange={setDecoration} suggestions={DECORATION_SUGGESTIONS} />
        <div className="flex justify-end">
          <button
            className={primary}
            disabled={saving === 'zones'}
            onClick={() => save('zones', { placement_zones: zones, decoration_types: decoration })}
          >
            {saving === 'zones' ? 'Saving…' : 'Save zones & decoration'}
          </button>
        </div>
      </section>
    </div>
  )
}
