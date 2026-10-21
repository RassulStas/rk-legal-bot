// Landing attribution beacon. The SPA used to keep the ad-click query string to
// itself, so a paid click could never be tied to the session it produced — and a
// visitor who bounced without typing left no row in the database at all.

// Click IDs and UTM tags that earn their own column server-side. Everything else
// (gbraid, wbraid, yclid, fbclid) still survives inside the raw landing_query.
const PARAM_FIELDS = [
  ['gclid', 'gclid'],
  ['gad_campaignid', 'gad_campaign_id'],
  ['gad_source', 'gad_source'],
  ['utm_source', 'utm_source'],
  ['utm_medium', 'utm_medium'],
  ['utm_campaign', 'utm_campaign'],
  ['utm_content', 'utm_content'],
  ['utm_term', 'utm_term'],
] as const

export function reportAttribution(apiBase: string, sessionId: string): void {
  const search = window.location.search
  const params = new URLSearchParams(search)
  const payload: Record<string, string> = {}
  for (const [param, field] of PARAM_FIELDS) {
    const value = params.get(param)
    if (value) payload[field] = value
  }
  if (search) payload.landing_query = search
  if (document.referrer) payload.referrer = document.referrer

  // Sent on every boot rather than only when params are present. The backend
  // keeps the first non-empty value, so a repeat visit cannot clobber the click
  // that acquired it, and a beacon lost to a flaky mobile network is retried
  // from the same URL on the next load. keepalive lets it finish even if the
  // visitor closes the tab immediately — which is most of the bounce population.
  void fetch(`${apiBase}/api/session/track`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, ...payload }),
    keepalive: true,
  }).catch(() => {
    /* best-effort: attribution must never block or break the app */
  })
}
