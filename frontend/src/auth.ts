// Client-side session for the Личный кабинет: an opaque bearer token issued by
// POST /api/auth/verify. Stored in localStorage so it survives reloads; every
// API layer merges authHeaders() into requests to bind the chatroom session,
// Premium status and contract archive to the signed-in profile.

const TOKEN_KEY = 'rk-legal-user-token'

export function getUserToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setUserToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearUserToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function authHeaders(): Record<string, string> {
  const token = getUserToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export type Profile = {
  user_id: number
  phone: string
  tier_status: 'free' | 'premium'
  is_premium: boolean
  active_until: string | null
  documents_count: number
  sessions_count: number
  created_at: string | null
}

export type DocumentMeta = {
  doc_id: number
  filename: string
  created_at: string
  preview: string
}

export type DocumentDetail = DocumentMeta & {
  analysis_summary: string
}
