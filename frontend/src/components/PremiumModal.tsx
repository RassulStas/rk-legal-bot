import { useEffect, useRef, useState } from 'react'
import { PREMIUM_PLAN, premiumGuideText } from '../config/premium'

export type ClaimStatus = 'none' | 'pending' | 'active'

type PremiumModalProps = {
  open: boolean
  apiBase: string
  sessionId: string
  claimStatus: ClaimStatus
  onClose: () => void
  onOpenOffer: () => void
  onClaimSubmitted: () => void
}

const PHONE_PLACEHOLDER = '+7 777 123-45-67'

function CheckIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      className="h-4 w-4 text-amber-500"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
    </svg>
  )
}

function PremiumModal({
  open,
  apiBase,
  sessionId,
  claimStatus,
  onClose,
  onOpenOffer,
  onClaimSubmitted,
}: PremiumModalProps) {
  const [phone, setPhone] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [copied, setCopied] = useState(false)
  const [editing, setEditing] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const phoneDisplay = PREMIUM_PLAN.kaspiPhoneDisplay
  const guide = premiumGuideText(phoneDisplay)
  const guideParts = guide.split(phoneDisplay)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose()
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  })

  useEffect(() => {
    if (open && claimStatus === 'none') inputRef.current?.focus()
  }, [open, claimStatus])

  if (!open) return null

  function handleClose() {
    setEditing(false)
    onClose()
  }

  const showForm = claimStatus === 'none' || editing

  async function copyPhone() {
    try {
      await navigator.clipboard.writeText(PREMIUM_PLAN.kaspiPhone)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard unavailable — the number stays visible for manual entry */
    }
  }

  async function submit() {
    const digits = phone.replace(/\D/g, '')
    const normalized =
      digits.length === 11 && digits.startsWith('8') ? '7' + digits.slice(1) : digits
    if (!/^7\d{10}$/.test(normalized)) {
      setError('Введите номер в формате +7 7XX XXX-XX-XX')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      const res = await fetch(`${apiBase}/api/premium/claim`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phone, session_id: sessionId }),
      })
      const body = (await res.json().catch(() => null)) as {
        detail?: string
      } | null
      if (!res.ok) {
        setError(body?.detail ?? 'Не удалось отправить заявку. Попробуйте ещё раз.')
        return
      }
      onClaimSubmitted()
    } catch {
      setError('Проверьте подключение к интернету и попробуйте снова.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={PREMIUM_PLAN.planName}
    >
      <div
        className="absolute inset-0 bg-navy-950/60 backdrop-blur-sm"
        onClick={handleClose}
      />
      <div className="relative flex max-h-[92vh] w-full max-w-lg flex-col overflow-y-auto rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl">
        <div className="bg-gradient-to-br from-navy-900 via-navy-800 to-navy-700 px-6 pb-6 pt-5 text-white">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-2.5">
              <span
                className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-400/20 ring-1 ring-amber-300/40"
                aria-hidden="true"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  className="h-5 w-5 text-amber-300"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z"
                  />
                </svg>
              </span>
              <div>
                <h2 className="text-lg font-bold leading-tight tracking-tight">
                  {PREMIUM_PLAN.planName}
                </h2>
                <p className="text-xs text-navy-200">
                  Полный доступ ко всем функциям SmartLawyer
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={handleClose}
              aria-label="Закрыть"
              className="rounded-full p-1.5 text-navy-200 transition-colors hover:bg-white/10 hover:text-white"
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
          <div className="mt-4 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-amber-300">
              9,900 ₸
            </span>
            <span className="text-sm font-medium text-navy-200">/ месяц</span>
          </div>
          <ul className="mt-4 space-y-2.5">
            {PREMIUM_PLAN.features.map((feature) => (
              <li key={feature} className="flex items-start gap-2.5 text-sm text-navy-50">
                <span className="mt-0.5 shrink-0 rounded-full bg-amber-400/15 p-0.5 ring-1 ring-amber-300/30">
                  <CheckIcon />
                </span>
                <span className="leading-snug">{feature}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="px-6 pb-5 pt-5">
          {claimStatus === 'active' ? (
            <div className="flex flex-col items-center py-6 text-center">
              <span
                className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 ring-1 ring-emerald-200"
                aria-hidden="true"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-7 w-7 text-emerald-500"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </span>
              <h3 className="mt-3 text-lg font-bold text-slate-800">Premium активен</h3>
              <p className="mt-1 max-w-xs text-sm text-slate-500">
                Спасибо! Все функции SmartLawyer Premium доступны без ограничений.
              </p>
            </div>
          ) : claimStatus === 'pending' && !showForm ? (
            <div className="flex flex-col items-center py-4 text-center">
              <span
                className="flex h-14 w-14 items-center justify-center rounded-full bg-amber-50 ring-1 ring-amber-200"
                aria-hidden="true"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-7 w-7 text-amber-500"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 8v4l2.5 2.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              </span>
              <h3 className="mt-3 text-lg font-bold text-slate-800">
                Заявка на проверке
              </h3>
              <p className="mt-1 max-w-sm text-sm leading-snug text-slate-500">
                Мы проверим поступление перевода с вашего номера и активируем
                Premium-доступ. Обычно проверка занимает не более 24 часов.
              </p>
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="mt-4 text-xs font-semibold text-navy-600 underline-offset-2 hover:underline"
              >
                Изменить номер
              </button>
            </div>
          ) : (
            <>
              <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <span className="inline-flex items-center gap-1.5 rounded-lg bg-[#F14635]/10 px-2 py-0.5 text-[11px] font-bold tracking-wide text-[#F14635]">
                    <svg
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.2"
                      className="h-3.5 w-3.5"
                      aria-hidden="true"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M13 5l7 7-7 7M5 12h15"
                      />
                    </svg>
                    Kaspi.kz · Переводы
                  </span>
                  <button
                    type="button"
                    onClick={copyPhone}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-600 transition-colors hover:border-slate-300 hover:text-slate-800"
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
                        d="M8 7V6a2 2 0 012-2h8a2 2 0 012 2v8a2 2 0 01-2 2h-1M6 8h8a2 2 0 012 2v8a2 2 0 01-2 2H6a2 2 0 01-2-2v-8a2 2 0 012-2z"
                      />
                    </svg>
                    {copied ? 'Скопировано' : 'Скопировать номер'}
                  </button>
                </div>
                <p className="mt-2.5 text-sm leading-relaxed text-slate-600">
                  {guideParts[0]}
                  <span className="font-bold text-navy-900">{phoneDisplay}</span>
                  {guideParts[1]}
                </p>
              </div>

              <div className="mt-5">
                <label
                  htmlFor="premium-phone"
                  className="block text-sm font-semibold text-slate-700"
                >
                  Введите ваш номер телефона, с которого совершена оплата
                </label>
                <input
                  ref={inputRef}
                  id="premium-phone"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  value={phone}
                  onChange={(e) => {
                    setPhone(e.target.value)
                    if (error) setError(null)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') submit()
                  }}
                  placeholder={PHONE_PLACEHOLDER}
                  className={`mt-2 w-full rounded-xl border bg-white px-3.5 py-3 text-sm text-slate-800 shadow-sm transition-all placeholder:text-slate-400 focus:outline-none focus:ring-2 ${
                    error
                      ? 'border-red-400 focus:border-red-400 focus:ring-red-100'
                      : 'border-slate-300 focus:border-navy-500 focus:ring-navy-100'
                  }`}
                />
                {error && (
                  <p className="mt-1.5 text-xs font-medium text-red-500">{error}</p>
                )}
                <button
                  type="button"
                  onClick={submit}
                  disabled={submitting}
                  className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-amber-400 to-amber-500 py-3.5 text-sm font-bold text-navy-950 shadow-md shadow-amber-400/30 transition-all duration-200 hover:from-amber-300 hover:to-amber-400 hover:shadow-lg active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {submitting ? (
                    <>
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        className="h-4 w-4 animate-spin"
                        aria-hidden="true"
                      >
                        <path
                          strokeLinecap="round"
                          d="M12 3a9 9 0 019 9"
                          className="opacity-80"
                        />
                      </svg>
                      Отправка заявки...
                    </>
                  ) : (
                    'Активировать Premium'
                  )}
                </button>
              </div>
            </>
          )}
        </div>

        <div className="border-t border-slate-100 px-6 pb-5 pt-4">
          <p className="text-center text-[11px] leading-snug text-slate-400">
            SmartLawyer — инструмент на основе искусственного интеллекта,
            генерирующий справочные ответы по действующему законодательству
            Республики Казахстан.
          </p>
          <button
            type="button"
            onClick={() => {
              handleClose()
              onOpenOffer()
            }}
            className="mx-auto mt-1.5 block text-[11px] font-semibold text-navy-600 underline-offset-2 hover:underline"
          >
            Публичная оферта и условия использования
          </button>
        </div>
      </div>
    </div>
  )
}

export default PremiumModal
