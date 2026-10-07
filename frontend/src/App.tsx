import { useCallback, useEffect, useRef, useState } from 'react'
import AdminPanel from './components/AdminPanel'
import ChatInput from './components/ChatInput'
import Header from './components/Header'
import LegalDocsModal from './components/LegalDocsModal'
import MessageBubble, { type ChatMessage } from './components/MessageBubble'
import PremiumModal, { type ClaimStatus } from './components/PremiumModal'
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
  const [claimStatus, setClaimStatus] = useState<ClaimStatus>('none')
  const [legalDoc, setLegalDoc] = useState<LegalDocId | null>(null)
  const [route, setRoute] = useState(getRoute)
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

  useEffect(() => {
    let cancelled = false
    fetch(`${API_BASE}/api/premium/status?session_id=${getSessionId()}`)
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
    if (claimStatus !== 'pending') return
    const timer = setInterval(refreshClaimStatus, 20_000)
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

  const sendMessage = useCallback(
    async (text: string) => {
      const history = messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({ role: m.role, content: m.content }))

      setMessages((prev) => [
        ...prev,
        { role: 'user', content: text },
        { role: 'assistant', content: '' },
      ])
      setIsStreaming(true)

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: text,
            language,
            history,
            session_id: getSessionId(),
          }),
        })

        if (!res.ok) {
          let detail = `HTTP ${res.status}`
          try {
            const body = await res.json()
            if (body?.detail) detail = body.detail
          } catch {
            /* non-JSON error body */
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
                    next[next.length - 1] = { ...last, content: last.content + parsed.text }
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

  return (
    <div className="flex h-screen flex-col bg-slate-100 text-slate-800">
      <Header
        language={language}
        onLanguageChange={handleLanguageChange}
        claimStatus={claimStatus}
        onOpenPremium={() => {
          refreshClaimStatus()
          setPremiumOpen(true)
        }}
      />
      <main
        ref={scrollRef}
        className="flex-1 overflow-y-auto scroll-smooth bg-white"
      >
        <div className="mx-auto flex max-w-4xl flex-col gap-5 px-4 py-6 sm:px-6">
          {messages.map((message, i) => (
            <MessageBubble
              key={i}
              message={message}
              streaming={isStreaming && i === messages.length - 1}
            />
          ))}
        </div>
      </main>
      <ChatInput
        language={language}
        disabled={isStreaming}
        premiumActive={claimStatus === 'active'}
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
        onClose={() => setPremiumOpen(false)}
        onOpenOffer={() => setLegalDoc('offer')}
        onClaimSubmitted={() => {
          setClaimStatus('pending')
          refreshClaimStatus()
        }}
      />
      {legalDoc && <LegalDocsModal docId={legalDoc} onClose={() => setLegalDoc(null)} />}
    </div>
  )
}

export default App
