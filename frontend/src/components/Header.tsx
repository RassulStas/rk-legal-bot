import { LANG_LABELS, UI_STRINGS, type Language } from '../i18n'

type HeaderProps = {
  language: Language
  onLanguageChange: (language: Language) => void
}

function Header({ language, onLanguageChange }: HeaderProps) {
  return (
    <header className="sticky top-0 z-10 bg-gradient-to-r from-navy-950 via-navy-900 to-navy-800 shadow-md">
      <div className="mx-auto flex max-w-4xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-3">
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
        </div>

        <div className="flex items-center gap-2.5">
          <span className="flex items-center gap-1.5 rounded-full border border-amber-300/30 bg-amber-400/10 px-2.5 py-1 text-[11px] font-medium text-amber-200">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-300" aria-hidden="true" />
            Free Tier Mode
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
