import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import { expect, test, vi, beforeEach } from 'vitest'

// Deferred upload so the pending window is observable: a real large-file upload
// is exactly the several-second gap this indicator exists to cover.
let resolveUpload: (v: { asset_url: string; asset_path: string }) => void = () => {}
const uploadLogo = vi.fn(
  () => new Promise<{ asset_url: string; asset_path: string }>(res => { resolveUpload = res }),
)

vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({ reply: 'ok', state: 'logo_adjust', data: {} }),
  uploadLogo: (...a: unknown[]) => uploadLogo(...(a as [])),
  uploadCanvasLayouts: vi.fn().mockResolvedValue(undefined),
  finalizeCanvas: vi.fn().mockResolvedValue({ reply: 'ok', state: 'generating', data: {} }),
}))

// jsdom never fires <img> onload, so the real loadImage promise would hang and
// the busy flag could never clear — stub the cache module outright.
vi.mock('../lib/imageCache', () => ({
  loadImage: vi.fn().mockResolvedValue({ naturalWidth: 200, naturalHeight: 100 }),
  getCachedImage: vi.fn().mockReturnValue(undefined),
}))

import { DesignStudioSurface } from '../components/DesignStudio/Surface'
import { ToolRail } from '../components/DesignStudio/ToolRail'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useCanvasStore } from '../store/canvasStore'

// Same canvas stubs every Surface-mounting test needs (see surfaceDirective).
function stubCanvasContext(): CanvasRenderingContext2D {
  const noop = () => {}
  const store: Record<string, unknown> = {}
  return new Proxy(store, {
    get(target, prop: string) {
      if (prop in target) return target[prop]
      switch (prop) {
        case 'measureText': return () => ({ width: 0 })
        case 'createLinearGradient':
        case 'createRadialGradient': return () => ({ addColorStop: noop })
        case 'createPattern': return () => ({})
        case 'getImageData': return () => ({ data: new Uint8ClampedArray(4), width: 1, height: 1 })
        case 'canvas': return undefined
        default: return noop
      }
    },
    set(target, prop: string, value) { target[prop] = value; return true },
  }) as unknown as CanvasRenderingContext2D
}
HTMLCanvasElement.prototype.getContext = ((() => stubCanvasContext()) as unknown) as typeof HTMLCanvasElement.prototype.getContext

beforeEach(() => {
  useChatStore.getState().reset()
  useCanvasStore.getState().reset()
  useSessionStore.setState({ sessionId: 's1', productRef: null } as never)
  uploadLogo.mockClear()
})

function rail(extra: Record<string, unknown> = {}) {
  return render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false}
      {...extra} />,
  )
}

test('ToolRail: the upload button reports progress and is not re-clickable', () => {
  rail({ allowedTools: new Set(['upload']), uploading: true })
  const upload = screen.getByRole('button', { name: /uploading/i })
  expect(upload).toBeDisabled()
})

test('ToolRail: the upload button is idle when nothing is uploading', () => {
  rail({ allowedTools: new Set(['upload']) })
  const upload = screen.getByRole('button', { name: /upload image/i })
  expect(upload).not.toBeDisabled()
})

test('Surface: a busy overlay covers the cap while a large image uploads, then clears', async () => {
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: null, autoOpen: null, instructions: '', showDone: false },
  } as never)
  render(<DesignStudioSurface />)

  const input = screen.getByLabelText('Upload image') as HTMLInputElement
  const file = new File(['x'.repeat(2048)], 'logo.png', { type: 'image/png' })
  await act(async () => {
    fireEvent.change(input, { target: { files: [file] } })
  })

  // Still in flight: the customer can see something is happening.
  expect(screen.getByTestId('canvas-busy')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(/uploading/i)

  await act(async () => {
    resolveUpload({ asset_url: 'https://x/logo.png', asset_path: 'p/logo.png' })
  })

  await waitFor(() => expect(screen.queryByTestId('canvas-busy')).not.toBeInTheDocument())
  // And the image actually landed on the canvas.
  expect(useCanvasStore.getState().faces.front.some(e => e.type === 'image')).toBe(true)
})

test('Surface: the busy overlay clears when the upload fails', async () => {
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: null, autoOpen: null, instructions: '', showDone: false },
  } as never)
  uploadLogo.mockImplementationOnce(() => Promise.reject(new Error('File too large')))
  render(<DesignStudioSurface />)

  const input = screen.getByLabelText('Upload image') as HTMLInputElement
  await act(async () => {
    fireEvent.change(input, { target: { files: [new File(['x'], 'l.png', { type: 'image/png' })] } })
  })

  await waitFor(() => expect(screen.queryByTestId('canvas-busy')).not.toBeInTheDocument())
  expect(screen.getByRole('alert')).toHaveTextContent('File too large')
})
