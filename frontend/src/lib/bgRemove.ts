import type { CanvasElement } from '../store/canvasStore'
import { uploadLogo } from './api'

/**
 * Run in-browser background matting on an image URL → a transparent PNG File.
 * The library is dynamic-imported so its multi-MB WASM model only downloads when
 * a customer actually removes a background — it never enters the main bundle.
 */
export async function removeBackgroundToFile(src: string): Promise<File> {
  const { removeBackground } = await import('@imgly/background-removal')
  const blob = await removeBackground(src)
  return new File([blob], 'logo-nobg.png', { type: 'image/png' })
}

/**
 * Compute the element patch for toggling background removal on/off. Re-uploads
 * the now-active image via uploadLogo so the crisp asset Gemini receives
 * (session uploaded_asset_path, last write wins) stays in sync with the canvas.
 */
export async function toggleBackground(
  sessionId: string,
  el: CanvasElement,
  on: boolean,
): Promise<Partial<CanvasElement>> {
  if (on) {
    const file = await removeBackgroundToFile(el.assetUrl ?? '')
    const { asset_url } = await uploadLogo(sessionId, file)
    return { assetUrl: asset_url, removeBg: true, originalAssetUrl: el.originalAssetUrl ?? el.assetUrl }
  }
  const orig = el.originalAssetUrl ?? el.assetUrl ?? ''
  const blob = await (await fetch(orig)).blob()
  const file = new File([blob], 'logo.png', { type: blob.type || 'image/png' })
  const { asset_url } = await uploadLogo(sessionId, file)
  return { assetUrl: asset_url, removeBg: false }
}
