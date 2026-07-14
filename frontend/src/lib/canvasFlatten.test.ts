import { describe, it, expect } from 'vitest'
import { dataUrlToFile, flattenStage, FLATTEN_HIDE_NAME } from './canvasFlatten'

// 1x1 transparent PNG
const PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

describe('dataUrlToFile', () => {
  it('decodes a data URL into a PNG File', () => {
    const f = dataUrlToFile(PNG, 'front.png')
    expect(f).toBeInstanceOf(File)
    expect(f.type).toBe('image/png')
    expect(f.name).toBe('front.png')
    expect(f.size).toBeGreaterThan(0)
  })
})

// A fake node whose visibility state is captured whenever toDataURL runs.
function fakeNode(name: string, log: string[]) {
  return {
    _name: name,
    visible: true,
    name() { return this._name },
    hide() { this.visible = false; log.push(`hide:${this._name}`) },
    show() { this.visible = true; log.push(`show:${this._name}`) },
  }
}

describe('flattenStage', () => {
  it('hides flatten-hide nodes (product photo + tint) during export, restores after', () => {
    const log: string[] = []
    const bg = fakeNode(FLATTEN_HIDE_NAME, log)
    const tint = fakeNode(FLATTEN_HIDE_NAME, log)
    const text = fakeNode('', log) // a decoration — must NOT be hidden
    let visibleWhenRasterised: Record<string, boolean> | null = null

    const stage = {
      // function selector: return only the nodes the predicate matches
      find(pred: (n: unknown) => boolean) {
        const arr = [bg, tint, text]
        const matched = arr.filter(pred)
        return Object.assign(matched, { forEach: matched.forEach.bind(matched) })
      },
      draw() {},
      toDataURL() {
        visibleWhenRasterised = { bg: bg.visible, tint: tint.visible, text: text.visible }
        log.push('toDataURL')
        return PNG
      },
    } as never

    const url = flattenStage(stage)
    expect(url).toBe(PNG)
    // Background nodes were hidden at rasterise time; the decoration stayed visible.
    expect(visibleWhenRasterised).toEqual({ bg: false, tint: false, text: true })
    // And they were restored afterwards.
    expect(bg.visible).toBe(true)
    expect(tint.visible).toBe(true)
    // Ordering: both hides precede toDataURL, both shows follow it.
    expect(log.indexOf('toDataURL')).toBeGreaterThan(log.indexOf('hide:flatten-hide'))
    expect(log.lastIndexOf('show:flatten-hide')).toBeGreaterThan(log.indexOf('toDataURL'))
  })
})
