import { useState } from 'react'
import { useStudioStore } from '../../store/studioStore'

export function ConceptModal() {
  const { showConceptModal, setShowConceptModal, selectedProduct, selectedSwatch, generatedImageUrl } = useStudioStore()
  const [submitted, setSubmitted] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [notes, setNotes] = useState('')

  if (!showConceptModal) return null

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitted(true)
  }

  function handleClose() {
    setShowConceptModal(false)
    setSubmitted(false)
    setName('')
    setEmail('')
    setNotes('')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end md:items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-surface border border-border rounded-2xl w-full max-w-md animate-fadeIn">
        {submitted ? (
          <div className="p-8 flex flex-col items-center text-center gap-4">
            <div className="w-14 h-14 rounded-full bg-accent/10 border border-accent/30 flex items-center justify-center text-2xl">✓</div>
            <div>
              <p className="text-textPrimary font-bold text-lg">Concept submitted!</p>
              <p className="text-textMuted text-sm mt-1">Our design team will review and be in touch shortly.</p>
            </div>
            <div className="bg-base border border-border rounded-xl px-4 py-2 w-full">
              <p className="text-xs text-textMuted">Share link</p>
              <p className="text-accent text-sm font-mono mt-0.5 truncate">madhats.com.au/studio/s/abc123</p>
            </div>
            <button onClick={handleClose} className="text-sm text-textMuted hover:text-textPrimary transition-colors">
              Close
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-border">
              <h2 className="font-bold text-textPrimary">Request This Concept</h2>
              <button onClick={handleClose} className="text-textMuted hover:text-textPrimary text-lg leading-none">×</button>
            </div>

            {/* Concept thumbnail */}
            <div className="px-6 py-4 flex items-center gap-3 bg-surfaceAlt">
              {generatedImageUrl && (
                <img src={generatedImageUrl} alt="Concept" className="w-16 h-16 rounded-lg object-cover border border-border" />
              )}
              <div>
                <p className="text-sm font-semibold text-textPrimary">{selectedProduct?.name}</p>
                <p className="text-xs text-textMuted">{selectedSwatch?.name} · {selectedProduct?.brand}</p>
              </div>
            </div>

            <form onSubmit={handleSubmit} className="px-6 pb-6 pt-4 flex flex-col gap-4">
              <div>
                <label className="text-xs text-textMuted uppercase tracking-wide font-medium mb-1.5 block">Name</label>
                <input
                  required
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Your name"
                  className="w-full bg-base border border-border rounded-xl px-3 py-2.5 text-sm text-textPrimary placeholder:text-textMuted focus:outline-none focus:border-accent transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-textMuted uppercase tracking-wide font-medium mb-1.5 block">Email</label>
                <input
                  required
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  className="w-full bg-base border border-border rounded-xl px-3 py-2.5 text-sm text-textPrimary placeholder:text-textMuted focus:outline-none focus:border-accent transition-colors"
                />
              </div>
              <div>
                <label className="text-xs text-textMuted uppercase tracking-wide font-medium mb-1.5 block">Notes <span className="normal-case font-normal">(optional)</span></label>
                <textarea
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  placeholder="Any extra details for the design team…"
                  rows={3}
                  className="w-full bg-base border border-border rounded-xl px-3 py-2.5 text-sm text-textPrimary placeholder:text-textMuted focus:outline-none focus:border-accent transition-colors resize-none"
                />
              </div>
              <button
                type="submit"
                className="w-full py-3 rounded-xl bg-accent text-white font-bold text-sm hover:bg-accentHover transition-colors mt-1"
              >
                Submit Concept
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
