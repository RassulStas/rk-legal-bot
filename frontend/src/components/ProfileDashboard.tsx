import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  authHeaders,
  clearUserToken,
  getUserToken,
  type DocumentDetail,
  type DocumentMeta,
  type Profile,
} from '../auth'
import { UI_STRINGS, type Language } from '../i18n'
import AuthForm from './AuthForm'

type ProfileDashboardProps = {
  language: Language
  apiBase: string
  sessionId: string
  onOpenPremium: () => void
  onAuthChange: (authenticated: boolean) => void
}

function formatDate(iso: string | null, language: Language): string {
  if (!iso) return '—'
  const locale = language === 'kk' ? 'kk-KZ' : 'ru-RU'
  return new Date(iso).toLocaleDateString(locale, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

function formatDateTime(iso: string, language: Language): string {
  const locale = language === 'kk' ? 'kk-KZ' : 'ru-RU'
  return new Date(iso).toLocaleString(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function daysLeft(activeUntil: string | null, now: number): number | null {
  if (!activeUntil) return null
  const diff = new Date(activeUntil).getTime() - now
  return diff > 0 ? Math.ceil(diff / 86_400_000) : 0
}

function ProfileDashboard({
  language,
  apiBase,
  sessionId,
  onOpenPremium,
  onAuthChange,
}: ProfileDashboardProps) {
  const s = UI_STRINGS[language]
  const [authenticated, setAuthenticated] = useState(() => getUserToken() !== null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [profileError, setProfileError] = useState(false)
  const [documents, setDocuments] = useState<DocumentMeta[] | null>(null)
  const [activeDoc, setActiveDoc] = useState<DocumentDetail | null>(null)
  const [docLoading, setDocLoading] = useState(false)

  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(timer)
  }, [])

  const loadProfile = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/user/profile`, { headers: authHeaders() })
      if (res.status === 401) {
        clearUserToken()
        setAuthenticated(false)
        setProfile(null)
        onAuthChange(false)
        return
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = (await res.json()) as Profile
      setProfile(body)
      setAuthenticated(true)
      setProfileError(false)
      onAuthChange(true)
    } catch {
      setProfileError(true)
    }
  }, [apiBase, onAuthChange])

  const loadDocuments = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/user/documents`, { headers: authHeaders() })
      if (!res.ok) return
      const body = (await res.json()) as { documents?: DocumentMeta[] }
      setDocuments(body.documents ?? [])
    } catch {
      /* offline — keep the previous list */
    }
  }, [apiBase])

  useEffect(() => {
    if (!getUserToken()) {
      setAuthenticated(false)
      setProfile(null)
      return
    }
    void loadProfile()
    void loadDocuments()
  }, [loadProfile, loadDocuments])

  const refresh = useCallback(() => {
    void loadProfile()
    void loadDocuments()
  }, [loadProfile, loadDocuments])

  const openDocument = useCallback(
    async (docId: number) => {
      setDocLoading(true)
      try {
        const res = await fetch(`${apiBase}/api/user/documents/${docId}`, {
          headers: authHeaders(),
        })
        if (!res.ok) return
        const body = (await res.json()) as DocumentDetail
        setActiveDoc(body)
      } finally {
        setDocLoading(false)
      }
    },
    [apiBase],
  )

  function logout() {
    clearUserToken()
    setAuthenticated(false)
    setProfile(null)
    setDocuments(null)
    setActiveDoc(null)
    onAuthChange(false)
  }

  const remainingDays = useMemo(
    () => (profile?.is_premium ? daysLeft(profile.active_until, now) : null),
    [profile, now],
  )

  if (!authenticated) {
    return (
      <div className="flex-1 overflow-y-auto bg-white">
        <div className="mx-auto flex max-w-md flex-col px-4 py-10 sm:px-6">
          <AuthForm
            apiBase={apiBase}
            sessionId={sessionId}
            language={language}
            onAuthenticated={() => {
              onAuthChange(true)
              refresh()
            }}
            onBackToChat={() => {
              window.location.hash = '/'
            }}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto bg-slate-100">
      <div className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6 sm:px-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold tracking-tight text-navy-900">{s.cabinet}</h2>
            <p className="text-xs text-slate-500">{s.cabinetSubtitle}</p>
          </div>
          <button
            type="button"
            onClick={logout}
            className="rounded-full border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:border-slate-400 hover:text-slate-800"
          >
            {s.logout}
          </button>
        </div>

        {profileError && (
          <button
            type="button"
            onClick={refresh}
            className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-left text-sm text-amber-800"
          >
            Нет связи с сервером — нажмите, чтобы повторить.
          </button>
        )}

        {/* --- Профиль --- */}
        <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h3 className="text-sm font-bold uppercase tracking-wide text-slate-400">
            {s.profileBlock}
          </h3>
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <span
              className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-navy-700 to-navy-900 text-lg font-bold text-white"
              aria-hidden="true"
            >
              {profile?.phone.slice(-4) ?? '····'}
            </span>
            <div className="min-w-0">
              <p className="truncate text-lg font-bold tracking-tight text-slate-800">
                {profile?.phone ?? '—'}
              </p>
              <p className="text-xs text-slate-500">ID: {profile?.user_id ?? '—'}</p>
            </div>
            <dl className="ml-auto flex gap-6 text-sm">
              <div>
                <dt className="text-xs text-slate-400">{s.memberSince}</dt>
                <dd className="font-semibold text-slate-700">
                  {formatDate(profile?.created_at ?? null, language)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">{s.linkedSessions}</dt>
                <dd className="font-semibold text-slate-700">{profile?.sessions_count ?? 0}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-400">{s.documentsCount}</dt>
                <dd className="font-semibold text-slate-700">{profile?.documents_count ?? 0}</dd>
              </div>
            </dl>
          </div>
        </section>

        {/* --- Управление подпиской --- */}
        <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h3 className="text-sm font-bold uppercase tracking-wide text-slate-400">
            {s.subscriptionBlock}
          </h3>
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <span
              className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-sm font-bold ${
                profile?.is_premium
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : 'border-amber-200 bg-amber-50 text-amber-700'
              }`}
            >
              <span
                className={`h-2 w-2 rounded-full ${profile?.is_premium ? 'bg-emerald-500' : 'bg-amber-400'}`}
                aria-hidden="true"
              />
              {profile?.is_premium ? s.tariffPremium : s.tariffFree}
            </span>
            {profile?.is_premium && remainingDays !== null && (
              <span className="text-sm text-slate-600">
                {s.premiumActiveUntil.replace(
                  '{date}',
                  formatDate(profile.active_until, language),
                )}
                <span className="ml-2 rounded-full bg-navy-50 px-2.5 py-0.5 text-xs font-bold text-navy-700">
                  {s.daysLeft.replace('{n}', String(remainingDays))}
                </span>
              </span>
            )}
            {!profile?.is_premium && (
              <button
                type="button"
                onClick={onOpenPremium}
                className="ml-auto rounded-2xl bg-gradient-to-r from-amber-400 to-amber-500 px-5 py-2.5 text-sm font-bold text-navy-950 shadow-md shadow-amber-400/30 transition-all duration-200 hover:from-amber-300 hover:to-amber-400 active:scale-[0.98]"
              >
                {s.activatePremium}
              </button>
            )}
          </div>
        </section>

        {/* --- Архив договоров --- */}
        <section className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <h3 className="text-sm font-bold uppercase tracking-wide text-slate-400">
            {s.archiveBlock}
          </h3>
          {documents === null ? (
            <p className="mt-4 text-sm text-slate-400">…</p>
          ) : documents.length === 0 ? (
            <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center">
              <p className="text-sm font-medium text-slate-600">{s.noDocuments}</p>
              <p className="mt-1 text-xs text-slate-400">{s.noDocumentsHint}</p>
            </div>
          ) : (
            <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
              <table className="w-full text-left text-sm">
                <tbody>
                  {documents.map((doc) => (
                    <tr
                      key={doc.doc_id}
                      className="cursor-pointer border-b border-slate-100 transition-colors last:border-0 hover:bg-navy-50/60"
                      onClick={() => void openDocument(doc.doc_id)}
                    >
                      <td className="px-4 py-3">
                        <p className="max-w-[16rem] truncate font-semibold text-slate-700">
                          {doc.filename}
                        </p>
                        <p className="mt-0.5 line-clamp-1 text-xs text-slate-400">
                          {doc.preview}
                        </p>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400">
                        {formatDateTime(doc.created_at, language)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className="inline-flex items-center gap-1 text-xs font-bold text-navy-600">
                          {s.openReadout}
                          <svg
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            className="h-3.5 w-3.5"
                            aria-hidden="true"
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                          </svg>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {/* Readout viewer */}
      {activeDoc && (
        <div
          className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4"
          role="dialog"
          aria-modal="true"
          aria-label={activeDoc.filename}
        >
          <div className="absolute inset-0 bg-navy-950/60 backdrop-blur-sm" onClick={() => setActiveDoc(null)} />
          <div className="relative flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl">
            <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
              <div className="min-w-0">
                <h3 className="truncate text-base font-bold tracking-tight text-navy-900">
                  {activeDoc.filename}
                </h3>
                <p className="text-xs text-slate-400">
                  {formatDateTime(activeDoc.created_at, language)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setActiveDoc(null)}
                aria-label="Закрыть"
                className="rounded-full p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5" aria-hidden="true">
                  <path strokeLinecap="round" d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </div>
            <div className="overflow-y-auto px-6 py-4">
              <div className="prose prose-sm max-w-none text-slate-700">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{activeDoc.analysis_summary}</ReactMarkdown>
              </div>
            </div>
          </div>
        </div>
      )}
      {docLoading && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/40">
          <span className="rounded-full bg-white px-4 py-2 text-sm font-semibold text-navy-800 shadow-lg">
            …
          </span>
        </div>
      )}
    </div>
  )
}

export default ProfileDashboard
