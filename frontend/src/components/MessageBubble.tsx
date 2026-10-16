import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export type MessageRole = 'user' | 'assistant' | 'error'

export type ChatMessage = {
  role: MessageRole
  content: string
  // Free-tier teaser: the response past the preview cut stays blurred until
  // the visitor completes phone verification (App clears the flag on auth).
  locked?: boolean
}

export type CopyLabels = { copy: string; copied: string; failed: string }

// Anonymous first-response teaser: the sharp region targets the first two
// paragraph blocks (direct answer + cited articles); everything past the cut
// is rendered blurred behind the unlock card.
export const FREE_PREVIEW_CHARS = 800

type MessageBubbleProps = {
  message: ChatMessage
  streaming?: boolean
  copyLabels?: CopyLabels
  children?: ReactNode
}

// Teaser cut = end of the second complete block (direct answer + cited
// articles stay sharp; risk audits and details blur). When that boundary is
// absurdly far, fall back to the last boundary near the threshold; when the
// text has no block structure at all, hard cut at FREE_PREVIEW_CHARS.
function teaserCut(content: string): number {
  if (content.length <= FREE_PREVIEW_CHARS) return content.length
  const boundaries = [
    ...content.matchAll(/\n\n|\n(?=[-*] )|\n(?=\d+\. )/g),
  ].map((m) => m.index + (m[0] === '\n\n' ? 2 : 1))
  boundaries.sort((a, b) => a - b)
  const second = boundaries[1]
  if (second !== undefined && second <= FREE_PREVIEW_CHARS + 300) return second
  const last = boundaries.filter((b) => b <= FREE_PREVIEW_CHARS + 300).pop()
  return last !== undefined && last >= 300 ? last : FREE_PREVIEW_CHARS
}

function TypingDots() {
  return (
    <span className="inline-flex gap-1 py-1" aria-label="typing">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-500"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </span>
  )
}

function ScalesAvatar() {
  return (
    <div
      className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-navy-800 text-white shadow-sm ring-1 ring-navy-200"
      aria-hidden="true"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        className="h-4 w-4"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 3v18M3 7l9-4 9 4M4 7v4c0 1.66 3.58 3 8 3s8-1.34 8-3V7M4 15v2c0 1.66 3.58 3 8 3s8-1.34 8-3v-2"
        />
      </svg>
    </div>
  )
}

function MarkdownBlock({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none prose-p:my-2 prose-strong:text-slate-900 prose-a:font-medium prose-a:text-navy-700 prose-pre:bg-slate-950 prose-code:text-navy-800">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  )
}

// Markdown → plain text for the copy buffer: strips emphasis, headers, quotes,
// list/HR/link syntax so pasted answers read as clean prose. Links keep their
// URL in parentheses (legal answers cite adilet.zan.kz) and fenced code blocks
// survive verbatim via placeholders. Single underscores are deliberately kept —
// they are near-nonexistent as RU/KK italics but common in identifiers.
export function stripMarkdown(text: string): string {
  const fences: string[] = []
  let out = text.replace(/```[^\n]*\n?([\s\S]*?)(?:```|$)/g, (_, code: string) => {
    fences.push(code.replace(/\n$/, ''))
    return `\u0000${fences.length - 1}\u0000`
  })
  out = out
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g, '$1 ($2)')
    .replace(/^[ \t]{0,3}#{1,6}[ \t]+/gm, '')
    .replace(/^[ \t]{0,3}>[ \t]?/gm, '')
    .replace(/^[ \t]{0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$/gm, '')
    .replace(/^([ \t]*)[-*+][ \t]+/gm, '$1- ')
    .replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, '$2')
    .replace(/\*(?=\S)([^*\n]*\S)\*/g, '$1')
    .replace(/`([^`\n]+)`/g, '$1')
  out = out.replace(/\u0000(\d+)\u0000/g, (_, i: string) => fences[Number(i)] ?? '')
  return out.replace(/\n{3,}/g, '\n\n').trim()
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    try {
      return document.execCommand('copy')
    } catch {
      return false
    } finally {
      ta.remove()
    }
  }
}

function CopyIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-3.5 w-3.5"
      aria-hidden="true"
    >
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"
      />
    </svg>
  )
}

function CopyButton({ text, labels }: { text: string; labels: CopyLabels }) {
  const [status, setStatus] = useState<'idle' | 'done' | 'failed'>('idle')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const onClick = async () => {
    const ok = await copyText(stripMarkdown(text))
    window.clearTimeout(timer.current)
    setStatus(ok ? 'done' : 'failed')
    timer.current = window.setTimeout(() => setStatus('idle'), 2000)
  }

  return (
    <button
      type="button"
      onClick={() => void onClick()}
      className={`mt-1 inline-flex w-fit items-center gap-1 rounded-md px-1.5 py-0.5 text-xs transition-colors ${
        status === 'done'
          ? 'text-emerald-600'
          : status === 'failed'
            ? 'text-red-500'
            : 'text-slate-500 hover:bg-slate-200/70 hover:text-slate-700'
      }`}
    >
      <CopyIcon />
      {status === 'done' ? labels.copied : status === 'failed' ? labels.failed : labels.copy}
    </button>
  )
}

function MessageBubble({ message, streaming, copyLabels, children }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isError = message.role === 'error'

  let body: ReactNode
  if (message.content === '' && streaming) {
    body = <TypingDots />
  } else if (isUser) {
    body = <p className="whitespace-pre-wrap break-words">{message.content}</p>
  } else if (message.locked) {
    const cut = teaserCut(message.content)
    const head = message.content.slice(0, cut)
    const tail = message.content.slice(cut)
    body = (
      <div className="relative">
        <MarkdownBlock content={head} />
        <div className="relative">
          <div
            className="pointer-events-none select-none transition-[filter] duration-500 [filter:blur(5px)]"
            aria-hidden="true"
          >
            <MarkdownBlock content={tail} />
          </div>
          {children && (
            <div className="absolute inset-x-0 top-1/2 z-10 flex -translate-y-1/2 justify-center px-2">
              {children}
            </div>
          )}
        </div>
      </div>
    )
  } else {
    body = <MarkdownBlock content={message.content} />
  }

  // No copy affordance while locked — the blurred tail is paywalled content.
  const showCopy =
    !isUser && !isError && !streaming && !message.locked && message.content !== '' && !!copyLabels

  return (
    <div className={`flex gap-2.5 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && !isError && <ScalesAvatar />}
      <div className="flex min-w-0 max-w-[85%] flex-col md:max-w-[75%]">
        <div
          className={`w-fit rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
            isUser
              ? 'rounded-br-md bg-gradient-to-br from-navy-800 to-navy-900 text-white'
              : isError
                ? 'rounded-bl-md border border-red-200 bg-red-50 text-red-700'
                : 'rounded-bl-md border border-slate-200/80 bg-slate-100 text-slate-800'
          }`}
        >
          {body}
          {streaming && message.content !== '' && (
            <span className="ml-0.5 inline-block h-3.5 w-2 animate-pulse rounded-sm bg-navy-500 align-text-bottom" />
          )}
        </div>
        {showCopy && copyLabels && <CopyButton text={message.content} labels={copyLabels} />}
      </div>
    </div>
  )
}

export default MessageBubble
