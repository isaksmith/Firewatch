export const BASE = import.meta.env.VITE_API_BASE ?? '/api'

export type Recommendation = 'escalate' | 'investigate' | 'monitor'
export type Status = 'new' | 'acknowledged' | 'escalated' | 'dismissed' | 'closed'
export type ActionName = 'acknowledge' | 'escalate' | 'dismiss' | 'reopen'

export interface Reason {
  feature: string
  label: string
  contribution: number
}

export interface AlertSummary {
  id: number
  lat: number
  lon: number
  place_label: string
  county: string | null
  first_seen: string
  last_seen: string
  status: Status
  score: number
  recommendation: Recommendation
  score_trend: number[]
  degraded: boolean
  guardrail: string | null
  suppression: 'logged_burn' | 'static_source' | 'likely_prescribed' | 'low_signal' | null
  reraised: boolean
  sources: Record<string, number>
  top_reason: string | null
  is_sample: boolean
  sample_slug: string | null
}

export interface AlertsResponse {
  mode: 'sample' | 'live'
  generated_at: string
  alerts: AlertSummary[]
  suppressed: { total: number; logged_burn: number; static_source: number; likely_prescribed: number; low_signal: number }
}

export interface Detection {
  id: number
  source: string
  satellite: string
  lat: number
  lon: number
  acq_time: string
  frp_mw: number | null
  confidence: string
  brightness_k: number | null
  daynight: string | null
}

export interface AlertDetail extends AlertSummary {
  features: Record<string, number>
  weather: {
    wind_kmh?: number
    gust_kmh?: number
    wind_dir_deg?: number
    rh_pct?: number
    temp_c?: number
    precip_72h_mm?: number
    source?: string
    gfdi?: number
    gfdi_band?: string
  }
  detections: Detection[]
  reasons: Reason[]
  scorer: string | null
  score_history: { scored_at: string; score: number; recommendation: Recommendation; scorer: string; guardrail: string | null }[]
  actions: { action: ActionName; operator: string; note: string | null; created_at: string }[]
  nearest_assets: { kind: string; name: string; distance_km: number }[]
  data_age?: DataAge[]
}

export interface DataAge {
  source: string
  label: string
  last_seen: string | null
}

export interface InPathPlace {
  id: string
  label: string
  kind: string
  family: string | null
  status: string
  arrival_local: string | null
  eta_local: string | null
  reached_local: string | null
  eta_min: number | null
  later: boolean
  miles_from_fire: number
  fire_dir_from_place: string
}

export interface InPath {
  event_id: number
  start: string
  now: string
  places: InPathPlace[]
}

export interface Messages {
  escalated: boolean
  chief: string
  quiet: string
  landowners: { id: string; name: string; phone?: string; text: string }[]
}

export interface NotifyResult {
  live: boolean
  results: { channel: string; to: string; text: string; status: string; error: string | null; via: string | null }[]
}

export interface Burn {
  id: number
  lat: number
  lon: number
  start: string
  end: string
  called_in: string
  caller: string
  label: string | null
  is_sample: boolean
}

export interface NewBurn {
  caller: string
  lat: number
  lon: number
  start: string
  end: string
}

export interface LiteResponse {
  t: string
  alerts: { id: number; score: number; rec: Recommendation; label: string; lat: number; lon: number; why: string; status: Status; seen: string }[]
  quiet: { total: number; logged_burn: number; static_source: number; likely_prescribed: number; low_signal: number }
}

export interface SimulationResult {
  event_id: number
  assumptions: Record<string, string | number>
  head_ros_kmh: number
  length_to_breadth: number
  isochrones: GeoJSON.FeatureCollection<GeoJSON.MultiPolygon, { minutes: number; area_ha: number }>
  impacts: { kind: string; name: string; minutes: number }[]
  wind_vector: { from_deg: number; kmh: number }
  observed_wind: { from_deg: number; kmh: number }
  overridden: boolean
}

export interface SourceHealth {
  status: 'ok' | 'stale' | 'down' | 'sample'
  age_min: number | null
  last_ok: string | null
  last_error: string | null
}

export interface Health {
  mode: 'sample' | 'live'
  firms_key_configured: boolean
  replay_running: boolean
  sources: Record<string, SourceHealth>
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

let liteEtag: string | null = null
let liteCache: AlertsResponse | null = null
let liteMissing = false

/** The one-bar list. Sends If-None-Match, treats 304 as no change, and falls back to /alerts if the route is missing. */
async function liteAlerts(): Promise<AlertsResponse> {
  if (liteMissing) return request<AlertsResponse>('/alerts?include_monitor=false')
  const headers: Record<string, string> = {}
  if (liteEtag && liteCache) headers['If-None-Match'] = liteEtag
  const res = await fetch(`${BASE}/lite/alerts`, { headers })
  if (res.status === 304 && liteCache) return liteCache
  if (res.status === 404) {
    liteMissing = true
    return request<AlertsResponse>('/alerts?include_monitor=false')
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  const d = (await res.json()) as LiteResponse
  const old = Date.now() - 3 * 86_400_000
  const out: AlertsResponse = {
    mode: 'live',
    generated_at: d.t,
    alerts: d.alerts.map((a) => ({
      id: a.id,
      lat: a.lat,
      lon: a.lon,
      place_label: a.label,
      county: null,
      first_seen: a.seen,
      last_seen: a.seen,
      status: a.status,
      score: a.score,
      recommendation: a.rec,
      score_trend: [a.score],
      degraded: false,
      guardrail: null,
      suppression: null,
      reraised: false,
      sources: {},
      top_reason: a.why,
      is_sample: new Date(a.seen).getTime() < old,
      sample_slug: null,
    })),
    suppressed: d.quiet,
  }
  liteEtag = res.headers.get('ETag')
  liteCache = out
  return out
}

export const api = {
  liteAlerts,
  inPath: (id: number) => request<InPath>(`/alerts/${id}/in-path`),
  messages: (id: number) => request<Messages>(`/alerts/${id}/messages`),
  notify: (id: number) => request<NotifyResult>(`/alerts/${id}/notify`, { method: 'POST', body: JSON.stringify({}) }),
  capUrl: (id: number) => `${BASE}/alerts/${id}/cap.xml`,
  burns: () => request<{ burns: Burn[] }>('/burns'),
  logBurn: (b: NewBurn) => request<Burn>('/burns', { method: 'POST', body: JSON.stringify(b) }),
  alerts: (includeMonitor: boolean) =>
    request<AlertsResponse>(`/alerts?include_monitor=${includeMonitor}`),
  alert: (id: number) => request<AlertDetail>(`/alerts/${id}`),
  act: (id: number, action: ActionName, operator: string, note: string) =>
    request<AlertDetail>(`/alerts/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action, operator, note: note || null }),
    }),
  simulate: (id: number, wind?: { kmh: number; fromDeg: number }) => {
    const q = wind ? `?wind_kmh=${wind.kmh}&wind_from_deg=${wind.fromDeg}` : ''
    return request<SimulationResult>(`/alerts/${id}/simulate${q}`)
  },
  layer: (name: string) => request<GeoJSON.FeatureCollection>(`/layers/${name}`),
  health: () => request<Health>('/health'),
  replay: () => request<{ status: string }>('/sample/replay?duration_s=60', { method: 'POST' }),
  ingest: () => request<unknown>('/ingest/run', { method: 'POST' }),
}
