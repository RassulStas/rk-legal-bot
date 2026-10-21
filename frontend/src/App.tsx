import { useCallback, useEffect, useRef, useState } from 'react'
import AdminPanel from './components/AdminPanel'
import AuthForm from './components/AuthForm'
import AuthModal from './components/AuthModal'
import ChatInput from './components/ChatInput'
import EmptyState from './components/EmptyState'
import Header from './components/Header'
import LegalDocsModal from './components/LegalDocsModal'
import MessageBubble, { FREE_PREVIEW_CHARS, type ChatMessage } from './components/MessageBubble'
import PremiumModal, { type ClaimStatus } from './components/PremiumModal'
import ProfileDashboard from './components/ProfileDashboard'
import { reportAttribution } from './attribution'
import type { Profile } from './auth'
import { authHeaders, clearUserToken, getUserToken } from './auth'
import type { LegalDocId } from './config/legal_docs'
import { UI_STRINGS, type Language } from './i18n'

const WELCOME = (lang: Language): ChatMessage => ({
  role: 'assistant',
  content: UI_STRINGS[lang].welcome,
})

const SESSION_KEY = 'rk-legal-session-id'

// Set VITE_API_URL at build time to call the backend directly (e.g.
// VITE_API_URL=https://api.example.com npm run build). Unset = same-origin
// requests to /api, which is the default behind an nginx reverse proxy.
const API_BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '')

function getSessionId(): string {
  let id = localStorage.getItem(SESSION_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(SESSION_KEY, id)
  }
  return id
}

function getRoute(): string {
  return window.location.hash.replace(/^#\/?/, '')
}

function App() {
  const [language, setLanguage] = useState<Language>('ru')
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME('ru')])
  const [isStreaming, setIsStreaming] = useState(false)
  const [premiumOpen, setPremiumOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const [unlockDismissed, setUnlockDismissed] = useState(false)
  const [claimStatus, setClaimStatus] = useState<ClaimStatus>('none')
  const [legalDoc, setLegalDoc] = useState<LegalDocId | null>(null)
  const [starter, setStarter] = useState<{ text: string; nonce: number } | null>(null)
  const [route, setRoute] = useState(getRoute)
  const [userToken, setUserToken] = useState(() => getUserToken())
  const [profile, setProfile] = useState<Profile | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onHashChange = () => setRoute(getRoute())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  const refreshClaimStatus = useCallback(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/api/premium/status?session_id=${getSessionId()}`,
        { headers: authHeaders() },
      )
      if (!res.ok) return
      const body = (await res.json()) as { status?: string }
      setClaimStatus(
        body?.status === 'active' || body?.status === 'pending' ? body.status : 'none',
      )
    } catch {
      /* offline — keep the current status */
    }
  }, [])

  const refreshProfile = useCallback(async () => {
    if (!getUserToken()) {
      setProfile(null)
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/user/profile`, { headers: authHeaders() })
      if (res.status === 401) {
        clearUserToken()
        setUserToken(null)
        setProfile(null)
        return
      }
      if (!res.ok) return
      setProfile((await res.json()) as Profile)
    } catch {
      /* offline — keep the cached profile */
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/api/premium/status?session_id=${getSessionId()}`, {
      headers: authHeaders(),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((body: { status?: string } | null) => {
        if (cancelled || !body) return
        setClaimStatus(
          body.status === 'active' || body.status === 'pending' ? body.status : 'none',
        )
      })
      .catch(() => {
        /* offline — badge stays on the current status */
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    reportAttribution(API_BASE, getSessionId())
  }, [])

  useEffect(() => {
    void refreshProfile()
  }, [refreshProfile])

  // 1-second cadence while a claim is pending: the payment webhook flips the
  // claim server-side, and this poll is what unblurs the teaser within ~1s.
  useEffect(() => {
    if (claimStatus !== 'pending') return
    const timer = setInterval(refreshClaimStatus, 1_000)
    return () => clearInterval(timer)
  }, [claimStatus, refreshClaimStatus])

  function handleLanguageChange(lang: Language) {
    if (lang === language || isStreaming) return
    setLanguage(lang)
    setMessages((prev) => {
      const onlyWelcome = prev.length === 1 && prev[0].role === 'assistant'
      return onlyWelcome ? [WELCOME(lang)] : prev
    })
  }

  function handleAuthChange() {
    setUserToken(getUserToken())
    void refreshProfile()
    void refreshClaimStatus()
  }

  function unlockAfterAuth() {
    setMessages((prev) => prev.map((m) => (m.locked ? { ...m, locked: false } : m)))
    setUnlockDismissed(false)
    handleAuthChange()
  }

  const premiumActive = claimStatus === 'active' || Boolean(profile?.is_premium)

  // Only the greeting is in the list and no starter prompt has been picked, so
  // the landing hero owns the screen. A chip tap sets `starter`, which hides the
  // hero and reveals that prompt prefilled in the input bar — prefilled, not
  // sent, because an accidental tap must not burn the one free anonymous chat.
  const showEmptyState =
    !starter && messages.length === 1 && messages[0].role === 'assistant'

  // Payment auto-activation path: when the polled claim status flips to
  // 'active', any blurred teaser unblurs — no auth or page reload needed.
  useEffect(() => {
    if (!premiumActive) return
    setMessages((prev) =>
      prev.some((m) => m.locked)
        ? prev.map((m) => (m.locked ? { ...m, locked: false } : m))
        : prev,
    )
  }, [premiumActive])

  const sendMessage = useCallback(
    async (text: string) => {
      const history = messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({ role: m.role, content: m.content }))

      // Teaser gate: only anonymous, non-premium visitors get blurred responses.
      const lockEligible = !getUserToken() && !premiumActive

      setMessages((prev) => [
        ...prev,
        { role: 'user', content: text },
        { role: 'assistant', content: '' },
      ])
      setIsStreaming(true)

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({
            message: text,
            language,
            history,
            session_id: getSessionId(),
          }),
        })

        if (!res.ok) {
          let detail = `HTTP ${res.status}`
          let code = ''
          try {
            const body = await res.json()
            if (body?.detail) detail = body.detail
            code = body?.code ?? ''
          } catch {
            /* non-JSON error body */
          }
          if (res.status === 429 && code === 'free_limit_reached') {
            setPremiumOpen(true)
          }
          if (res.status === 429 && code === 'auth_required') {
            setAuthOpen(true)
          }
          throw new Error(detail)
        }

        const reader = res.body?.getReader()
        if (!reader) throw new Error('Streaming is not supported by this browser')

        const decoder = new TextDecoder()
        let buffer = ''

        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          const events = buffer.split('\n\n')
          buffer = events.pop() ?? ''

          for (const event of events) {
            const dataLine = event
              .split('\n')
              .find((line) => line.startsWith('data:'))
            if (!dataLine) continue
            const payload = dataLine.slice('data:'.length).trim()
            if (payload === '[DONE]') continue

            try {
              const parsed = JSON.parse(payload)
              if (parsed.error) throw new Error(parsed.error)
              if (parsed.text) {
                setMessages((prev) => {
                  const next = [...prev]
                  const last = next[next.length - 1]
                  if (last?.role === 'assistant') {
                    const content = last.content + parsed.text
                    next[next.length - 1] = {
                      ...last,
                      content,
                      locked:
                        last.locked ||
                        (lockEligible && content.length > FREE_PREVIEW_CHARS),
                    }
                  }
                  return next
                })
              }
            } catch (err) {
              if (err instanceof SyntaxError) continue
              throw err
            }
          }
        }
      } catch (err) {
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?.role === 'assistant' && last.content === '') {
            next.pop()
          }
          return [
            ...next,
            {
              role: 'error',
              content: `${UI_STRINGS[language].errorTitle}: ${err instanceof Error ? err.message : String(err)}`,
            },
          ]
        })
      } finally {
        setIsStreaming(false)
      }
    },
    [language, messages],
  )

  const analyzeContract = useCallback(
    async (file: File) => {
      const userNote = `[${UI_STRINGS[language].analysisTitle}: ${file.name}]`

      setMessages((prev) => [
        ...prev,
        { role: 'user', content: userNote },
        { role: 'assistant', content: '' },
      ])
      setIsStreaming(true)

      const form = new FormData()
      form.append('session_id', getSessionId())
      form.append('file', file)

      try {
        const res = await fetch(`${API_BASE}/api/analyze-contract`, {
          method: 'POST',
          headers: authHeaders(),
          body: form,
        })

        if (!res.ok) {
          if (res.status === 403) {
            setClaimStatus('none')
            setPremiumOpen(true)
            throw new Error(UI_STRINGS[language].attachBlocked)
          }
          let detail = `HTTP ${res.status}`
          try {
            const body = await res.json()
            if (body?.detail) detail = body.detail
          } catch {
            /* non-JSON error body */
          }
          throw new Error(detail)
        }

        const body = (await res.json()) as { filename?: string; analysis?: string }
        const analysis = body.analysis ?? ''
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?.role === 'assistant') {
            next[next.length - 1] = { ...last, content: analysis }
          }
          return next
        })
      } catch (err) {
        setMessages((prev) => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?.role === 'assistant' && last.content === '') {
            next.pop()
          }
          return [
            ...next,
            {
              role: 'error',
              content: `${UI_STRINGS[language].errorTitle}: ${err instanceof Error ? err.message : String(err)}`,
            },
          ]
        })
      } finally {
        setIsStreaming(false)
      }
    },
    [language],
  )

  if (route === 'admin') {
    return <AdminPanel apiBase={API_BASE} />
  }

  if (route === 'profile') {
    return (
      <div className="flex h-screen flex-col bg-slate-100 text-slate-800">
        <Header
          language={language}
          onLanguageChange={handleLanguageChange}
          claimStatus={claimStatus}
          onOpenCabinet={() => {
            window.location.hash = '/profile'
          }}
          cabinetActive
          onOpenPremium={() => {
            refreshClaimStatus()
            setPremiumOpen(true)
          }}
        />
        <main className="flex-1 overflow-y-auto bg-white">
          <ProfileDashboard
            language={language}
            apiBase={API_BASE}
            sessionId={getSessionId()}
            onOpenPremium={() => {
              refreshClaimStatus()
              setPremiumOpen(true)
            }}
            onAuthChange={handleAuthChange}
          />
        </main>
        <PremiumModal
          open={premiumOpen}
          apiBase={API_BASE}
          sessionId={getSessionId()}
          claimStatus={claimStatus}
          authToken={userToken}
          defaultPhone={profile?.phone}
          onClose={() => setPremiumOpen(false)}
          onOpenOffer={() => setLegalDoc('offer')}
          onClaimSubmitted={() => {
            setClaimStatus('pending')
            refreshClaimStatus()
            void refreshProfile()
          }}
        />
        {legalDoc && <LegalDocsModal docId={legalDoc} onClose={() => setLegalDoc(null)} />}
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col bg-slate-100 text-slate-800">
      <Header
        language={language}
        onLanguageChange={handleLanguageChange}
        claimStatus={claimStatus}
        onOpenCabinet={() => {
          window.location.hash = '/profile'
        }}
        cabinetActive={false}
        onOpenPremium={() => {
          refreshClaimStatus()
          setPremiumOpen(true)
        }}
      />
      <main
        ref={scrollRef}
        className="flex-1 overflow-y-auto scroll-smooth bg-white"
      >
        {showEmptyState ? (
          <div className="mx-auto flex min-h-full max-w-4xl flex-col px-4 py-6 sm:px-6">
            <EmptyState
              language={language}
              premiumActive={premiumActive}
              onAnalyzeContract={analyzeContract}
              onOpenPremium={() => {
                refreshClaimStatus()
                setPremiumOpen(true)
              }}
              onPickStarter={(prompt) =>
                setStarter((prev) => ({
                  text: prompt,
                  nonce: (prev?.nonce ?? 0) + 1,
                }))
              }
            />
          </div>
        ) : (
          <div className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6 sm:px-6">
            {messages.map((message, i) => (
              <div key={i} className="flex flex-col">
                <MessageBubble
                  message={message}
                  streaming={isStreaming && i === messages.length - 1}
                  copyLabels={{
                    copy: UI_STRINGS[language].copyAnswer,
                    copied: UI_STRINGS[language].copied,
                    failed: UI_STRINGS[language].copyFailed,
                  }}
                >
                  {message.locked && !userToken && !unlockDismissed && (
                    <AuthForm
                      apiBase={API_BASE}
                      sessionId={getSessionId()}
                      language={language}
                      title={UI_STRINGS[language].unlockTitle}
                      lead={UI_STRINGS[language].unlockLead}
                      onClose={() => setUnlockDismissed(true)}
                      onAuthenticated={unlockAfterAuth}
                    />
                  )}
                </MessageBubble>
                {message.locked && !userToken && unlockDismissed && (
                  <button
                    type="button"
                    onClick={() => setUnlockDismissed(false)}
                    className="ml-11 mt-1 flex w-fit items-center gap-1.5 rounded-full border border-navy-200 bg-navy-50 px-4 py-2 text-xs font-bold text-navy-700 transition-colors hover:bg-navy-100"
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
                        d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                      />
                    </svg>
                    {UI_STRINGS[language].unlockShowFull}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
      <ChatInput
        language={language}
        disabled={isStreaming}
        premiumActive={premiumActive}
        prefill={starter}
        onSend={sendMessage}
        onAnalyzeContract={analyzeContract}
        onOpenPremium={() => {
          refreshClaimStatus()
          setPremiumOpen(true)
        }}
        onOpenLegalDoc={setLegalDoc}
      />
      <PremiumModal
        open={premiumOpen}
        apiBase={API_BASE}
        sessionId={getSessionId()}
        claimStatus={claimStatus}
        authToken={userToken}
        defaultPhone={profile?.phone}
        onClose={() => setPremiumOpen(false)}
        onOpenOffer={() => setLegalDoc('offer')}
        onClaimSubmitted={() => {
          setClaimStatus('pending')
          refreshClaimStatus()
          void refreshProfile()
        }}
      />
      <AuthModal
        open={authOpen}
        apiBase={API_BASE}
        sessionId={getSessionId()}
        language={language}
        onClose={() => setAuthOpen(false)}
        onAuthenticated={() => {
          setAuthOpen(false)
          unlockAfterAuth()
        }}
      />
      {legalDoc && <LegalDocsModal docId={legalDoc} onClose={() => setLegalDoc(null)} />}
    </div>
  )
}

export default App
