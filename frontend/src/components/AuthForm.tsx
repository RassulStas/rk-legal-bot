import { useState } from 'react'
import { setUserToken } from '../auth'
import { UI_STRINGS, type Language } from '../i18n'

type AuthFormProps = {
  apiBase: string
  sessionId: string
  language: Language
  onAuthenticated: () => void
  onBackToChat?: () => void
}

type LoginResponse = {
  dev_code?: string
  otp_ttl_seconds?: number
}

function normalizePhoneDigits(raw: string): string {
  const digits = raw.replace(/\D/g, '')
  if (digits.length === 11 && digits.startsWith('8')) return '7' + digits.slice(1)
  return digits
}

function AuthForm({ apiBase, sessionId, language, onAuthenticated, onBackToChat }: AuthFormProps) {
  const s = UI_STRINGS[language]
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [devCode, setDevCode] = useState<string | null>(null)
  const [phase, setPhase] = useState<'phone' | 'code'>('phone')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function requestCode() {
    const digits = normalizePhoneDigits(phone)
    if (!/^7\d{10}$/.test(digits)) {
      setError(s.invalidPhone)
      return
    }
    setError(null)
    setBusy(true)
    try {
      const res = await fetch(`${apiBase}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone }),
      })
      const body = (await res.json().catch(() => null)) as LoginResponse | null
      if (!res.ok) {
        setError('Не удалось отправить код. Попробуйте ещё раз.')
        return
      }
      setDevCode(body?.dev_code ?? null)
      setPhase('code')
    } catch {
      setError('Проверьте подключение к интернету и попробуйте снова.')
    } finally {
      setBusy(false)
    }
  }

  async function verify() {
    if (!/^\d{4,8}$/.test(code.trim())) {
      setError(s.invalidCode)
      return
    }
    setError(null)
    setBusy(true)
    try {
      const res = await fetch(`${apiBase}/api/auth/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone, code: code.trim(), session_id: sessionId }),
      })
      const body = (await res.json().catch(() => null)) as
        | ({ token?: string } & { user?: unknown })
        | null
      if (!res.ok || !body?.token) {
        setError('Неверный или просроченный код. Запросите новый.')
        return
      }
      setUserToken(body.token)
      setPhase('phone')
      setCode('')
      setDevCode(null)
      onAuthenticated()
    } catch {
      setError('Проверьте подключение к интернету и попробуйте снова.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex items-center gap-3">
        <span
          className="flex h-11 w-11 items-center justify-center rounded-2xl bg-navy-800 ring-1 ring-navy-700"
          aria-hidden="true"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            className="h-5 w-5 text-white"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM4.5 20.5a7.5 7.5 0 0115 0"
            />
          </svg>
        </span>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-navy-900">{s.loginTitle}</h2>
          <p className="text-xs text-slate-500">{s.cabinetSubtitle}</p>
        </div>
      </div>
      <p className="mt-4 text-sm leading-relaxed text-slate-600">{s.loginLead}</p>

      <label htmlFor="auth-phone" className="mt-5 block text-sm font-semibold text-slate-700">
        {s.phoneLabel}
      </label>
      <input
        id="auth-phone"
        type="tel"
        inputMode="tel"
        autoComplete="tel"
        value={phone}
        disabled={phase === 'code'}
        onChange={(e) => {
          setPhone(e.target.value)
          if (error) setError(null)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void requestCode()
        }}
        placeholder="+7 777 123-45-67"
        className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3.5 py-3 text-sm text-slate-800 shadow-sm transition-all placeholder:text-slate-400 focus:border-navy-500 focus:outline-none focus:ring-2 focus:ring-navy-100 disabled:bg-slate-50"
      />

      {phase === 'code' && (
        <>
          <label htmlFor="auth-code" className="mt-4 block text-sm font-semibold text-slate-700">
            {s.codeLabel}
          </label>
          <input
            id="auth-code"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => {
              setCode(e.target.value.replace(/\D/g, '').slice(0, 6))
              if (error) setError(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void verify()
            }}
            placeholder="123456"
            className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3.5 py-3 text-center text-lg font-semibold tracking-[0.4em] text-slate-800 shadow-sm transition-all placeholder:text-slate-300 focus:border-navy-500 focus:outline-none focus:ring-2 focus:ring-navy-100"
          />
          {devCode && (
            <p className="mt-2 rounded-lg bg-navy-50 px-3 py-2 text-center text-xs font-medium text-navy-700">
              {s.codeSent}: <span className="font-bold tracking-widest">{devCode}</span>
            </p>
          )}
        </>
      )}

      {error && <p className="mt-2 text-xs font-medium text-red-500">{error}</p>}

      {phase === 'phone' ? (
        <button
          type="button"
          onClick={() => void requestCode()}
          disabled={busy}
          className="mt-5 flex w-full items-center justify-center gap-2 rounded-2xl bg-navy-800 py-3 text-sm font-bold text-white shadow-md transition-all duration-200 hover:bg-navy-700 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? s.loggingIn : s.sendCode}
        </button>
      ) : (
        <div className="mt-5 flex gap-2">
          <button
            type="button"
            onClick={() => {
              setPhase('phone')
              setCode('')
              setDevCode(null)
              setError(null)
            }}
            className="flex-1 rounded-2xl border border-slate-300 py-3 text-sm font-semibold text-slate-600 transition-colors hover:border-slate-400 hover:text-slate-800"
          >
            ←
          </button>
          <button
            type="button"
            onClick={() => void verify()}
            disabled={busy}
            className="flex-[4] rounded-2xl bg-gradient-to-r from-amber-400 to-amber-500 py-3 text-sm font-bold text-navy-950 shadow-md shadow-amber-400/30 transition-all duration-200 hover:from-amber-300 hover:to-amber-400 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? s.loggingIn : s.verifyLogin}
          </button>
        </div>
      )}
      {onBackToChat && (
        <button
          type="button"
          onClick={onBackToChat}
          className="mx-auto mt-4 flex cursor-pointer items-center gap-1.5 text-xs font-semibold text-navy-600 underline-offset-2 transition-colors hover:text-navy-900 hover:underline"
        >
          ← {s.backToChat}
        </button>
      )}
    </div>
  )
}

export default AuthForm
