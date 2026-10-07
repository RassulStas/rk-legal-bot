import { useEffect, useRef, type KeyboardEvent } from 'react'
import type { LegalDocId } from '../config/legal_docs'
import { DISCLAIMER, UI_STRINGS, type Language } from '../i18n'

type ChatInputProps = {
  language: Language
  disabled: boolean
  onSend: (message: string) => void
  onOpenLegalDoc: (docId: LegalDocId) => void
}

function ChatInput({ language, disabled, onSend, onOpenLegalDoc }: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  })

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  function submit() {
    const value = textareaRef.current?.value.trim()
    if (!value || disabled) return
    onSend(value)
    if (textareaRef.current) textareaRef.current.value = ''
  }

  const label = UI_STRINGS[language].send

  return (
    <footer className="border-t border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto max-w-4xl px-4 py-3 sm:px-6">
        <div className="flex items-end gap-2.5 rounded-2xl border border-slate-300 bg-white px-3 py-2 shadow-sm transition-all duration-200 focus-within:border-navy-500 focus-within:shadow-md focus-within:ring-2 focus-within:ring-navy-100">
          <textarea
            ref={textareaRef}
            rows={1}
            placeholder={UI_STRINGS[language].inputPlaceholder}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            className="max-h-40 flex-1 resize-none bg-transparent px-1 py-1.5 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none disabled:opacity-50"
          />
          <button
            type="button"
            onClick={submit}
            disabled={disabled}
            className="flex h-9 shrink-0 items-center gap-1.5 rounded-xl bg-navy-800 px-4 text-sm font-semibold text-white shadow-sm transition-all duration-200 hover:bg-navy-700 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {label}
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5"
              />
            </svg>
          </button>
        </div>
        <p className="mt-2 text-center text-[11px] leading-snug text-slate-400">
          {DISCLAIMER}
        </p>
        <div className="mt-1.5 flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={() => onOpenLegalDoc('offer')}
            className="text-[11px] font-semibold text-slate-400 underline-offset-2 transition-colors hover:text-navy-600 hover:underline"
          >
            Публичная оферта
          </button>
          <span className="text-slate-300" aria-hidden="true">
            ·
          </span>
          <button
            type="button"
            onClick={() => onOpenLegalDoc('privacy')}
            className="text-[11px] font-semibold text-slate-400 underline-offset-2 transition-colors hover:text-navy-600 hover:underline"
          >
            Политика конфиденциальности
          </button>
        </div>
      </div>
    </footer>
  )
}

export default ChatInput
