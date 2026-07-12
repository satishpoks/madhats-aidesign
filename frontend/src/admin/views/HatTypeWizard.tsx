import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { createHatType, updateHatType, type HatType } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores, slugify, allAngles } from './hatTypes/shared'
import { BasicsFields, type BasicsValue } from './hatTypes/BasicsFields'
import { AngleUploader } from './hatTypes/AngleUploader'
import { ColourwayEditor } from './hatTypes/ColourwayEditor'
import { ChipListEditor } from './hatTypes/ChipListEditor'

const ZONE_SUGGESTIONS = ['Front panel', 'Left side', 'Right side', 'Back', 'Under-brim']
const DECORATION_SUGGESTIONS = ['Embroidery', 'Print', 'Patch']
const TOTAL_STEPS = 5

export function HatTypeWizard() {
  const { stores } = useStores()
  const [params] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const storeKey = stores.find((s) => s.id === storeId)?.public_key ?? null
  const navigate = useNavigate()

  const [step, setStep] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [basics, setBasics] = useState<BasicsValue>({ name: '', style: '', description: '' })
  const [hat, setHat] = useState<HatType | null>(null)
  const [colours, setColours] = useState<{ name: string; hex: string }[]>([])
  const [zones, setZones] = useState<string[]>([])
  const [decoration, setDecoration] = useState<string[]>([])

  const canActivate = useMemo(() => (hat ? allAngles(hat) : false), [hat])

  function fail(e: unknown, fallback: string) {
    setError(e instanceof Error ? e.message : fallback)
  }

  async function leaveBasics() {
    if (!storeKey || !basics.name.trim()) {
      setError('Please enter a name.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (hat) {
        const updated = await updateHatType(
          hat.id,
          { name: basics.name, style: basics.style, description: basics.description },
          storeKey,
        )
        // PATCH response does not include view_images (defaults to {}) and may
        // re-carry blank_view_images paths — preserve the locally-known angle
        // state so uploaded thumbnails survive the round-trip.
        setHat({ ...updated, view_images: hat.view_images, blank_view_images: hat.blank_view_images })
      } else {
        const created = await createHatType(
          { name: basics.name, slug: slugify(basics.name), style: basics.style, description: basics.description },
          storeKey,
        )
        setHat(created)
        setColours(created.colours ?? [])
        setZones(created.placement_zones ?? [])
        setDecoration(created.decoration_types ?? [])
      }
      setStep(2)
    } catch (e: unknown) {
      fail(e, 'Could not save hat type')
    } finally {
      setBusy(false)
    }
  }

  async function saveColours() {
    if (!storeKey || !hat) return
    setBusy(true)
    setError(null)
    try {
      await updateHatType(hat.id, { colours }, storeKey)
      setStep(4)
    } catch (e: unknown) {
      fail(e, 'Could not save colours')
    } finally {
      setBusy(false)
    }
  }

  async function saveZones() {
    if (!storeKey || !hat) return
    setBusy(true)
    setError(null)
    try {
      await updateHatType(hat.id, { placement_zones: zones, decoration_types: decoration }, storeKey)
      setStep(5)
    } catch (e: unknown) {
      fail(e, 'Could not save zones')
    } finally {
      setBusy(false)
    }
  }

  async function activate() {
    if (!storeKey || !hat) return
    setBusy(true)
    setError(null)
    try {
      await updateHatType(hat.id, { active: true }, storeKey)
      navigate(`/admin/hat-types?store=${storeId}`)
    } catch (e: unknown) {
      fail(e, 'Could not activate')
    } finally {
      setBusy(false)
    }
  }

  const primary =
    'rounded-lg bg-[#ff5c00] px-4 py-2 text-sm text-white hover:bg-[#e64f00] disabled:opacity-50'
  const secondary = 'rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50'

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-xl font-semibold">New hat type</h1>
      <p className="text-sm text-gray-500">Step {step} of {TOTAL_STEPS}</p>
      {error && <ErrorBanner message={error} />}

      <div className="rounded-lg border border-gray-200 bg-white p-5">
        {step === 1 && (
          <>
            <h2 className="mb-3 font-medium">Basics</h2>
            <BasicsFields value={basics} onChange={setBasics} />
            <div className="mt-5 flex justify-end">
              <button className={primary} disabled={busy} onClick={leaveBasics}>
                {busy ? 'Saving…' : 'Next'}
              </button>
            </div>
          </>
        )}

        {step === 2 && hat && (
          <>
            <h2 className="mb-3 font-medium">Upload the four angles</h2>
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
            <div className="mt-5 flex justify-between">
              <button className={secondary} onClick={() => setStep(1)}>Back</button>
              <button className={primary} disabled={!canActivate} onClick={() => setStep(3)}>Next</button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <h2 className="mb-3 font-medium">Colourways</h2>
            <ColourwayEditor value={colours} onChange={setColours} />
            <div className="mt-5 flex justify-between">
              <button className={secondary} onClick={() => setStep(2)}>Back</button>
              <button className={primary} disabled={busy} onClick={saveColours}>Next</button>
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <h2 className="mb-3 font-medium">Zones &amp; decoration</h2>
            <div className="space-y-4">
              <ChipListEditor label="Placement zones" value={zones} onChange={setZones} suggestions={ZONE_SUGGESTIONS} />
              <ChipListEditor label="Decoration types" value={decoration} onChange={setDecoration} suggestions={DECORATION_SUGGESTIONS} />
            </div>
            <div className="mt-5 flex justify-between">
              <button className={secondary} onClick={() => setStep(3)}>Back</button>
              <button className={primary} disabled={busy} onClick={saveZones}>Next</button>
            </div>
          </>
        )}

        {step === 5 && hat && (
          <>
            <h2 className="mb-3 font-medium">Review &amp; activate</h2>
            <ul className="space-y-1 text-sm text-gray-600">
              <li><strong>{basics.name}</strong> {basics.style && `· ${basics.style}`}</li>
              <li>{colours.length} colourway(s)</li>
              <li>{zones.length} zone(s), {decoration.length} decoration type(s)</li>
              <li>Angles: {canActivate ? 'all four uploaded ✓' : 'incomplete — go back to step 2'}</li>
            </ul>
            <div className="mt-5 flex justify-between">
              <button className={secondary} onClick={() => setStep(4)}>Back</button>
              <button className={primary} disabled={busy || !canActivate} onClick={activate}>
                {busy ? 'Activating…' : 'Activate'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
