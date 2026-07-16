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
import { flattenStage, flattenFull, dataUrlToFile } from '../../lib/canvasFlatten'
import { uploadLogo, uploadCanvasLayouts, finalizeCanvas } from '../../lib/api'
import { loadImage } from '../../lib/imageCache'

export function DesignStudioSurface() {
  const sessionId = useSessionStore(s => s.sessionId)
  const productRef = useSessionStore(s => s.productRef)

  const chatState = useChatStore(s => s.chatState)
  const unlocked = chatState === 'canvas_design'
  // Intro states (pre-design) vs outro/other (post-design). Empty string is the
  // pre-kickoff instant → treat as intro.
  const introStates = ['', 'greeting', 'ask_name', 'save_progress_email', 'ask_purpose', 'ask_quantity']
  const isIntro = introStates.includes(chatState)

  const canvasDirective = useChatStore(s => s.canvasDirective)
  const triggerFinalize = useChatStore(s => s.triggerFinalize)

  // v2 = a canvas directive is present (the chat orchestrator is driving the
  // canvas turn-by-turn). Fall back to the legacy whole-rail gating
  // (chatState === 'canvas_design') when there is no directive (v1).
  const isV2 = canvasDirective !== null
  const allowedTools = isV2 ? new Set(canvasDirective!.allowedTools as ('upload' | 'text' | 'shape')[]) : undefined
  const highlightTool = isV2 && canvasDirective!.allowedTools.length === 1
    ? (canvasDirective!.allowedTools[0] as 'upload' | 'text' | 'shape')
    : null

  const setActiveFace = useCanvasStore(s => s.setActiveFace)
  const faceImages = useCanvasStore(s => s.faceImages)
  const addText = useCanvasStore(s => s.addText)
  const addImage = useCanvasStore(s => s.addImage)
  const addShape = useCanvasStore(s => s.addShape)
  const setFaceImages = useCanvasStore(s => s.setFaceImages)
  const toCanvasDesign = useCanvasStore(s => s.toCanvasDesign)
  const lockAll = useCanvasStore(s => s.lockAll)

  const stageRef = useRef<Konva.Stage>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [rendering, setRendering] = useState(false)
  const [rendered, setRendered] = useState(false)
  const [graphicsOpen, setGraphicsOpen] = useState(false)
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

  // When the canvas (re)unlocks — the intro finishing, or a "Rework on the
  // canvas" refine — clear the local rendered flag so "Done designing" is
  // active again for another pass.
  useEffect(() => {
    if (unlocked) setRendered(false)
  }, [unlocked])

  // v2: switch to the directive's target face as the chat walks through steps.
  useEffect(() => {
    if (canvasDirective?.targetFace) setActiveFace(canvasDirective.targetFace as Face)
  }, [canvasDirective?.targetFace, setActiveFace])

  // v2: auto-open the requested tool dialog once per directive change.
  useEffect(() => {
    if (canvasDirective?.autoOpen === 'upload') fileRef.current?.click()
    if (canvasDirective?.autoOpen === 'shape') setGraphicsOpen(true)
    if (canvasDirective?.autoOpen === 'text') addText('Your text')
  }, [canvasDirective?.autoOpen, addText])

  // v2: when the chat says finalize, lock every placed element (freezing the
  // canvas for the multi-face export loop in doRender) and flatten + finalize
  // exactly like the v1 render. Guard so a re-render never double-fires.
  const finalizeStarted = useRef(false)
  useEffect(() => {
    if (triggerFinalize && !finalizeStarted.current) {
      finalizeStarted.current = true
      lockAll()
      void doRender()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triggerFinalize])

  function postDone() {
    const sid = useSessionStore.getState().sessionId
    if (sid) void useChatStore.getState().sendMessage(sid, 'done')
  }

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
    if (!sessionId || rendering) return
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
      // Full WYSIWYG exports (cap + colour + decorations) — the customer's own
      // "your design" images, emailed alongside the photorealistic render.
      const previews: { face: string; file: File }[] = []
      for (const face of FACES as Face[]) {
        if (design.faces[face].length === 0) continue
        setActiveFace(face)
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))
        const stage = stageRef.current
        if (!stage) continue
        // Full export FIRST (nothing hidden), then the decorations-only guide.
        previews.push({ face, file: dataUrlToFile(flattenFull(stage), `${face}-preview.png`) })
        layouts.push({ face, file: dataUrlToFile(flattenStage(stage), `${face}.png`) })
      }
      if (layouts.length) await uploadCanvasLayouts(sessionId, layouts, 'layout')
      if (previews.length) await uploadCanvasLayouts(sessionId, previews, 'preview')
      const res = await finalizeCanvas(sessionId, { canvas_design: design })
      // Chat lives in the right panel of this same screen — append the reply
      // in place; do NOT navigate away (that was the old full-screen ChatPanel
      // handoff) and do NOT wipe the intro Q&A thread (hydrate([]) would).
      useChatStore.getState().applyResponse(res.reply, res.state, res.data)
      setRendered(true); setRendering(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
      setRendering(false)
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {error && (
        <div role="alert" className="mx-4 mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Slim, non-blocking status strip — replaces the old full-panel blur.
          The canvas stays fully visible; when locked the tools are simply
          disabled (ToolRail/CanvasStage `locked`) so nothing can be modified.
          v1 only — v2 sessions show the directive instruction callout instead. */}
      {!isV2 && !unlocked && (
        <div className="mx-4 mt-3 rounded-lg border border-border bg-surfaceAlt/60 px-4 py-2 text-center text-xs text-textMuted">
          {isIntro
            ? 'Answer the questions on the right to unlock your design tools →'
            : 'Design locked in — finishing up in the chat ✓'}
        </div>
      )}

      {/* v2: the chat orchestrator's current instruction for this turn. */}
      {canvasDirective?.instructions && (
        <div className="mx-4 mt-3 rounded-lg border border-accent/40 bg-accent/5 px-4 py-2 text-sm text-textPrimary">
          {canvasDirective.instructions}
        </div>
      )}

      <div className="relative flex-1 flex flex-col md:flex-row min-h-0">
        {/* Left rail — face-thumbnail navigator */}
        <div className="md:border-r border-border overflow-y-auto flex-shrink-0">
          <FaceThumbnails />
        </div>

        {/* Centre — canvas + contextual toolbar */}
        <div className="flex-1 flex flex-col items-center gap-3 p-4 overflow-auto min-w-0">
          <CanvasStage stageRef={stageRef} locked={isV2 ? false : !unlocked} />
          {/* v2 also mounts the toolbar: its instruction copy tells the customer
              to change font/size/colour "in the toolbar under the cap". It
              no-ops (returns null) until an element is selected, so it only
              surfaces once they pick a placed element — exactly when needed. */}
          {(unlocked || isV2) && <SelectedToolbar />}
          {canvasDirective?.showDone && (
            <button onClick={postDone}
              className="px-6 py-2 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold">
              Done
            </button>
          )}
        </div>

        {/* Right rail — tools + render */}
        <div className="md:border-l border-border overflow-y-auto flex-shrink-0">
          <ToolRail onAddText={() => addText('Your text')} onUploadClick={() => fileRef.current?.click()}
            onGraphicsClick={() => setGraphicsOpen(true)}
            colourways={colourways} onRender={() => void doRender()} rendering={rendering}
            // v2: finalize is chat-driven (`triggerFinalize`), not a manual click —
            // force this legacy render button inert ("Design saved ✓", disabled)
            // so it can't be used to jump ahead of the directive walkthrough.
            rendered={isV2 ? true : rendered}
            locked={isV2 ? false : !unlocked}
            allowedTools={allowedTools} highlightTool={highlightTool} />
        </div>
      </div>

      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={handleUpload} className="sr-only" aria-label="Upload image" />

      <GraphicsPicker open={graphicsOpen} onClose={() => setGraphicsOpen(false)}
        onPickShape={kind => addShape(kind)} onPickImage={url => void addGraphic(url)} />
    </div>
  )
}
