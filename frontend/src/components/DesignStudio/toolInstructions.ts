/** Canned per-tool usage tips (fallback when the chat directive omits copy). */
export const TOOL_INSTRUCTIONS: Record<'upload' | 'text' | 'shape', string> = {
  upload: 'Drag to move it, pull a corner to resize, and use the top handle to rotate.',
  text: 'Type your wording, drag to position, and change font/size/colour in the toolbar under the cap.',
  shape: 'Drag to position and resize; recolour it from the toolbar under the cap.',
}
