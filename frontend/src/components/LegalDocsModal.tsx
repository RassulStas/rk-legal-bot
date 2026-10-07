import { useEffect } from 'react'
import { LEGAL_DOCS, type LegalDocId } from '../config/legal_docs'

type LegalDocsModalProps = {
  docId: LegalDocId
  onClose: () => void
}

function LegalDocsModal({ docId, onClose }: LegalDocsModalProps) {
  const doc = LEGAL_DOCS[docId]

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  })

  if (!doc) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={doc.title}
    >
      <div
        className="absolute inset-0 bg-navy-950/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
          <div>
            <h2 className="text-base font-bold leading-snug tracking-tight text-navy-900">
              {doc.title}
            </h2>
            <p className="mt-0.5 text-xs text-slate-400">{doc.updatedAt}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="rounded-full p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-5 w-5"
              aria-hidden="true"
            >
              <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {doc.preamble.map((paragraph) => (
            <p key={paragraph.slice(0, 40)} className="mb-3 text-sm leading-relaxed text-slate-600">
              {paragraph}
            </p>
          ))}
          {doc.sections.map((section) => (
            <section key={section.heading} className="mt-5">
              <h3 className="text-sm font-bold uppercase tracking-wide text-navy-800">
                {section.heading}
              </h3>
              <div className="mt-2 space-y-2">
                {section.paragraphs.map((paragraph) => (
                  <p key={paragraph.slice(0, 48)} className="text-sm leading-relaxed text-slate-600">
                    {paragraph}
                  </p>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}

export default LegalDocsModal
