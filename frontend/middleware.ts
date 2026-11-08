import { ipAddress, next, rewrite } from '@vercel/functions'

// Vercel runs this before every request except the built files and the FireNode Explorer. It asks for the console
// login, then forwards /api and /lite to the server with the API token, the visitor's IP and the proxy secret.
// None of those three reach a browser. Environment (Vercel project settings):
//   FW_USER, FW_PASSWORD   console login
//   FW_LOGIN=off           no login: anyone can use the console, including Run scenario and the other admin actions
//   FW_API_ORIGIN          the server, e.g. https://3-14-15-92.sslip.io
//   FW_API_TOKEN           the backend's API_TOKEN
//   FW_PROXY_SECRET        the server refuses requests without it, so the IP and token headers can be trusted
export const config = {
  matcher: ['/((?!assets/|nodes|favicon\\.svg|icons\\.svg).*)'],
}

// Residents and the mobile app need no login. Everything else is the console and asks for one.
const PUBLIC = [
  /^\/board(\/|$)/,
  /^\/api\/m\//,
  /^\/api\/sms\/inbound$/,
  /^\/api\/board\/(device|me|burns)$/,
  /^\/api\/board\/posts(\/|$)/,
]
const BACKEND = /^\/(api\/|lite(\/|$))/
const SESSION = 'fw_session'

export default async function middleware(request: Request) {
  const url = new URL(request.url)
  const open = PUBLIC.some((p) => p.test(url.pathname))
  const backend = BACKEND.test(url.pathname)
  // Chrome doesn't always send the saved password with the page's own API calls, so a login also sets a cookie
  // that every request carries.
  let setCookie: string | undefined
  const loginOff = process.env.FW_LOGIN === 'off'
  if (!open && !loginOff && !(await hasSession(request.headers.get('cookie')))) {
    if (!(await loggedIn(request.headers.get('authorization')))) {
      // Only pages ask for the password; a prompt raised by a background API call would be confusing.
      const ask = backend ? {} : { 'WWW-Authenticate': 'Basic realm="Firewatch", charset="UTF-8"' }
      return new Response('Login required', { status: 401, headers: ask })
    }
    setCookie = `${SESSION}=${await sessionToken()}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax`
  }
  const extra = setCookie ? { headers: { 'Set-Cookie': setCookie } } : {}
  if (!backend) return next(extra)

  const headers = new Headers(request.headers)
  for (const h of ['host', 'authorization', 'cookie', 'x-firewatch-token', 'x-firewatch-proxy', 'x-firewatch-client-ip']) {
    headers.delete(h)
  }
  if (!open) headers.set('x-firewatch-token', process.env.FW_API_TOKEN ?? '')
  headers.set('x-firewatch-proxy', process.env.FW_PROXY_SECRET ?? '')
  headers.set('x-firewatch-client-ip', ipAddress(request) ?? '')
  return rewrite(new URL(url.pathname + url.search, process.env.FW_API_ORIGIN), { ...extra, request: { headers } })
}

const bytes = (s: string) => Uint8Array.from(new TextEncoder().encode(s))
const digest = async (b: Uint8Array<ArrayBuffer>) => new Uint8Array(await crypto.subtle.digest('SHA-256', b))

// Comparing fixed-length digests in full, so the time taken says nothing about how much of the secret matched.
async function same(given: Uint8Array<ArrayBuffer>, expected: Uint8Array<ArrayBuffer>): Promise<boolean> {
  const [a, b] = await Promise.all([digest(given), digest(expected)])
  return a.reduce((diff, x, i) => diff | (x ^ b[i]), 0) === 0
}

function configured(): boolean {
  // Unset login settings must lock the console, not open it to an empty username and password.
  return Boolean(process.env.FW_USER && process.env.FW_PASSWORD && process.env.FW_PROXY_SECRET)
}

async function loggedIn(header: string | null): Promise<boolean> {
  if (!configured() || !header?.startsWith('Basic ')) return false
  let given: Uint8Array<ArrayBuffer>
  try {
    given = Uint8Array.from(atob(header.slice(6)), (c) => c.charCodeAt(0))
  } catch {
    return false
  }
  return same(given, bytes(`${process.env.FW_USER}:${process.env.FW_PASSWORD}`))
}

// Derived from the password and the proxy secret, so changing the password signs everyone out.
async function sessionToken(): Promise<string> {
  const { FW_USER, FW_PASSWORD, FW_PROXY_SECRET } = process.env
  const d = await digest(bytes(`session:${FW_USER}:${FW_PASSWORD}:${FW_PROXY_SECRET}`))
  return Array.from(d, (x) => x.toString(16).padStart(2, '0')).join('')
}

async function hasSession(cookies: string | null): Promise<boolean> {
  if (!configured() || !cookies) return false
  const given = cookies.split(/;\s*/).find((c) => c.startsWith(`${SESSION}=`))?.slice(SESSION.length + 1)
  return given ? same(bytes(given), bytes(await sessionToken())) : false
}
