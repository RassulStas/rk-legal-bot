import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export type MessageRole = 'user' | 'assistant' | 'error'

export type ChatMessage = {
  role: MessageRole
  content: string
}

type MessageBubbleProps = {
  message: ChatMessage
  streaming?: boolean
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

function MessageBubble({ message, streaming }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isError = message.role === 'error'

  return (
    <div className={`flex gap-2.5 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && !isError && <ScalesAvatar />}
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm md:max-w-[75%] ${
          isUser
            ? 'rounded-br-md bg-gradient-to-br from-navy-800 to-navy-900 text-white'
            : isError
              ? 'rounded-bl-md border border-red-200 bg-red-50 text-red-700'
              : 'rounded-bl-md border border-slate-200/80 bg-slate-100 text-slate-800'
        }`}
      >
        {message.content === '' && streaming ? (
          <TypingDots />
        ) : isUser ? (
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none prose-p:my-2 prose-strong:text-slate-900 prose-a:font-medium prose-a:text-navy-700 prose-pre:bg-slate-950 prose-code:text-navy-800">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
        {streaming && message.content !== '' && (
          <span className="ml-0.5 inline-block h-3.5 w-2 animate-pulse rounded-sm bg-navy-500 align-text-bottom" />
        )}
      </div>
    </div>
  )
}

export default MessageBubble
