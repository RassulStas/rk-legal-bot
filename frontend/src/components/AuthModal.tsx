import { useEffect } from 'react'
import type { Language } from '../i18n'
import AuthForm from './AuthForm'

type AuthModalProps = {
  open: boolean
  apiBase: string
  sessionId: string
  language: Language
  onClose: () => void
  onAuthenticated: () => void
}

function AuthModal({ open, apiBase, sessionId, language, onClose, onAuthenticated }: AuthModalProps) {
  useEffect(() => {
    if (!open) return
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

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Login"
    >
      <div
        className="absolute inset-0 bg-navy-950/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative w-full max-w-md">
        <button
          type="button"
          onClick={onClose}
          aria-label="Закрыть"
          className="absolute -top-3 right-4 z-10 rounded-full border border-slate-200 bg-white p-1.5 text-slate-400 shadow-md transition-colors hover:text-slate-700 sm:-right-3"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4" aria-hidden="true">
            <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
        <AuthForm apiBase={apiBase} sessionId={sessionId} language={language} onAuthenticated={onAuthenticated} />
      </div>
    </div>
  )
}

export default AuthModal
