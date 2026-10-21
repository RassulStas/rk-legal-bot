import { useRef, useState, type DragEvent, type KeyboardEvent } from 'react'
import { UI_STRINGS, type Language } from '../i18n'
import { ACCEPTED_EXTS, validateUpload } from '../uploads'

type EmptyStateProps = {
  language: Language
  premiumActive: boolean
  onAnalyzeContract: (file: File) => void
  onOpenPremium: () => void
  onPickStarter: (prompt: string) => void
}

// Landing state shown before the first message. Ad traffic arrives cold and
// 98% of it is mobile, so the primary action is a full-width tap target rather
// than the small paperclip in the input bar.
function EmptyState({
  language,
  premiumActive,
  onAnalyzeContract,
  onOpenPremium,
  onPickStarter,
}: EmptyStateProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)

  const s = UI_STRINGS[language]

  // Contract analysis is Premium-gated on the server (403), so for an anonymous
  // visitor this block is a paywall trigger, not a file picker. It is labelled
  // as such on the block itself — promising an upload and showing a payment
  // modal instead would be a bait-and-switch that costs more trust than it
  // converts.
  function activate() {
    setFileError(null)
    if (!premiumActive) {
      onOpenPremium()
      return
    }
    fileInputRef.current?.click()
  }

  function handleKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== 'Enter' && e.key !== ' ') return
    e.preventDefault()
    activate()
  }

  function handleDragLeave(e: DragEvent<HTMLDivElement>) {
    // dragleave also fires when the pointer crosses into a child element; only
    // an exit from the whole block should clear the highlight.
    const next = e.relatedTarget as Node | null
    if (next && e.currentTarget.contains(next)) return
    setDragging(false)
  }

  function submitFile(file: File | undefined) {
    if (!file) return
    const rejection = validateUpload(file)
    if (rejection) {
      setFileError(
        rejection === 'size' ? s.fileTooLarge : ACCEPTED_EXTS.join(', '),
      )
      return
    }
    setFileError(null)
    onAnalyzeContract(file)
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragging(false)
    if (!premiumActive) {
      onOpenPremium()
      return
    }
    submitFile(e.dataTransfer.files?.[0])
  }

  const chips = [
    { emoji: '🏢', label: s.chipLease, prompt: s.promptLease },
    { emoji: '📦', label: s.chipSupply, prompt: s.promptSupply },
    { emoji: '💼', label: s.chipEmployment, prompt: s.promptEmployment },
  ]

  return (
    // my-auto (not justify-center on the parent): auto margins centre the block
    // when the viewport has spare height, but collapse to zero when the content
    // is taller than the viewport — justify-center would clip the heading above
    // the scroll origin where it can never be reached.
    <div className="my-auto flex flex-col items-center pb-4 text-center">
      <h1 className="text-xl font-extrabold tracking-tight text-navy-900 sm:text-[28px] sm:leading-tight">
        {s.emptyTitle}
      </h1>
      <p className="mt-2.5 max-w-md text-sm leading-relaxed text-slate-500">
        {s.emptyLead}
      </p>

      <div
        role="button"
        tabIndex={0}
        aria-label={s.uploadAria}
        onClick={activate}
        onKeyDown={handleKeyDown}
        onDragOver={(e) => {
          e.preventDefault()
          e.dataTransfer.dropEffect = 'copy'
          if (!dragging) setDragging(true)
        }}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={`relative mt-6 w-full max-w-md cursor-pointer rounded-2xl border-2 border-dashed p-6 shadow-sm transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-navy-400 focus-visible:ring-offset-2 sm:p-8 ${
          dragging
            ? 'scale-[1.01] border-navy-500 bg-navy-100 shadow-md'
            : 'border-navy-300 bg-navy-50/60 hover:border-navy-400 hover:bg-navy-100/70 hover:shadow-md active:scale-[0.99]'
        }`}
      >
        {!premiumActive && (
          <span className="absolute right-3 top-3 flex items-center gap-1 rounded-full bg-gradient-to-r from-amber-400 to-amber-500 px-2.5 py-1 text-[10px] font-bold text-navy-950 shadow-sm">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-3 w-3"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"
              />
            </svg>
            {s.premiumBadge}
          </span>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTS.join(',')}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (e.currentTarget) e.currentTarget.value = ''
            submitFile(file)
          }}
        />

        <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-navy-700 shadow-sm ring-1 ring-navy-200">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            className="h-7 w-7"
            aria-hidden="true"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
            />
          </svg>
        </span>

        <p className="mt-4 text-sm font-extrabold uppercase leading-snug tracking-tight text-navy-900 sm:text-base">
          {dragging ? s.dropActive : s.uploadCta}
        </p>
        <p className="mt-2 text-xs font-medium text-slate-500">
          {s.uploadFormats}
        </p>
        {!premiumActive && (
          <p className="mx-auto mt-3 max-w-xs text-xs font-semibold leading-snug text-navy-700">
            {s.uploadLocked}
          </p>
        )}
      </div>

      {fileError && (
        <p className="mt-3 text-xs font-semibold text-red-500">{fileError}</p>
      )}

      <p className="mt-8 text-[11px] font-bold uppercase tracking-wider text-slate-400">
        {s.quickStart}
      </p>
      <div className="mt-3 flex w-full max-w-md flex-col gap-2 sm:w-auto sm:flex-row sm:gap-2.5">
        {chips.map((chip) => (
          <button
            key={chip.label}
            type="button"
            onClick={() => onPickStarter(chip.prompt)}
            className="flex items-center justify-center gap-2 rounded-xl border border-navy-200 bg-white px-4 py-2.5 text-sm font-semibold text-navy-800 shadow-sm transition-all duration-200 hover:border-navy-400 hover:bg-navy-50 active:scale-[0.97]"
          >
            <span aria-hidden="true">{chip.emoji}</span>
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  )
}

export default EmptyState
