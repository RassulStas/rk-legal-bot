import { useCallback, useEffect, useRef, useState } from 'react'

type AdminPanelProps = {
  apiBase: string
}

type AdminClaim = {
  claim_id: number
  session_id: string
  phone: string
  status: string
  created_at: string | null
}

type StatusFilter = 'pending' | 'active' | 'all'

const TOKEN_KEY = 'rk-admin-token'

const STATUS_LABEL: Record<string, string> = {
  pending: 'Ожидает',
  active: 'Активен',
  rejected: 'Отклонена',
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function AdminPanel({ apiBase }: AdminPanelProps) {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) ?? '')
  const [filter, setFilter] = useState<StatusFilter>('pending')
  const [claims, setClaims] = useState<AdminClaim[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmingId, setConfirmingId] = useState<number | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(
    async (activeToken: string, activeFilter: StatusFilter) => {
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(`${apiBase}/api/admin/claims?status=${activeFilter}`, {
          headers: { Authorization: `Bearer ${activeToken}` },
        })
        if (res.status === 404) {
          sessionStorage.removeItem(TOKEN_KEY)
          setError('Неверный токен администратора (или доступ запрещён).')
          setClaims([])
          return
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const body = (await res.json()) as { claims?: AdminClaim[] }
        setClaims(body.claims ?? [])
      } catch {
        setError('Не удалось загрузить заявки. Проверьте соединение и попробуйте снова.')
      } finally {
        setLoading(false)
      }
    },
    [apiBase],
  )

  useEffect(() => {
    const saved = sessionStorage.getItem(TOKEN_KEY)
    if (!saved) return
    let cancelled = false
    fetch(`${apiBase}/api/admin/claims?status=pending`, {
      headers: { Authorization: `Bearer ${saved}` },
    })
      .then(async (res) => {
        if (cancelled) return
        if (res.status === 404) {
          sessionStorage.removeItem(TOKEN_KEY)
          setError('Неверный токен администратора (или доступ запрещён).')
          return
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const body = (await res.json()) as { claims?: AdminClaim[] }
        setClaims(body.claims ?? [])
      })
      .catch(() => {
        if (!cancelled) {
          setError('Не удалось загрузить заявки. Проверьте соединение и попробуйте снова.')
        }
      })
    return () => {
      cancelled = true
      if (confirmTimer.current) clearTimeout(confirmTimer.current)
    }
  }, [apiBase])

  function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = token.trim()
    if (!trimmed) return
    sessionStorage.setItem(TOKEN_KEY, trimmed)
    load(trimmed, filter)
  }

  function handleLogout() {
    sessionStorage.removeItem(TOKEN_KEY)
    setToken('')
    setClaims([])
    setError(null)
    setNotice(null)
  }

  function handleFilterChange(next: StatusFilter) {
    setFilter(next)
    const saved = sessionStorage.getItem(TOKEN_KEY)
    if (saved) load(saved, next)
  }

  function handleRefresh() {
    const saved = sessionStorage.getItem(TOKEN_KEY)
    if (saved) load(saved, filter)
  }

  function askConfirm(claim: AdminClaim) {
    setConfirmingId(claim.claim_id)
    if (confirmTimer.current) clearTimeout(confirmTimer.current)
    confirmTimer.current = setTimeout(() => setConfirmingId(null), 4000)
  }

  async function approve(claim: AdminClaim) {
    if (confirmTimer.current) clearTimeout(confirmTimer.current)
    setConfirmingId(null)
    setBusyId(claim.claim_id)
    setNotice(null)
    try {
      const res = await fetch(`${apiBase}/api/admin/claims/${claim.claim_id}/approve`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${sessionStorage.getItem(TOKEN_KEY) ?? ''}` },
      })
      if (res.status === 404) {
        sessionStorage.removeItem(TOKEN_KEY)
        setError('Неверный токен администратора (или доступ запрещён).')
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setNotice(`Premium активирован для ${claim.phone}`)
      handleRefresh()
    } catch {
      setError('Не удалось активировать заявку. Попробуйте ещё раз.')
    } finally {
      setBusyId(null)
    }
  }

  const authorized = sessionStorage.getItem(TOKEN_KEY) !== null

  return (
    <div className="min-h-screen bg-navy-950 text-slate-100">
      <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white">
              SmartLawyer Admin
            </h1>
            <p className="mt-1 text-xs text-navy-200">
              Заявки на Premium-доступ — ручная проверка переводов Kaspi
            </p>
          </div>
          {authorized && (
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-semibold text-navy-100 transition-colors hover:bg-white/10"
            >
              Сменить токен
            </button>
          )}
        </div>

        {!authorized ? (
          <form
            onSubmit={handleLogin}
            className="mt-8 rounded-2xl border border-white/10 bg-white/5 p-5"
          >
            <label htmlFor="admin-token" className="block text-sm font-semibold text-white">
              Токен администратора
            </label>
            <input
              id="admin-token"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Введите ADMIN_TOKEN"
              autoComplete="off"
              className="mt-2 w-full rounded-xl border border-white/15 bg-navy-900 px-3.5 py-3 text-sm text-white placeholder:text-navy-300 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-400/20"
            />
            {error && <p className="mt-2 text-xs font-medium text-red-300">{error}</p>}
            <button
              type="submit"
              disabled={!token.trim()}
              className="mt-4 w-full rounded-xl bg-gradient-to-r from-amber-400 to-amber-500 py-3 text-sm font-bold text-navy-950 transition-all hover:from-amber-300 hover:to-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Войти
            </button>
          </form>
        ) : (
          <div className="mt-6">
            <div className="flex flex-wrap items-center gap-2">
              {(['pending', 'active', 'all'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => handleFilterChange(value)}
                  className={`rounded-full px-3.5 py-1.5 text-xs font-bold transition-all ${
                    filter === value
                      ? 'bg-amber-400 text-navy-950'
                      : 'border border-white/15 bg-white/5 text-navy-100 hover:bg-white/10'
                  }`}
                >
                  {value === 'pending' ? 'Ожидают' : value === 'active' ? 'Активные' : 'Все'}
                </button>
              ))}
              <button
                type="button"
                onClick={handleRefresh}
                disabled={loading}
                className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/5 px-3.5 py-1.5 text-xs font-semibold text-navy-100 transition-colors hover:bg-white/10 disabled:opacity-50"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`}
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M4 4v5h5M20 20v-5h-5M5.5 9A7.5 7.5 0 0119 7.5M18.5 15A7.5 7.5 0 015 16.5"
                  />
                </svg>
                Обновить
              </button>
            </div>

            {error && (
              <p className="mt-4 rounded-xl border border-red-400/30 bg-red-400/10 px-4 py-2.5 text-xs font-medium text-red-200">
                {error}
              </p>
            )}
            {notice && (
              <p className="mt-4 rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-2.5 text-xs font-semibold text-emerald-200">
                {notice}
              </p>
            )}

            <div className="mt-4 space-y-3">
              {loading && claims.length === 0 ? (
                <p className="py-10 text-center text-sm text-navy-200">Загрузка…</p>
              ) : claims.length === 0 ? (
                <p className="py-10 text-center text-sm text-navy-200">
                  Заявок с этим статусом нет.
                </p>
              ) : (
                claims.map((claim) => (
                  <div
                    key={claim.claim_id}
                    className="flex flex-col gap-3 rounded-2xl border border-white/10 bg-white/5 p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div>
                      <div className="flex items-center gap-2.5">
                        <span className="font-mono text-base font-bold tracking-tight text-white">
                          {claim.phone}
                        </span>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                            claim.status === 'active'
                              ? 'bg-emerald-400/15 text-emerald-200'
                              : claim.status === 'pending'
                                ? 'bg-amber-400/15 text-amber-200'
                                : 'bg-slate-400/15 text-slate-300'
                          }`}
                        >
                          {STATUS_LABEL[claim.status] ?? claim.status}
                        </span>
                      </div>
                      <p className="mt-1 text-xs text-navy-200">
                        Заявка №{claim.claim_id} · {formatDate(claim.created_at)}
                      </p>
                    </div>
                    {claim.status === 'pending' &&
                      (confirmingId === claim.claim_id ? (
                        <button
                          type="button"
                          onClick={() => approve(claim)}
                          disabled={busyId === claim.claim_id}
                          className="shrink-0 rounded-xl bg-emerald-500 px-5 py-2.5 text-xs font-bold text-white shadow-md shadow-emerald-500/30 transition-all hover:bg-emerald-400 active:scale-[0.98] disabled:opacity-60"
                        >
                          {busyId === claim.claim_id ? 'Активация…' : 'Подтвердить активацию'}
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => askConfirm(claim)}
                          className="shrink-0 rounded-xl bg-gradient-to-r from-amber-400 to-amber-500 px-5 py-2.5 text-xs font-bold text-navy-950 shadow-md shadow-amber-400/20 transition-all hover:from-amber-300 hover:to-amber-400 active:scale-[0.98]"
                        >
                          [ Approve ]
                        </button>
                      ))}
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        <a
          href="#"
          onClick={(e) => {
            e.preventDefault()
            window.location.hash = ''
          }}
          className="mt-10 inline-block text-xs font-semibold text-navy-200 underline-offset-2 hover:text-white hover:underline"
        >
          ← Вернуться в чат
        </a>
      </div>
    </div>
  )
}

export default AdminPanel
