import { useEffect, useRef, useState } from 'react'
import type Konva from 'konva'
import { useSessionStore } from '../../store/sessionStore'
import { useCanvasStore, FACES, type Face, TEXT_PLACEHOLDER } from '../../store/canvasStore'
import { useChatStore } from '../../store/chatStore'
import { useBrandStore } from '../../store/brandStore'
import { CanvasStage } from './CanvasStage'
import { ToolRail } from './ToolRail'
import { SelectedToolbar } from './SelectedToolbar'
import { MobileToolsButton } from './MobileToolsButton'
import { FaceThumbnails } from './FaceThumbnails'
import { GraphicsPicker } from './GraphicsPicker'
import { ReviewDialog, CONFIRM_LABEL, REWORK_LABEL } from './ReviewDialog'
import { Watermark } from './Watermark'
import { flattenStage, flattenFull, dataUrlToFile } from '../../lib/canvasFlatten'
import { uploadLogo, uploadCanvasLayouts, finalizeCanvas } from '../../lib/api'
import { loadImage } from '../../lib/imageCache'
import { useIsDesktop } from '../../lib/useIsDesktop'

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
  // Lifted out of local state so useActiveSurface can see it: a rejected
  // finalize re-opens the canvas, and the focus cue must follow.
  const finalizeFailed = useChatStore(s => s.finalizeFailed)
  // "Design for <Name>" banner — display-only, sourced from the turn's own
  // data (orchestrator_v2._public), never a second fetch and never logged.
  const designerName = useChatStore(s => s.collectedName)
  const watermark = useChatStore(s => s.watermark)
  const watermarkText = useBrandStore(s => s.watermarkText)

  // v2 = a canvas directive is present (the chat orchestrator is driving the
  // canvas turn-by-turn). Fall back to the legacy whole-rail gating
  // (chatState === 'canvas_design') when there is no directive (v1).
  const isV2 = canvasDirective !== null
  const allowedTools = isV2 ? new Set(canvasDirective!.allowedTools as ('upload' | 'text' | 'shape')[]) : undefined
  const highlightTool = isV2 && canvasDirective!.allowedTools.length === 1
    ? (canvasDirective!.allowedTools[0] as 'upload' | 'text' | 'shape')
    : null
  // v2: a step that hands over no tool is a chat question, not an editing step
  // — the stage and the element toolbar must be read-only for it. Previously
  // both were hardcoded open for every v2 turn (`isV2 ? false : !unlocked`),
  // so a placed element stayed draggable through the wrap-up questions.
  // A finalize that FAILED (e.g. the cap-text profanity gate 422s with "please
  // edit that text and try again") must re-open the canvas. At FINALIZE_CANVAS
  // the step declares no tool, so the directive gives `allowedTools: []` — the
  // stage is read-only, the Adjust panel is unmounted and the finalize effect
  // has already locked every element. Without this the customer is told to edit
  // text they physically cannot touch. Cleared when a retry starts.
  const v2Editing = isV2 && (canvasDirective!.allowedTools.length > 0 || finalizeFailed)
  const stageLocked = isV2 ? !v2Editing : !unlocked

  const isDesktop = useIsDesktop()
  const showAdjust = isV2 ? v2Editing : unlocked
  const selectedId = useCanvasStore(s => s.selectedId)
  // The tool rail's controls render only when the canvas is actually editable
  // this turn. Every other v2 step is a chat question, so a column of disabled
  // buttons there reads as broken rather than as "not yet".
  //
  // While an element is SELECTED in v2, the rail shows ONLY the Adjust panel —
  // the default buttons are ADD affordances, and during an adjust step they
  // invite a second element and crowd out the panel the step is actually
  // about. Deselecting brings them straight back.
  //
  // v2 ONLY. In v1 the rail's "Done designing" button is the real submit, and
  // hiding it whenever something is selected would force the customer to
  // deselect before they could finish. v2's submit is the per-step Done button
  // in the centre column, so nothing is lost there.
  const toolsVisible = isV2 ? (v2Editing && !selectedId) : unlocked

  const setActiveFace = useCanvasStore(s => s.setActiveFace)
  const faceImages = useCanvasStore(s => s.faceImages)
  const addText = useCanvasStore(s => s.addText)
  const addImage = useCanvasStore(s => s.addImage)
  const addShape = useCanvasStore(s => s.addShape)
  const setFaceImages = useCanvasStore(s => s.setFaceImages)
  const toCanvasDesign = useCanvasStore(s => s.toCanvasDesign)
  const lockAll = useCanvasStore(s => s.lockAll)
  const lockPlaced = useCanvasStore(s => s.lockPlaced)
  const unlockAll = useCanvasStore(s => s.unlockAll)

  const stageRef = useRef<Konva.Stage>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [rendering, setRendering] = useState(false)
  const [rendered, setRendered] = useState(false)
  const [graphicsOpen, setGraphicsOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Mobile-only tool/adjust visibility — see MobileToolsButton and the close
  // button in SelectedToolbar. Two independent booleans, not one: the rail
  // (nothing selected) and the sheet (something selected) are gated by
  // different questions —
  //  - `mobileToolsOpen` starts CLOSED (owner: "collapsed by default").
  //  - `mobileSheetHidden` starts HIDDEN (owner, 2026-08-03: "do not open the
  //    tool bar by default when element is added — on mobile. only open when
  //    the user taps or clicks the tool bar"). Adding an element auto-selects
  //    it (canvasStore's addText/addImage/addShape/addDrawing all return
  //    `selectedId: el.id`), so a sheet that auto-opened on `selectedId`
  //    changing sprang open the instant a step's tool placed something — the
  //    exact behaviour the owner asked to remove.
  // Deliberately NOT reset on selection change in either direction: the sheet
  // stays exactly as the customer left it (hidden, or open) as they select
  // different elements. It only ever changes via an explicit action — the
  // floating tools button (`toggleMobilePanel`) or the sheet's own close
  // button — matching "only open when the user taps or clicks the tool bar"
  // literally, in both directions, not just the "opening" one: a sheet closed
  // for element A must not spring back open just because the customer then
  // taps element B. This is the less surprising choice — once the customer
  // has explicitly opened the panel to make adjustments, forcing them to
  // reopen it after every single selection change (or, symmetrically,
  // resurrecting a panel they just dismissed) would be far more disruptive
  // than leaving it exactly where they put it.
  const [mobileToolsOpen, setMobileToolsOpen] = useState(false)
  const [mobileSheetHidden, setMobileSheetHidden] = useState(true)
  // The floating button is context-sensitive: while something is selected the
  // relevant panel is the Adjust sheet, otherwise it's the tool rail. This is
  // what makes one button cover both "the tools" and "the adjustment part".
  function toggleMobilePanel() {
    if (selectedId) setMobileSheetHidden(h => !h)
    else setMobileToolsOpen(o => !o)
  }
  const mobilePanelOpen = selectedId ? !mobileSheetHidden : mobileToolsOpen
  // Pulse the button when it has something to reveal and is currently closed
  // — most importantly at REWORK_CANVAS, where every tool unlocks at once but
  // the rail starts collapsed on a phone. Stops the instant it's opened.
  const mobileHasHiddenTools = !selectedId && toolsVisible && !mobileToolsOpen
  const mobileHasHiddenSheet = !!selectedId && showAdjust && mobileSheetHidden
  const mobilePulse = mobileHasHiddenTools || mobileHasHiddenSheet

  const [reviewOpen, setReviewOpen] = useState(false)
  // Open on ARRIVAL at the review, not on every render while there — otherwise
  // dismissing it would immediately re-open. Leaving the state resets the latch.
  const wasReviewing = useRef(false)
  useEffect(() => {
    const reviewing = chatState === 'review_design'
    if (reviewing && !wasReviewing.current) setReviewOpen(true)
    if (!reviewing) setReviewOpen(false)
    wasReviewing.current = reviewing
  }, [chatState])

  function sendReview(label: string) {
    setReviewOpen(false)
    const sid = useSessionStore.getState().sessionId
    if (sid) void useChatStore.getState().sendMessage(sid, label)
  }

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
  // This effect is declared BEFORE the auto-open effect below and React runs
  // a component's passive effects in declaration order within one commit, so
  // `setActiveFace` (synchronous, via the zustand store) is guaranteed to
  // have applied before the auto-open effect reads `activeFace` (e.g.
  // `addImage` appends to whatever face is currently active).
  useEffect(() => {
    if (canvasDirective?.targetFace) setActiveFace(canvasDirective.targetFace as Face)
  }, [canvasDirective?.targetFace, setActiveFace])

  // v2: REWORK_CANVAS reopens a finished (locked) design for editing — unlock
  // every element so it's draggable/selectable again. Distinct from the
  // triggerFinalize-based re-open effect below (that one fires on the refine
  // rework path); this one fires directly off the directive so a review-step
  // "Rework on the canvas" answer unlocks immediately, independent of
  // triggerFinalize's state.
  useEffect(() => {
    if (canvasDirective?.unlockAll) unlockAll()
  }, [canvasDirective?.unlockAll, unlockAll])

  // v2: auto-open the requested tool dialog once per directive change. Also
  // depends on targetFace (not just autoOpen) so it re-evaluates in lockstep
  // with the face-switch effect above whenever the directive changes either
  // field — belt-and-braces on top of the declaration-order guarantee, and
  // documents the ordering dependency between the two effects.
  useEffect(() => {
    if (canvasDirective?.autoOpen === 'upload') fileRef.current?.click()
    if (canvasDirective?.autoOpen === 'shape') setGraphicsOpen(true)
    if (canvasDirective?.autoOpen === 'text') addText(TEXT_PLACEHOLDER)
  }, [canvasDirective?.autoOpen, canvasDirective?.targetFace, addText])

  // v2: lock whatever was just placed as soon as the flow leaves an editing
  // step. This is the SOLE locker — anchoring it to the DIRECTIVE rather than
  // to the Done button is what makes it correct for every way the customer can
  // answer: the canvas Done button, the chat's "Done" chip, or typing "done".
  // The chip calls sendMessage directly and never went through
  // postDone/lockPlaced, so the chat replied "Locked that in" while the logo
  // stayed draggable. postDone must NOT lock as well — see the note there.
  // `v2Editing` (not `showDone`) is the trigger because ASK_LOGO_PLACEMENT
  // hands over the upload tool without a Done button — it's still an editing
  // step. Idempotent: leaving a non-editing step has nothing new to lock.
  useEffect(() => {
    if (isV2 && !v2Editing) lockPlaced()
  }, [isV2, v2Editing, lockPlaced])

  // v2: when the chat says finalize, lock every placed element (freezing the
  // canvas for the multi-face export loop in doRender) and flatten + finalize
  // exactly like the v1 render. Guard so a re-render never double-fires.
  const finalizeStarted = useRef(false)
  useEffect(() => {
    if (!triggerFinalize) {
      // Re-arm: the refine confirm step fires trigger_finalize a SECOND time.
      // Without this the ref stays true from the first finalize and the
      // re-render is silently swallowed.
      finalizeStarted.current = false
      // Rework re-open: the canvas is editable again, but every pre-existing
      // element is still locked:true from the finalize lockAll(). Nothing else
      // ever clears it, so refined designs render non-draggable/non-selectable
      // ("not all layers are unlocked"). Unlock them here.
      //
      // Guarded on "something is actually locked" because this branch also runs
      // on every ordinary mount (deps are [triggerFinalize], which starts
      // false). unlockAll() clears selectedId, so calling it unconditionally
      // deselects the element the customer is editing and unmounts
      // SelectedToolbar with it — which would make the background-removal
      // toggle unreachable at ask_logo_bg. With the guard it is a true no-op
      // until a finalize has actually locked the canvas.
      const locked = FACES.some(f => useCanvasStore.getState().faces[f].some(e => e.locked))
      if (locked) unlockAll()
      return
    }
    if (!finalizeStarted.current) {
      finalizeStarted.current = true
      lockAll()
      void doRender()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triggerFinalize])

  function postDone() {
    // Deliberately does NOT lock: the directive effect above is the single,
    // authoritative locker for every answer path (this button, the chat "Done"
    // chip, typing "done"). Locking here as well was not merely redundant — it
    // was destructive. chatStore.sendMessage reads
    // `useCanvasStore.getState().toCanvasDesign()` SYNCHRONOUSLY on a
    // `logo_adjust` turn, so a lock on the line above would land first and ship
    // an all-locked blob; `canvas_steps.observe_canvas` skips locked images, so
    // a customer's own "Remove background" tick was invisible on exactly the
    // path LOGO_ADJUST's copy points at. (It also locked the element out of
    // selection, putting the manual toggle out of reach, and made
    // `_ops_logo_bg`'s "last unlocked image" canvas op a no-op.)
    const sid = useSessionStore.getState().sessionId
    if (sid) void useChatStore.getState().sendMessage(sid, 'done')
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !sessionId) return
    try {
      const { asset_url, asset_path } = await uploadLogo(sessionId, file)
      // Read the image's natural aspect so it inserts undistorted (preserved
      // until the user resizes it themselves). Fall back to square if it can't load.
      let aspect = 1
      try {
        const img = await loadImage(asset_url)
        if (img.naturalWidth && img.naturalHeight) aspect = img.naturalWidth / img.naturalHeight
      } catch { /* keep square default */ }
      addImage(asset_url, aspect, asset_path)
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
    setRendering(true); setError(null); useChatStore.setState({ finalizeFailed: false })
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
      // A failed finalize must be retryable AND actionable. The gate's own
      // message ("please edit that text and try again") is only followable if
      // the canvas comes back to life: the finalize effect locked every element
      // and FINALIZE_CANVAS's directive hands over no tool, so the stage is
      // read-only and the Adjust panel unmounted. Unlock, drop the finalize
      // trigger, and flag the failure so `v2Editing` re-opens the stage +
      // panel until the customer retries.
      //
      // Re-arming the ref matters on its own too: `triggerFinalize` never
      // changes by itself (it's already true from the chat reaching
      // FINALIZE_CANVAS) so the effect above would never fire doRender() again,
      // and the v2 render button is permanently disabled
      // (`rendered={isV2 ? true : rendered}`) — leaving no way back in.
      useChatStore.setState({ finalizeFailed: true })
      unlockAll()
      useChatStore.setState({ triggerFinalize: false })
      finalizeStarted.current = false
    }
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {error && (
        <div role="alert" className="mx-4 mt-3 flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          <span>{error}</span>
          <button onClick={() => void doRender()}
            className="flex-shrink-0 rounded-full border border-red-300 px-3 py-1 text-xs font-semibold text-red-700 hover:bg-red-100">
            Try again
          </button>
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
        <div className="mx-4 mt-3 rounded-lg border border-canvasAccent/40 bg-canvasAccent/5 px-4 py-2 text-sm text-textPrimary">
          {canvasDirective.instructions}
        </div>
      )}

      <div className="relative flex-1 flex flex-col md:flex-row min-h-0">
        {/* Left rail — face-thumbnail navigator */}
        <div className="md:border-r border-border overflow-y-auto flex-shrink-0">
          <FaceThumbnails />
        </div>

        {/* Centre — the canvas, plus (mobile) the per-step Done button below it.
            On mobile the Adjust panel is a fixed bottom sheet, portalled out of
            this column entirely (see SelectedToolbar's portal comment) — it is
            invoked here for JSX purposes only and renders nothing in place, so
            it reserves no space whether or not something is selected. `pb-80`
            (mobile only, reset at `md:`) leaves scroll room below the Done
            button/tool rail so they can be scrolled clear of the sheet, which
            now overlays the bottom of the viewport instead of sharing this
            column's flow — see item 3 of the mobile-adjust-sheet fix. */}
        <div className="flex-1 flex flex-col items-center gap-3 p-4 pb-80 md:pb-4 overflow-auto min-w-0">
          {showAdjust && !isDesktop && !mobileSheetHidden && (
            <SelectedToolbar variant="sheet" onClose={() => setMobileSheetHidden(true)} />
          )}
          {/* The watermark goes in as CanvasStage's `overlay`, NOT as a wrapper
              around it: CanvasStage sizes itself by walking up from its own
              root to this slot and on to the centre column, so any element
              between the two kills the responsive stage (see the warning in
              CanvasStage). Inside, it is still a plain-DOM sibling of the Konva
              stage, so it stays out of every toDataURL export. */}
          <div data-testid="canvas-stage-wrap" className="w-full shrink-0 flex justify-center">
            <CanvasStage stageRef={stageRef} locked={stageLocked}
              overlay={watermark ? <Watermark text={watermarkText} /> : null} />
          </div>
          {canvasDirective?.showDone && (
            <button onClick={postDone}
              className="px-6 py-2 bg-canvasAccent hover:bg-canvasAccentHover text-white rounded-full text-sm font-semibold">
              Done
            </button>
          )}
        </div>

        {/* Right rail — tools + render. Mobile: collapsed by default behind the
            floating MobileToolsButton (owner: "the rail should be collapsed
            ... revealed by this button") — real conditional rendering, not a
            CSS `hidden` class, so a closed rail is actually out of the DOM
            rather than merely invisible. Desktop ignores `mobileToolsOpen`
            entirely and always renders. Unmounting loses nothing: every tool's
            state (draw mode/colour/width, colourway) lives in canvasStore, not
            component state. This rail is a SIBLING of the centre column (not a
            child CanvasStage measures via availableHeight), so toggling it
            never resizes the cap. */}
        {(isDesktop || mobileToolsOpen) && (
        <div className="md:border-l border-border overflow-y-auto flex-shrink-0">
          {designerName && (
            <div className="px-3 pt-3 text-xs font-semibold text-textMuted truncate">
              Design for {designerName}
            </div>
          )}
          <ToolRail onAddText={() => addText(TEXT_PLACEHOLDER)} onUploadClick={() => fileRef.current?.click()}
            onGraphicsClick={() => setGraphicsOpen(true)}
            colourways={colourways} onRender={() => void doRender()} rendering={rendering}
            // v2: finalize is chat-driven (`triggerFinalize`), not a manual click —
            // force this legacy render button inert ("Design saved ✓", disabled)
            // so it can't be used to jump ahead of the directive walkthrough.
            rendered={isV2 ? true : rendered}
            locked={isV2 ? false : !unlocked}
            // Any v2 turn: finalize is chat-driven (`triggerFinalize`), so this
            // button can never act — showing it permanently disabled
            // ("Design saved ✓") is the same dead-chrome problem as a greyed-out
            // tool, and on mobile its height comes straight out of the cap's
            // own space (the rail is a sibling stacked below the canvas
            // column). `isV2` alone covers REWORK_CANVAS too (unlockAll is
            // only ever set on a v2 directive), so there is no separate case
            // to keep track of. Computed here, not inside ToolRail, because
            // `isV2` is derived from `canvasDirective` and already lives in
            // this component — ToolRail stays a dumb prop-driven renderer.
            hideRender={isV2}
            allowedTools={allowedTools} highlightTool={highlightTool} toolsVisible={toolsVisible} />
          {/* Desktop home for the Adjust panel: the free space below "Design
              saved". The rail root is content-sized (no h-full — adding one
              would push this off-screen via mt-auto on the Done button), so
              this simply follows it. The wrapper mirrors ToolRail's own width
              and padding so the column width is class-driven, not content-driven. */}
          {showAdjust && isDesktop && (
            <div className="w-full md:w-44 lg:w-52 xl:w-64 px-3 xl:px-4 pb-3">
              <SelectedToolbar variant="rail" />
            </div>
          )}
        </div>
        )}
      </div>

      <MobileToolsButton isDesktop={isDesktop} open={mobilePanelOpen} pulse={mobilePulse} onToggle={toggleMobilePanel} />

      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={handleUpload} className="sr-only" aria-label="Upload image" />

      <GraphicsPicker open={graphicsOpen} onClose={() => setGraphicsOpen(false)}
        onPickShape={kind => addShape(kind)} onPickImage={url => void addGraphic(url)} />

      <ReviewDialog
        open={reviewOpen}
        // Same constants the buttons are labelled with — the label IS the chip
        // the backend resolves by identity, so it must have exactly one source.
        onConfirm={() => sendReview(CONFIRM_LABEL)}
        onRework={() => sendReview(REWORK_LABEL)}
        onClose={() => setReviewOpen(false)}
      />
    </div>
  )
}
