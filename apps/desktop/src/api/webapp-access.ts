import { hermesApi, profileScoped } from './client'

// Web access: make the Webapp the gateway on THIS machine serves reachable from
// other devices, behind the dashboard login. The backend owns every fact here;
// the pane only renders /status and asks for changes.

export type WebAccessMode = 'lan' | 'public'

/** What the gateway serves now. Its `webapp:` config applies when it starts, so this can lag. */
export interface WebAccessGatewayState {
  reason: null | string
  /** `stopped`: no gateway answers. */
  state: 'off' | 'serving' | 'stopped' | 'unavailable'
  url: null | string
}

export interface WebAccessStatus {
  default_port: number
  /** `webapp.enabled` in the serving gateway's config. */
  enabled: boolean
  gateway: WebAccessGatewayState
  lan_address: null | string
  /** Configured shape; `local` is a loopback Webapp without a public URL (set up outside this pane). */
  mode: 'lan' | 'local' | 'public' | null
  nous_client_id: string
  password_username: string
  port: number
  public_url: string
}

/** Start/stop save the config and restart the gateway; a refused restart keeps the config. */
export interface WebAccessChange extends WebAccessStatus {
  restart_error?: string
  restart_started: boolean
}

export interface WebAccessPlan {
  mode: WebAccessMode
  port: number
  public_url?: string
}

export function getWebAccessStatus(): Promise<WebAccessStatus> {
  return hermesApi<WebAccessStatus>({ ...profileScoped(), path: '/api/webapp-access/status' })
}

export function setWebAccessPassword(username: string, password: string): Promise<WebAccessStatus> {
  return hermesApi<WebAccessStatus>({
    ...profileScoped(),
    body: { password, username },
    method: 'POST',
    path: '/api/webapp-access/password'
  })
}

export function removeWebAccessPassword(): Promise<WebAccessStatus> {
  return hermesApi<WebAccessStatus>({ ...profileScoped(), method: 'DELETE', path: '/api/webapp-access/password' })
}

export function setUpWebAccessNous(plan: WebAccessPlan): Promise<WebAccessStatus> {
  return hermesApi<WebAccessStatus>({
    ...profileScoped(),
    body: plan,
    method: 'POST',
    path: '/api/webapp-access/nous'
  })
}

export function removeWebAccessNous(): Promise<WebAccessStatus> {
  return hermesApi<WebAccessStatus>({ ...profileScoped(), method: 'DELETE', path: '/api/webapp-access/nous' })
}

export function startWebAccess(plan: WebAccessPlan): Promise<WebAccessChange> {
  return hermesApi<WebAccessChange>({
    ...profileScoped(),
    body: plan,
    method: 'POST',
    path: '/api/webapp-access/start'
  })
}

export function stopWebAccess(): Promise<WebAccessChange> {
  return hermesApi<WebAccessChange>({ ...profileScoped(), method: 'POST', path: '/api/webapp-access/stop' })
}
