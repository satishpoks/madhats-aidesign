// Shared module-level cache for HTMLImageElements used by the design studio
// canvas. Konva needs a real, already-decoded <img> to paint synchronously —
// without this cache, switching faces creates a fresh Image() per mount and
// the flatten loop's rAF wait races the async decode, exporting stale/blank
// pixels. Preloading into this cache (see DesignStudio/index.tsx) lets
// CanvasStage/nodes.tsx read back a `.complete` element and render it on the
// very first paint after a face switch.
const cache = new Map<string, HTMLImageElement>()
// In-flight load promises keyed by url. Dedupes concurrent loadImage() calls
// for the same not-yet-complete url so they all await the SAME Image's
// onload/onerror instead of each caller overwriting the previous caller's
// handlers on a shared Image object (which left the earlier caller's promise
// hanging forever — see CanvasStage's active-face load racing the flatten
// preload for that same face).
const inflight = new Map<string, Promise<HTMLImageElement>>()

export function getCachedImage(url: string): HTMLImageElement | undefined {
  return cache.get(url)
}

export function loadImage(url: string): Promise<HTMLImageElement> {
  if (!url) {
    return Promise.reject(new Error('loadImage: empty url'))
  }

  const cached = cache.get(url)
  if (cached && cached.complete) {
    return Promise.resolve(cached)
  }

  const existing = inflight.get(url)
  if (existing) {
    return existing
  }

  const promise = new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new window.Image()
    img.crossOrigin = 'anonymous' // avoid tainting the canvas for toDataURL()
    img.onload = () => {
      cache.set(url, img)
      inflight.delete(url)
      resolve(img)
    }
    img.onerror = () => {
      inflight.delete(url)
      reject(new Error(`Failed to load image: ${url}`))
    }
    img.src = url
  })

  inflight.set(url, promise)
  return promise
}
