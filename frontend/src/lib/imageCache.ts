// Shared module-level cache for HTMLImageElements used by the design studio
// canvas. Konva needs a real, already-decoded <img> to paint synchronously —
// without this cache, switching faces creates a fresh Image() per mount and
// the flatten loop's rAF wait races the async decode, exporting stale/blank
// pixels. Preloading into this cache (see DesignStudio/index.tsx) lets
// CanvasStage/nodes.tsx read back a `.complete` element and render it on the
// very first paint after a face switch.
const cache = new Map<string, HTMLImageElement>()

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

  return new Promise((resolve, reject) => {
    const img = cached ?? new window.Image()
    img.crossOrigin = 'anonymous' // avoid tainting the canvas for toDataURL()
    img.onload = () => { cache.set(url, img); resolve(img) }
    img.onerror = () => reject(new Error(`Failed to load image: ${url}`))
    cache.set(url, img)
    img.src = url
  })
}
