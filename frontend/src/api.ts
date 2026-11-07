const BASE = import.meta.env.VITE_API_BASE ?? '/api'

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
  /** Satellite score; null when the event has only line-fault or people signals. */
  score: number | null
  recommendation: Recommendation
  score_trend: number[]
  degraded: boolean
  guardrail: string | null
  suppression: Suppression | null
  reraised: boolean
  sources: Record<string, number>
  signals: Record<string, number>
  top_reason: string | null
  level_reason: string | null
  evidence: Evidence[]
  response: ResponseBrief | null
  is_sample: boolean
  sample_slug: string | null
}

export type Suppression = 'static_source' | 'likely_prescribed' | 'registered_burn' | 'low_signal'

export interface Evidence {
  kind: 'satellite' | 'line_fault' | 'report' | 'neighbor_reply' | 'camera_smoke' | 'burn_notice'
  label: string
  at: string
  counts: 'strong' | 'yes' | 'weak' | 'no'
  note?: string
  source?: string
}

export interface ResponseBrief {
  investigate_at: string | null
  escalate_at: string | null
  awaiting: string | null
  decision: 'page' | 'no' | null
  decision_by: string | null
  decision_at: string | null
  page_at: string | null
  ladder: { step: number; at: string }[]
  responders: { contact_id: number; name: string; role: string; at: string }[]
  mutual_aid: { reason: string; drafted_at: string; sent_at?: string; sent_by?: string } | null
  plan: {
    acres_60: number
    area_60_ha: number
    wind: { from: string; mph: number }
    downwind: { contact_id: number; name: string; eta_min: number }[]
    helpers: { contact_id: number; name: string; role: string }[]
  } | null
  texts_sent: number
}

export interface Message {
  id: number
  event_id: number | null
  direction: 'in' | 'out'
  purpose: string | null
  body: string
  status: string
  created_at: string
  phone: string | null
  contact_name: string | null
  contact_role: string | null
}

export interface AlertsResponse {
  mode: 'sample' | 'live'
  generated_at: string
  alerts: AlertSummary[]
  suppressed: { total: number } & Record<Suppression, number>
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
    dew_point_c?: number
    pressure_hpa?: number
    vpd_kpa?: number
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
  signal_list: { id: number; kind: string; lat: number; lon: number; observed_at: string; source: string; value: string | null; contact_name: string | null }[]
  messages: Message[]
  nearest_assets: { kind: string; name: string; distance_km: number }[]
}

export interface Milestone {
  key: string
  t: number | null
  label: string
}

export interface ScenarioStatus {
  slug: string
  title: string
  story: string
  synthetic: boolean
  t0: string
  t0_local: string
  duration_min: number
  ignition: { lat: number; lon: number; cause: string }
  weather: { wind_kmh: number; wind_dir_deg: number; rh_pct: number; temp_c: number; gfdi: number; gfdi_band: string }
  running: boolean
  t_min: number | null
  baseline: Milestone[]
  firewatch: Milestone[]
  size_on_scene: { baseline: { acres: number; head_mi: number } | null; firewatch: { acres: number; head_mi: number } | null }
  growth: { minute: number; acres: number; head_mi: number }[]
  events: { id: number; place_label: string; recommendation: Recommendation; level_reason: string; suppression: string | null; texts_sent: number }[]
  texts_sent: number
}

export interface District {
  slug: string
  settings: Record<string, string | number | number[]> & { name: string; short_name: string }
  boundary: GeoJSON.FeatureCollection
}

export const SCENARIO = 'cottonwood-creek'

export interface SimulationResult {
  event_id: number
  assumptions: Record<string, string | number>
  head_ros_kmh: number
  length_to_breadth: number
  isochrones: GeoJSON.FeatureCollection<GeoJSON.MultiPolygon, { minutes: number; area_ha: number }>
  impacts: { kind: string; id: string; name: string; minutes: number }[]
  wind_vector: { from_deg: number; kmh: number }
  observed_wind: { from_deg: number; kmh: number }
  overridden: boolean
}

export interface SourceHealth {
  status: 'ok' | 'stale' | 'down' | 'sample' | 'skipped'
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

export interface PlaybookOption {
  id: string
  title: string
  recommended: boolean
  why: string | null
  metrics: { label: string; value: string }[]
  effects: string[]
  /** Clock time this option was already chosen for the current decision. */
  done: string | null
  /** In acre-equivalents: P(fire) x acres if real + (1 - P) x false-alarm cost. */
  expected_loss: number
}

export interface Receipt {
  at: string
  clock: string
  by: string
  title: string
  followed_recommendation: boolean | null
  results: string[]
}

export interface Playbook {
  event_id: number
  clock: string
  minutes_since_start: number
  /** P(fire is real) and the evidence steps that produced it. */
  probability: { p: number; steps: { text: string; factor?: number; p: number }[] }
  /** What makes this fire dangerous (context; the choice comes from expected loss). */
  risk: string[]
  decision: { id: string; question: string; options: PlaybookOption[] } | null
  receipts: Receipt[]
  /** Every weight the recommendation uses, with its source. */
  model: { key: string; value: number | Record<string, number>; source: string }[]
}

export interface FeedResponse {
  feed: string
  fixture: boolean
  fetched_at: string | null
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any
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

export const api = {
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
  feed: (name: string) => request<FeedResponse>(`/feeds/${name}`),
  riskGrid: () => request<GeoJSON.FeatureCollection>('/risk/grid'),
  linesUnderWind: () => request<GeoJSON.FeatureCollection>('/risk/lines-under-wind'),
  health: () => request<Health>('/health'),
  replay: () => request<{ status: string }>('/sample/replay?duration_s=60', { method: 'POST' }),
  ingest: () => request<unknown>('/ingest/run', { method: 'POST' }),
  decide: (id: number, action: 'page' | 'no' | 'send', operator: string) =>
    request<AlertDetail>(`/alerts/${id}/decision`, { method: 'POST', body: JSON.stringify({ action, operator }) }),
  district: () => request<District>('/district'),
  scenario: (slug: string) => request<ScenarioStatus>(`/scenario/${slug}`),
  runScenario: (slug: string) => request<{ status: string }>(`/scenario/${slug}/run`, { method: 'POST' }),
  options: (id: number) => request<Playbook>(`/alerts/${id}/options`),
  chooseOption: (id: number, optionId: string, operator: string) =>
    request<Playbook>(`/alerts/${id}/options/${optionId}`, { method: 'POST', body: JSON.stringify({ operator }) }),
}
