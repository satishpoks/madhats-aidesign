/**
 * A blocking-looking (but not event-blocking) progress scrim drawn over the
 * cap while something the customer started is still in flight — today, an
 * image upload.
 *
 * Like Watermark, this is a plain-DOM SIBLING of the Konva `<Stage>`, passed in
 * as CanvasStage's `overlay`. That is load-bearing for the same reason it is
 * there: a DOM node can never appear in `stage.toDataURL()`, so a spinner that
 * happens to be on screen when a flatten runs can never reach the layout guide
 * the image model conditions on, nor the WYSIWYG preview the customer is
 * emailed. Never make this a Konva layer.
 *
 * `role="status"` (not `alert`) so a screen reader announces it politely — the
 * upload is progress, not an error.
 */
export function BusyOverlay({ label }: { label: string }) {
  return (
    <div
      data-testid="canvas-busy"
      role="status"
      aria-live="polite"
      // z-20 so it sits above the watermark (z-10) when both are up.
      // pointer-events-none: the cap underneath is already read-only during an
      // upload step, and swallowing clicks here would also swallow them for the
      // instant the overlay is torn down.
      className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 rounded-2xl bg-surface/70 backdrop-blur-[1px]"
    >
      <span className="w-8 h-8 rounded-full border-2 border-canvasAccent border-t-transparent animate-spin" />
      <span className="text-sm font-medium text-textPrimary">{label}</span>
    </div>
  )
}
