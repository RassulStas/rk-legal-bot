import { LANG_LABELS, UI_STRINGS, type Language } from '../i18n'
import type { ClaimStatus } from './PremiumModal'

type HeaderProps = {
  language: Language
  onLanguageChange: (language: Language) => void
  claimStatus: ClaimStatus
  onOpenPremium: () => void
  onOpenCabinet: () => void
  cabinetActive: boolean
}

const BADGE_STYLES: Record<ClaimStatus, string> = {
  none: 'border-amber-300/30 bg-amber-400/10 text-amber-200',
  pending: 'border-amber-300/30 bg-amber-400/10 text-amber-200',
  active: 'border-emerald-300/30 bg-emerald-400/10 text-emerald-200',
}

const BADGE_DOT: Record<ClaimStatus, string> = {
  none: 'bg-amber-300',
  pending: 'animate-pulse bg-amber-300',
  active: 'bg-emerald-300',
}

function Header({
  language,
  onLanguageChange,
  claimStatus,
  onOpenPremium,
  onOpenCabinet,
  cabinetActive,
}: HeaderProps) {
  return (
    <header className="sticky top-0 z-10 bg-gradient-to-r from-navy-950 via-navy-900 to-navy-800 shadow-md">
      <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <button
          type="button"
          onClick={() => {
            window.location.hash = '/'
          }}
          aria-label="На главную"
          className="flex cursor-pointer items-center gap-3 rounded-xl text-left transition-opacity duration-200 hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
        >
          <div
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/20"
            aria-hidden="true"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              className="h-5 w-5 text-navy-100"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 3v18M3 7l9-4 9 4M4 7v4c0 1.66 3.58 3 8 3s8-1.34 8-3V7M4 15v2c0 1.66 3.58 3 8 3s8-1.34 8-3v-2"
              />
            </svg>
          </div>
          <div>
            <h1 className="text-lg font-semibold leading-tight tracking-tight text-white">
              RK Legal AI Assistant
            </h1>
            <p className="hidden text-xs text-navy-200 sm:block">
              {UI_STRINGS[language].subtitle}
            </p>
          </div>
        </button>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={onOpenCabinet}
            aria-label={UI_STRINGS[language].cabinet}
            className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold transition-all duration-200 ${
              cabinetActive
                ? 'border-white/40 bg-white/20 text-white'
                : 'border-white/15 bg-white/10 text-navy-100 hover:bg-white/20 hover:text-white'
            }`}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              className="h-3.5 w-3.5"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM4.5 20.5a7.5 7.5 0 0115 0"
              />
            </svg>
            <span className="hidden sm:inline">{UI_STRINGS[language].cabinet}</span>
          </button>

          <button
            type="button"
            onClick={onOpenPremium}
            aria-label={UI_STRINGS[language].premiumButtonAria}
            className="flex items-center gap-1.5 rounded-full bg-gradient-to-r from-amber-400 to-amber-500 px-3 py-1 text-xs font-bold text-navy-950 shadow-sm transition-all duration-200 hover:from-amber-300 hover:to-amber-400 active:scale-[0.97]"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-3.5 w-3.5"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3z"
              />
            </svg>
            {UI_STRINGS[language].premiumButton}
          </button>

          <span
            className={`hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium sm:flex ${BADGE_STYLES[claimStatus]}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${BADGE_DOT[claimStatus]}`} aria-hidden="true" />
            {claimStatus === 'active'
              ? UI_STRINGS[language].premiumBadge
              : claimStatus === 'pending'
                ? UI_STRINGS[language].premiumPendingBadge
                : UI_STRINGS[language].freeTierBadge}
          </span>

          <div
            className="flex items-center rounded-full border border-white/15 bg-white/10 p-1"
            role="group"
            aria-label="Language"
          >
            {(Object.keys(LANG_LABELS) as Language[]).map((lang) => (
              <button
                key={lang}
                type="button"
                onClick={() => onLanguageChange(lang)}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition-all duration-200 ${
                  language === lang
                    ? 'bg-white text-navy-900 shadow-sm'
                    : 'text-navy-200 hover:text-white'
                }`}
              >
                {LANG_LABELS[lang]}
              </button>
            ))}
          </div>
        </div>
      </div>
    </header>
  )
}

export default Header
