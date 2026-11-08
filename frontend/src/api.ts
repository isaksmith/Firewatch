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
  kind: 'satellite' | 'line_fault' | 'report' | 'neighbor_reply' | 'camera_smoke' | 'sensor_smoke' | 'burn_notice'
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
  crew: CrewPosition[]
}

/** A roster contact whose Meshtastic radio has a GPS fix from the last 30 minutes. */
export interface CrewPosition {
  contact_id: number
  name: string
  role: string
  lat: number
  lon: number
  mi: number
  from_fire: string
  position_min_ago: number
}

export interface MeshNode {
  node_id: string
  long_name: string | null
  short_name: string | null
  hw_model: string | null
  lat: number | null
  lon: number | null
  position_at: string | null
  battery_pct: number | null
  snr: number | null
  last_heard: string
  contact_id: number | null
  contact_name: string | null
  contact_role: string | null
  is_gateway: boolean
  heard_min_ago: number
  position_min_ago: number | null
  sensors: SensorReadings | null
}

export type SensorStatus = 'ok' | 'watch' | 'service' | 'replace' | 'stale' | 'offline'

export interface SensorLatest {
  temp_c?: number
  rh_pct?: number
  pressure_hpa?: number
  gas_kohm?: number
  pm25?: number
  pm10?: number
  pack_v?: number
  pack_ma?: number
  solar_v?: number
  solar_ma?: number
  reading_at?: string
}

export interface SensorNode {
  node_id: string
  kind: 'sensor' | 'relay' | 'bridge'
  tier: 'bare' | 'rich' | null
  site: number | null
  label: string
  lat: number
  lon: number
  via: string | null
  installed_at: string
  simulated: boolean
  last_heard: string | null
  snr: number | null
  battery_pct: number | null
  status: SensorStatus
  radio: 'ok' | 'down'
  sensors: 'ok' | 'stale' | 'unknown' | 'n/a'
  actions: string[]
  latest: SensorLatest
}

export interface SensorNetwork {
  simulated: boolean
  counts: Record<SensorStatus, number>
  nodes: SensorNode[]
  links: GeoJSON.FeatureCollection<GeoJSON.LineString, { kind: 'backbone' | 'gateway' }>
}

export interface SensorCheck {
  key: string
  part: string
  status: SensorStatus
  value: string
  detail: string
  action: string | null
}

export interface SensorDetail extends SensorNode {
  checks: SensorCheck[]
  series: Record<'pm25' | 'gas_kohm' | 'pack_v' | 'temp_c' | 'rh_pct' | 'solar_w', [string, number][]>
  via_label: string | null
  baseline: { gas_kohm?: number }
}

export interface SensorReadings {
  temp_c?: number
  rh_pct?: number
  pm25?: number
  pm10?: number
  reading_at: string
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
  channel: 'sms' | 'mesh'
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
    /** Hour of the weather sample the alert was scored and forecast with. */
    valid_time?: string
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

export interface FireSize {
  acres: number
  head_mi: number
}

export interface ScenarioFire {
  key: string
  label: string
  ignition: { lat: number; lon: number; cause: string }
  t_start: number
  event_id: number | null
  baseline: Milestone[]
  firewatch: Milestone[]
  size_on_scene: { baseline: FireSize | null; firewatch: FireSize | null }
  growth: { minute: number; acres: number; head_mi: number }[]
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
  waiting: { name: string; reply: string; mesh_id: string; until: string; seconds_left: number } | null
  baseline: Milestone[]
  firewatch: Milestone[]
  size_on_scene: { baseline: FireSize | null; firewatch: FireSize | null }
  growth: { minute: number; acres: number; head_mi: number }[]
  fires: ScenarioFire[]
  events: { id: number; place_label: string; recommendation: Recommendation; level_reason: string; suppression: string | null; texts_sent: number; fire: string }[]
  texts_sent: number
}

export interface District {
  slug: string
  settings: Record<string, string | number | number[]> & { name: string; short_name: string }
  boundary: GeoJSON.FeatureCollection
}

export const SCENARIO = 'cottonwood-creek'

export interface ScenarioSummary {
  slug: string
  title: string
  story: string
}

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
  llm_configured?: boolean
  replay_running: boolean
  sources: Record<string, SourceHealth>
}

/** The answer a texted question would get; shown in the console, never sent. */
export interface AskAnswer {
  answer: string
  /** True when the LLM worded it; false when the plain template did (LLM off, failed, or its answer failed the checks). */
  by_model: boolean
  llm_configured: boolean
  fires: { id: number; place: string; status: string }[]
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

export interface AlertForecast {
  event_id: number
  /** The fire's "now": the scenario clock, a historical fire's last detection, or the wall clock. */
  now: string
  steps: {
    ahead_min: number
    at: string
    likely: GeoJSON.MultiPolygon
    worst: GeoJSON.MultiPolygon
    /** Forecast wind at the fire at that time. */
    wind: { from_deg: number; kmh: number; compass: string }
  }[]
  members: number
  assumptions: Record<string, string | number>
}

export interface PlannerRegions {
  districts: { key: string; name: string }[]
  counties: { key: string; name: string }[]
}

export interface PlanParams {
  sites?: number
  bare_per_site?: number
  rich_per_site?: number
  budget_usd?: number
  rich_range_km?: number
  bare_fetch_km?: number
  pricing?: NodePricing
}

export type NodePricing = 'stocked' | 'custom'

export interface WindMode {
  from_deg: number
  from: string
  share: number
}

export interface Climatology {
  source: string
  fire_gfdi: number
  fire_hours_per_year: number
  very_high_hours_per_year: number
  fire_hours_by_month: number[]
  fire_wind_rose: number[]
  fire_wind_kmh_median: number
  fire_wind_modes: WindMode[]
  sun_hours: { fire_season_mean: number; fire_season_worst_week: number; winter_worst_week: number; december_mean: number }
  pm_too_cold_days_per_year: number
  fire_season_fog_morning_share: number
}

interface PowerRow {
  sun_hours: number
  made_wh_day: number
  need_wh_day: number
  days_on_battery: number | null
}

export interface TierPower {
  panel_w: number
  pack_wh: number
  fire_season_worst_week: PowerRow
  winter_worst_week: PowerRow
  max_pm_duty_fire_season?: number
}

export interface RadioLink {
  km: number
  fresnel: number
  quality: 'clear' | 'marginal'
}

export interface PlanSite {
  id: number
  label: string
  lon: number
  lat: number
  on: 'line' | 'cell'
  priority: number
  adds_coverage: number
  reasons: string[]
  risk: {
    rank: number
    factors: { key: RiskFactor; label: string; share: number }[]
    tallgrass: boolean
    downwind_of_town: number
  }
  choice: string[]
  placement: string
  layout: string
  checks: string[]
  bare: number
  rich: number
  gateway: (RadioLink & { name: string }) | null
  hops: number | null
  nodes: { tier: 'bare' | 'rich'; lon: number; lat: number; faces: string | null }[]
}

export type RiskFactor = 'history' | 'burns' | 'lines' | 'people'

export interface PlanRelay extends RadioLink {
  name: string
  kind: 'town' | 'substation' | 'high_point' | 'site_mast' | 'new_mast'
  why: string
  serves: number[]
  mount: 'tower' | 'mast'
  power: 'mains' | 'solar'
  lon: number
  lat: number
  uplink: string
}

export interface RegionPlan {
  region: {
    key: string
    name: string
    kind: string
    area_km2: number
    area_sq_mi: number
    bbox: [number, number, number, number]
    cell_km: number
    boundary: GeoJSON.Feature
  }
  params: Required<Omit<PlanParams, 'budget_usd'>> & { budget_usd: number | null; plot_acres: number; site_min_sep_km: number }
  climate: Climatology
  power: { bare: TierPower; rich: TierPower }
  summary: {
    sites: number
    bare: number
    rich: number
    relays: number
    priority_covered: number
    watched_by_rich: number
    watched_by_bare: number
    coverage_curve: number[]
    reported_wildfires: number
    burns_per_year: number
    max_hops: number | null
    unreached_sites: number[]
    prevailing_fire_wind: string
    fire_wind_compass: string
  }
  station: { name: string; lon: number; lat: number }
  sites: PlanSite[]
  relays: PlanRelay[]
  bom: {
    pricing: NodePricing
    lines: { item: string; qty: number; unit: number; total: number }[]
    hardware: number
    spares: number
    total: number
    alternative: { pricing: NodePricing; hardware: number }
  }
  geojson: {
    cells: GeoJSON.FeatureCollection<GeoJSON.Polygon, { priority: number; covered: number }>
    nodes: GeoJSON.FeatureCollection<GeoJSON.Point, { kind: 'sensor'; tier: 'bare' | 'rich'; site: number }>
    links: GeoJSON.FeatureCollection<GeoJSON.LineString, RadioLink & { kind: 'backbone' | 'gateway' }>
  }
  assumptions: string[]
  warnings: string[]
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
}

export interface NewBurn {
  caller: string
  lat: number
  lon: number
  start: string
  end: string
  called_in?: string
  label?: string
}

/** What /api/lite/alerts sends: short keys, plus a count of quiet detections. */
interface LiteResponse {
  t: string
  alerts: { id: number; score: number | null; level: 'escalate' | 'investigate'; data_at?: string | null; label: string; lat: number; lon: number; why: string | null; status: Status; seen: string }[]
  quiet?: Partial<Record<Suppression | 'logged_burn' | 'total', number>>
}

function quietCounts(q: LiteResponse['quiet']): AlertsResponse['suppressed'] {
  const n = (v: number | undefined) => v ?? 0
  const out = {
    static_source: n(q?.static_source),
    likely_prescribed: n(q?.likely_prescribed),
    registered_burn: n(q?.registered_burn) + n(q?.logged_burn),
    low_signal: n(q?.low_signal),
  }
  return { total: q?.total ?? out.static_source + out.likely_prescribed + out.registered_burn + out.low_signal, ...out }
}

let liteEtag: string | null = null
let liteCache: AlertsResponse | null = null

/** The small alert list. Sends If-None-Match and treats 304 as no change. Reshaped to look like /alerts. */
async function liteAlerts(): Promise<AlertsResponse> {
  const headers: Record<string, string> = {}
  if (liteEtag && liteCache) headers['If-None-Match'] = liteEtag
  const res = await fetch(`${BASE}/lite/alerts`, { headers })
  if (res.status === 304 && liteCache) return liteCache
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  const d = (await res.json()) as LiteResponse
  const out: AlertsResponse = {
    mode: 'live',
    generated_at: d.t,
    alerts: d.alerts.map(
      (a) =>
        ({
          id: a.id,
          lat: a.lat,
          lon: a.lon,
          place_label: a.label,
          county: null,
          first_seen: a.seen,
          last_seen: a.seen,
          status: a.status,
          score: a.score,
          recommendation: a.level,
          score_trend: a.score == null ? [] : [a.score],
          degraded: false,
          guardrail: null,
          suppression: null,
          reraised: false,
          sources: {},
          signals: {},
          top_reason: a.why,
          level_reason: null,
          evidence: [],
          response: null,
          is_sample: false,
          sample_slug: null,
        }) as AlertSummary,
    ),
    suppressed: quietCounts(d.quiet),
  }
  liteEtag = res.headers.get('ETag')
  liteCache = out
  return out
}

/** Plain words for the errors people can actually hit, instead of raw codes. */
function plainError(res: Response, detail: unknown): string {
  if (res.status === 401) return "This computer isn't signed in to do that."
  if (res.status === 429) {
    const secs = Number(res.headers.get('Retry-After'))
    return secs > 0 ? `Please wait ${Math.ceil(secs)} seconds and try again.` : 'Please wait a moment and try again.'
  }
  return typeof detail === 'string' ? detail : `${res.status} ${res.statusText}`
}

async function request<T>(path: string, init?: RequestInit, unauthorized?: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    // No token here: anything in the bundle is public. The proxy in front of the API adds X-Firewatch-Token.
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(res.status === 401 && unauthorized ? unauthorized : plainError(res, body.detail))
  }
  return res.json() as Promise<T>
}

export const api = {
  liteAlerts,
  burns: async (): Promise<{ burns: Burn[] }> => {
    const r = await request<Burn[] | { burns: Burn[] }>('/burns')
    return Array.isArray(r) ? { burns: r } : r
  },
  logBurn: (b: NewBurn, keepalive = false) => request<Burn>('/burns', { method: 'POST', body: JSON.stringify(b), keepalive }, "Burn not saved: this computer isn't signed in to log burns."),
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
  meshNodes: () => request<MeshNode[]>('/mesh/nodes'),
  sensors: () => request<SensorNetwork>('/sensors'),
  sensor: (id: string) => request<SensorDetail>(`/sensors/${encodeURIComponent(id)}`),
  boardAdminPosts: () => request<AdminPost[]>('/board/admin/posts'),
  boardAdminBurns: () => request<AdminBurn[]>('/board/admin/burns'),
  boardStation: (id: number, action: StationAction, operator: string) =>
    request<StationResult>(`/board/admin/posts/${id}/station`, {
      method: 'POST',
      body: JSON.stringify({ action, operator }),
    }),
  pendingMembers: () => request<PendingMember[]>('/members/pending'),
  approveMember: (id: number, lat: number, lon: number) =>
    request<ApproveResult>(`/members/${id}/approve`, { method: 'POST', body: JSON.stringify({ lat, lon }) }),
  rejectMember: (id: number) => request<{ ok: boolean }>(`/members/${id}/reject`, { method: 'POST' }),
  scenarios: () => request<ScenarioSummary[]>('/scenarios'),
  scenario: (slug: string) => request<ScenarioStatus>(`/scenario/${slug}`),
  runScenario: (slug: string) => request<{ status: string }>(`/scenario/${slug}/run`, { method: 'POST' }),
  stopScenario: () => request<{ status: 'stopped' | 'not_running' }>('/scenario/stop', { method: 'POST' }),
  alertForecast: (id: number) => request<AlertForecast>(`/alerts/${id}/forecast`),
  options: (id: number) => request<Playbook>(`/alerts/${id}/options`),
  chooseOption: (id: number, optionId: string, operator: string) =>
    request<Playbook>(`/alerts/${id}/options/${optionId}`, { method: 'POST', body: JSON.stringify({ operator }) }),
  ask: (question: string, useModel: boolean) =>
    request<AskAnswer>('/ask', { method: 'POST', body: JSON.stringify({ question, use_model: useModel }) }),
  plannerRegions: () => request<PlannerRegions>('/planner/regions'),
  plan: (region: string, params: PlanParams) => {
    const q = new URLSearchParams({ region })
    for (const [k, v] of Object.entries(params)) if (v != null && !Number.isNaN(v)) q.set(k, String(v))
    return request<RegionPlan>(`/planner/plan?${q}`)
  },
}

// ---- Community board ----

const DEVICE_KEY = 'firewatch.device'

const TOKEN_RE = /^[A-Za-z0-9_-]{43}$/

export function isWellFormedToken(t: string): boolean {
  return TOKEN_RE.test(t)
}

export function getDeviceToken(): string | null {
  try {
    const t = localStorage.getItem(DEVICE_KEY)
    if (t === null) return null
    if (TOKEN_RE.test(t)) return t
    localStorage.removeItem(DEVICE_KEY)
    return null
  } catch {
    return null
  }
}

export function setDeviceToken(token: string) {
  if (!TOKEN_RE.test(token)) return
  try {
    localStorage.setItem(DEVICE_KEY, token)
  } catch {
    /* storage blocked: the page still works without it */
  }
}

export function clearDeviceToken() {
  try {
    localStorage.removeItem(DEVICE_KEY)
  } catch {
    /* ignore */
  }
}

export type BoardCategory = 'fire' | 'smoke' | 'hazard' | 'burn' | 'other'
export type ConfirmKind = 'see' | 'not_seeing' | 'burn'
export type StationAction = 'ack' | 'send' | 'page' | 'dismiss' | 'resolve'

export interface BoardMe {
  name: string | null
  role: string | null
  member: boolean
  station: boolean
}

export interface BoardPost {
  id: number
  category: string
  body: string
  lat: number | null
  lon: number | null
  estimated: boolean
  hearsay: boolean
  flagged: boolean
  status: string
  parent_id: number | null
  event_id?: number | null
  created_at: string
  author: string | null
  confirms: number
  notes: number | null
  badge: string | null
  unconfirmed: boolean
  held?: boolean
  event_status?: string | null
  has_photo?: boolean
  thread_size?: number
  age_min?: number
  sent_late_min?: number | null
}

export interface AdminPost extends BoardPost {
  held: boolean
  event_id: number | null
  event_status: string | null
}

export interface StationResult {
  ok: boolean
  event_id: number | null
  repeat?: boolean
}

export interface PendingMember {
  id: number
  name: string
  phone: string
}

export interface ApproveResult {
  token: string | null
  link: string | null
  texted: boolean
}

export const BOARD_ADMIN_KEY = ['board-admin-posts'] as const

/** A burn on the board's "Burns today": the public view, rounded and without identity. Same store as Burn. */
export interface BoardBurn {
  lat: number
  lon: number
  radius_km: number
  registered_at: string
  reports_nearby: boolean
}

export interface AdminBurn extends BoardBurn {
  name: string
  late: boolean
  /** Logged by phone: the window, UTC ISO. */
  start?: string
  end?: string
}

export const BOARD_BURNS_ADMIN_KEY = ['board-admin-burns'] as const

export interface PostResult {
  post_id: number
  event_id: number | null
  flagged: boolean
  asked: number
  known: boolean
  used_home: boolean
  alerted: boolean
  duplicate?: boolean
}

export interface ConfirmResult {
  ok: boolean
  reason: string
  counted: boolean
  count: number
  event_id: number | null
  level: string | null
}

export class BoardError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function boardRequest<T>(path: string, init?: RequestInit, tokenOverride?: string): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = tokenOverride ?? getDeviceToken()
  if (token) headers['X-Firewatch-Device'] = token
  const res = await fetch(`${BASE}/board${path}`, { ...init, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new BoardError(typeof body.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`, res.status)
  }
  return res.json() as Promise<T>
}

/** Create a device token the first time someone posts or confirms. */
export async function ensureDevice(): Promise<void> {
  if (getDeviceToken()) return
  const r = await boardRequest<{ token: string }>('/device', { method: 'POST' })
  setDeviceToken(r.token)
}

/** Ensure a device, call, and on a 401 make one new device and retry once. */
async function withDevice<T>(call: () => Promise<T>): Promise<T & { reissued: boolean }> {
  await ensureDevice()
  try {
    return { ...(await call()), reissued: false }
  } catch (e) {
    if (!(e instanceof BoardError) || e.status !== 401) throw e
  }
  clearDeviceToken()
  await ensureDevice()
  return { ...(await call()), reissued: true }
}

export const boardPhotoUrl = (id: number) => `${BASE}/board/posts/${id}/photo`
export const boardAdminPhotoUrl = (id: number) => `${BASE}/board/admin/posts/${id}/photo`

async function uploadPhoto(postId: number, blob: Blob): Promise<void> {
  await ensureDevice()
  const headers: Record<string, string> = { 'Content-Type': blob.type }
  const token = getDeviceToken()
  if (token) headers['X-Firewatch-Device'] = token
  const res = await fetch(`${BASE}/board/posts/${postId}/photo`, { method: 'POST', headers, body: blob })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new BoardError(typeof body.detail === 'string' ? body.detail : `${res.status} ${res.statusText}`, res.status)
  }
}

export interface NewPostBody {
  category: BoardCategory
  body: string
  lat: number | null
  lon: number | null
  attach_location: boolean
  client_key?: string
  queued_min?: number
  bearing?: number
  miles?: number
}

export const boardApi = {
  uploadPhoto,
  /** With no token there is no identity to look up, so no request goes out. */
  me: async (token?: string): Promise<BoardMe | null> => {
    const t = token ?? getDeviceToken()
    if (!t) return null
    return boardRequest<BoardMe>('/me', undefined, t)
  },
  posts: () => boardRequest<BoardPost[]>('/posts'),
  burns: () => boardRequest<BoardBurn[]>('/burns'),
  post: (b: NewPostBody) =>
    withDevice(() => boardRequest<PostResult>('/posts', { method: 'POST', body: JSON.stringify(b) })),
  confirm: (id: number, b: { kind: ConfirmKind; lat: number | null; lon: number | null }) =>
    withDevice(() => boardRequest<ConfirmResult>(`/posts/${id}/confirm`, { method: 'POST', body: JSON.stringify(b) })),
  station: (id: number, action: StationAction) =>
    boardRequest<unknown>(`/posts/${id}/station`, { method: 'POST', body: JSON.stringify({ action }) }),
}
