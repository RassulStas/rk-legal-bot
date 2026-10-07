import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { LegalDocId } from '../config/legal_docs'
import { DISCLAIMER, UI_STRINGS, type Language } from '../i18n'

const ACCEPTED_EXTS = ['.docx', '.doc', '.pdf', '.txt']
const MAX_FILE_BYTES = 10 * 1024 * 1024

type ChatInputProps = {
  language: Language
  disabled: boolean
  premiumActive: boolean
  onSend: (message: string) => void
  onAnalyzeContract: (file: File) => void
  onOpenPremium: () => void
  onOpenLegalDoc: (docId: LegalDocId) => void
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
  return `${Math.max(1, Math.round(bytes / 1024))} КБ`
}

function ChatInput({
  language,
  disabled,
  premiumActive,
  onSend,
  onAnalyzeContract,
  onOpenPremium,
  onOpenLegalDoc,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [attachError, setAttachError] = useState<string | null>(null)

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
    if (disabled) return
    if (pendingFile) {
      onAnalyzeContract(pendingFile)
      setPendingFile(null)
      return
    }
    const value = textareaRef.current?.value.trim()
    if (!value) return
    onSend(value)
    if (textareaRef.current) textareaRef.current.value = ''
  }

  function handleAttachClick() {
    setAttachError(null)
    if (!premiumActive) {
      onOpenPremium()
      return
    }
    fileInputRef.current?.click()
  }

  function handleFileChange(files: FileList | null) {
    const file = files?.[0]
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (!file) return
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    if (!ACCEPTED_EXTS.includes(ext)) {
      setAttachError('.docx, .doc, .pdf, .txt')
      setPendingFile(null)
      return
    }
    if (file.size > MAX_FILE_BYTES) {
      setAttachError(UI_STRINGS[language].fileTooLarge)
      setPendingFile(null)
      return
    }
    setAttachError(null)
    setPendingFile(file)
  }

  const strings = UI_STRINGS[language]
  const label = strings.send

  return (
    <footer className="border-t border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto max-w-4xl px-4 py-3 sm:px-6">
        {pendingFile && (
          <div className="mb-2 flex items-center gap-2">
            <span className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-navy-200 bg-navy-50 px-2.5 py-1 text-xs font-medium text-navy-800">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                className="h-3.5 w-3.5 shrink-0"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                />
              </svg>
              <span className="truncate">{pendingFile.name}</span>
              <span className="shrink-0 text-navy-500">
                {formatSize(pendingFile.size)}
              </span>
              <button
                type="button"
                onClick={() => setPendingFile(null)}
                className="ml-0.5 shrink-0 rounded-full p-0.5 text-navy-500 transition-colors hover:bg-navy-100 hover:text-navy-800"
                aria-label="Убрать файл"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-3 w-3"
                  aria-hidden="true"
                >
                  <path strokeLinecap="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          </div>
        )}
        <div className="flex items-end gap-2.5 rounded-2xl border border-slate-300 bg-white px-3 py-2 shadow-sm transition-all duration-200 focus-within:border-navy-500 focus-within:shadow-md focus-within:ring-2 focus-within:ring-navy-100">
          <input
            ref={fileInputRef}
            type="file"
            accept=".docx,.doc,.pdf,.txt"
            className="hidden"
            onChange={(e) => handleFileChange(e.target.files)}
          />
          <button
            type="button"
            onClick={handleAttachClick}
            disabled={disabled}
            title={premiumActive ? strings.attachContract : strings.attachBlocked}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-slate-500 transition-all duration-200 hover:bg-slate-100 hover:text-navy-700 active:scale-[0.96] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-5 w-5"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32a.75.75 0 01-1.06-1.06l9.114-9.114"
              />
            </svg>
          </button>
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
        {attachError && (
          <p className="mt-1.5 text-center text-[11px] font-medium text-red-500">
            {attachError}
          </p>
        )}
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
