import { createRef } from 'react'
import { render } from '@testing-library/react'
import { describe, expect, test, vi } from 'vitest'
import { Stage, Layer } from 'react-konva'
import type Konva from 'konva'
import { TextNode, ImageNode } from '../components/DesignStudio/nodes'
import type { CanvasElement } from '../store/canvasStore'

// jsdom has no real <canvas> 2D backend (the `canvas` npm package isn't
// installed here), so `HTMLCanvasElement.getContext('2d')` returns null and a
// real Konva Stage can't mount at all. We only need Konva's OBJECT GRAPH
// (node.draggable(), stage.findOne(), node.fire('click')) to work — none of
// that requires actual pixels — so stub getContext with a permissive no-op
// 2D context. This is local to this file (not global test setup) since it's
// the only spec that mounts a real react-konva <Stage>.
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
    set(target, prop: string, value) {
      target[prop] = value
      return true
    },
  }) as unknown as CanvasRenderingContext2D
}

HTMLCanvasElement.prototype.getContext = ((() => stubCanvasContext()) as unknown) as typeof HTMLCanvasElement.prototype.getContext

// Behavioral checks (not vacuous): a locked element must (a) report
// draggable() === false on the underlying Konva node, (b) render no
// Transformer even when isSelected, and (c) NOT invoke onSelect when a
// 'click' event is fired directly on the node. An unlocked element must do
// the opposite on all three counts — so a test that only checked "no click
// fired -> onSelect not called" (the plan's original snippet) would pass
// for both locked AND unlocked nodes and prove nothing.

function baseText(overrides: Partial<CanvasElement> = {}): CanvasElement {
  return {
    id: 't1', type: 'text', x: 0.5, y: 0.5, width: 0.3, height: 0.1,
    rotation: 0, zIndex: 0, content: 'hi', ...overrides,
  }
}

function baseImage(overrides: Partial<CanvasElement> = {}): CanvasElement {
  return {
    id: 'i1', type: 'image', x: 0.5, y: 0.5, width: 0.3, height: 0.3,
    rotation: 0, zIndex: 0, ...overrides,
  }
}

describe('TextNode respects el.locked', () => {
  test('locked: not draggable, click does not select, no Transformer', () => {
    const stageRef = createRef<Konva.Stage>()
    const onSelect = vi.fn()
    render(
      <Stage ref={stageRef} width={200} height={200}>
        <Layer>
          <TextNode
            el={baseText({ locked: true })}
            stageW={200} stageH={200}
            isSelected onSelect={onSelect} onChange={() => {}}
          />
        </Layer>
      </Stage>,
    )
    const node = stageRef.current!.findOne('Text') as Konva.Text
    expect(node).toBeTruthy()
    expect(node.draggable()).toBe(false)
    expect(stageRef.current!.findOne('Transformer')).toBeFalsy()

    node.fire('click', {}, true)
    expect(onSelect).not.toHaveBeenCalled()
  })

  test('unlocked: draggable, click selects, Transformer renders when selected', () => {
    const stageRef = createRef<Konva.Stage>()
    const onSelect = vi.fn()
    render(
      <Stage ref={stageRef} width={200} height={200}>
        <Layer>
          <TextNode
            el={baseText({ locked: false })}
            stageW={200} stageH={200}
            isSelected onSelect={onSelect} onChange={() => {}}
          />
        </Layer>
      </Stage>,
    )
    const node = stageRef.current!.findOne('Text') as Konva.Text
    expect(node.draggable()).toBe(true)
    expect(stageRef.current!.findOne('Transformer')).toBeTruthy()

    node.fire('click', {}, true)
    expect(onSelect).toHaveBeenCalledTimes(1)
  })
})

describe('ImageNode respects el.locked', () => {
  test('locked: not draggable, click does not select, no Transformer', () => {
    const stageRef = createRef<Konva.Stage>()
    const onSelect = vi.fn()
    render(
      <Stage ref={stageRef} width={200} height={200}>
        <Layer>
          <ImageNode
            el={baseImage({ locked: true })}
            stageW={200} stageH={200}
            isSelected onSelect={onSelect} onChange={() => {}}
          />
        </Layer>
      </Stage>,
    )
    const node = stageRef.current!.findOne('Image') as Konva.Image
    expect(node).toBeTruthy()
    expect(node.draggable()).toBe(false)
    expect(stageRef.current!.findOne('Transformer')).toBeFalsy()

    node.fire('click', {}, true)
    expect(onSelect).not.toHaveBeenCalled()
  })

  test('unlocked: draggable, click selects, Transformer renders when selected', () => {
    const stageRef = createRef<Konva.Stage>()
    const onSelect = vi.fn()
    render(
      <Stage ref={stageRef} width={200} height={200}>
        <Layer>
          <ImageNode
            el={baseImage({ locked: false })}
            stageW={200} stageH={200}
            isSelected onSelect={onSelect} onChange={() => {}}
          />
        </Layer>
      </Stage>,
    )
    const node = stageRef.current!.findOne('Image') as Konva.Image
    expect(node.draggable()).toBe(true)
    expect(stageRef.current!.findOne('Transformer')).toBeTruthy()

    node.fire('click', {}, true)
    expect(onSelect).toHaveBeenCalledTimes(1)
  })
})
