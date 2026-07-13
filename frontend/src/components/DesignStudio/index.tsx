import { useEffect, useRef, useState } from 'react'
import type Konva from 'konva'
import { useSessionStore } from '../../store/sessionStore'
import { useCanvasStore, FACES, type Face } from '../../store/canvasStore'
import { useChatStore } from '../../store/chatStore'
import { CanvasStage } from './CanvasStage'
import { ToolRail } from './ToolRail'
import { SelectedToolbar } from './SelectedToolbar'
import { FaceThumbnails } from './FaceThumbnails'
import { GraphicsPicker } from './GraphicsPicker'
import { Modal } from '../Modal'
import { flattenStage, dataUrlToFile } from '../../lib/canvasFlatten'
import { uploadLogo, uploadCanvasLayouts, finalizeCanvas } from '../../lib/api'
import { loadImage } from '../../lib/imageCache'

export function DesignStudio() {
  const sessionId = useSessionStore(s => s.sessionId)
  const productRef = useSessionStore(s => s.productRef)
  const setView = useSessionStore.setState

  const setActiveFace = useCanvasStore(s => s.setActiveFace)
  const faceImages = useCanvasStore(s => s.faceImages)
  const addText = useCanvasStore(s => s.addText)
  const addImage = useCanvasStore(s => s.addImage)
  const addShape = useCanvasStore(s => s.addShape)
  const setFaceImages = useCanvasStore(s => s.setFaceImages)
  const toCanvasDesign = useCanvasStore(s => s.toCanvasDesign)

  const stageRef = useRef<Konva.Stage>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [rendering, setRendering] = useState(false)
  const [emailOpen, setEmailOpen] = useState(false)
  const [graphicsOpen, setGraphicsOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Seed the four face backgrounds from the product reference.
  useEffect(() => {
    if (productRef) {
      const v = productRef.view_images || {}
      setFaceImages({
        front: v.front || productRef.reference_image_url,
        back: v.back || '', left: v.left || '', right: v.right || '',
      })
    }
  }, [productRef, setFaceImages])

  const colourways = useSessionStore(s => s.blankColourways)

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !sessionId) return
    try {
      const { asset_url } = await uploadLogo(sessionId, file)
      // Read the image's natural aspect so it inserts undistorted (preserved
      // until the user resizes it themselves). Fall back to square if it can't load.
      let aspect = 1
      try {
        const img = await loadImage(asset_url)
        if (img.naturalWidth && img.naturalHeight) aspect = img.naturalWidth / img.naturalHeight
      } catch { /* keep square default */ }
      addImage(asset_url, aspect)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    }
    // Allow re-selecting the same file later (onChange won't fire otherwise).
    e.target.value = ''
  }

  // Add a library graphic (clipart / company) to the canvas — same image-element
  // flow as an upload, reading its natural aspect so it inserts undistorted.
  async function addGraphic(url: string) {
    let aspect = 1
    try {
      const img = await loadImage(url)
      if (img.naturalWidth && img.naturalHeight) aspect = img.naturalWidth / img.naturalHeight
    } catch { /* keep square default */ }
    addImage(url, aspect)
  }

  async function doRender() {
    if (!sessionId) return
    setRendering(true); setError(null)
    try {
      // Flatten the CURRENT active face, then each other decorated face. Konva
      // renders one stage; switch faces, let it paint, flatten. Simplest: flatten
      // the active face now; for other decorated faces, re-render via activeFace.
      const design = toCanvasDesign()

      // Preload every background + element image the decorated faces need
      // into the shared cache BEFORE switching faces. CanvasStage/ImageNode
      // both read the cache synchronously, so once an image is cached
      // `.complete`, switching activeFace paints it immediately — no async
      // gap for the rAF wait below to race against.
      const urls = new Set<string>()
      for (const face of FACES as Face[]) {
        if (design.faces[face].length === 0) continue
        if (faceImages[face]) urls.add(faceImages[face])
        for (const el of design.faces[face]) {
          if (el.type === 'image' && el.assetUrl) urls.add(el.assetUrl)
        }
      }
      await Promise.all([...urls].map(loadImage))
      // Ensure any Google/web fonts used are loaded before we rasterise, so the
      // flattened PNG shows the real typeface, not a fallback.
      try { await document.fonts?.ready } catch { /* best-effort */ }

      const layouts: { face: string; file: File }[] = []
      for (const face of FACES as Face[]) {
        if (design.faces[face].length === 0) continue
        setActiveFace(face)
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))
        const stage = stageRef.current
        if (!stage) continue
        const url = flattenStage(stage)
        layouts.push({ face, file: dataUrlToFile(url, `${face}.png`) })
      }
      if (layouts.length) await uploadCanvasLayouts(sessionId, layouts)
      const res = await finalizeCanvas(sessionId, { canvas_design: design, email: email || undefined })
      // Hand off to the existing ChatPanel for verify -> deliver -> refine.
      useChatStore.getState().hydrate([], res.state, res.data)
      setView({ view: 'session' })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
      setRendering(false)
    }
  }

  function onRenderClick() {
    if (email) void doRender()
    else setEmailOpen(true)
  }

  return (
    <div className="h-screen bg-base flex flex-col">
      <header className="bg-surface border-b border-border px-6 py-3.5 flex items-center gap-3">
        <span className="text-accent font-extrabold text-lg tracking-wide">MAD HATS</span>
        {productRef && <span className="text-sm text-textMuted truncate">{productRef.name} › Design</span>}
      </header>

      {error && <div role="alert" className="mx-6 mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}

      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        {/* Left rail — face-thumbnail navigator */}
        <div className="md:border-r border-border overflow-y-auto flex-shrink-0">
          <FaceThumbnails />
        </div>

        {/* Centre — canvas + contextual toolbar */}
        <div className="flex-1 flex flex-col items-center gap-3 p-4 overflow-auto">
          <CanvasStage stageRef={stageRef} />
          <SelectedToolbar />
        </div>

        {/* Right rail — tools + render */}
        <div className="md:border-l border-border overflow-y-auto flex-shrink-0">
          <ToolRail onAddText={() => addText('Your text')} onUploadClick={() => fileRef.current?.click()}
            onGraphicsClick={() => setGraphicsOpen(true)}
            colourways={colourways} onRender={onRenderClick} rendering={rendering} />
        </div>
      </div>

      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={handleUpload} className="sr-only" aria-label="Upload image" />

      <GraphicsPicker open={graphicsOpen} onClose={() => setGraphicsOpen(false)}
        onPickShape={kind => addShape(kind)} onPickImage={url => void addGraphic(url)} />

      <Modal open={emailOpen} title="Where should we send it?" onClose={() => setEmailOpen(false)}>
        <div className="flex flex-col gap-3 p-2">
          <p className="text-sm text-textSub">Pop in your email — it saves your progress and we'll send your rendered design there.</p>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com"
            className="bg-base border border-border rounded-xl px-3 py-2 text-sm" />
          <button onClick={() => { setEmailOpen(false); void doRender() }} disabled={!email.includes('@')}
            className="px-4 py-2 bg-accent text-white rounded-full text-sm font-semibold disabled:opacity-50">
            See it rendered
          </button>
        </div>
      </Modal>
    </div>
  )
}
