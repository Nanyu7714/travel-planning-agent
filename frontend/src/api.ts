const apiBase = import.meta.env.VITE_API_BASE_URL || '/api/v1'

export function apiUrl(path: string) {
  return `${apiBase}${path}`
}

function csrfToken() {
  return document.cookie.split('; ').find((item) => item.startsWith('csrf_token='))?.split('=')[1] || ''
}

let refreshPromise: Promise<boolean> | null = null

async function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = fetch(apiUrl('/auth/refresh'), {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken() },
      body: '{}',
    }).then((response) => response.ok).catch(() => false).finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

type ValidationIssue = {
  loc?: Array<string | number>
  msg?: string
  type?: string
}

function validationMessage(field: string, issue: ValidationIssue) {
  if (field === 'email') return '邮箱格式不正确，请输入类似 name@example.com 的地址'
  if (field === 'username' && issue.type?.includes('too_short')) return '用户名至少输入 2 个字符'
  if (field === 'username' && issue.type?.includes('too_long')) return '用户名不能超过 50 个字符'
  if (field === 'password' && issue.type?.includes('too_short')) return '密码至少输入 6 个字符'
  if (field === 'password' && issue.type?.includes('too_long')) return '密码不能超过 128 个字符'
  return issue.msg === 'Field required' ? '此项不能为空' : '输入内容不符合要求'
}

export class ApiError extends Error {
  fieldErrors: Record<string, string>

  constructor(message: string, fieldErrors: Record<string, string> = {}) {
    super(message)
    this.name = 'ApiError'
    this.fieldErrors = fieldErrors
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = options.method || 'GET'
  const send = () => {
    const headers = new Headers(options.headers)
    headers.set('Content-Type', 'application/json')
    if (method !== 'GET') headers.set('X-CSRF-Token', csrfToken())
    return fetch(apiUrl(path), { ...options, headers, credentials: 'include' })
  }
  let response = await send()
  const canRefresh = !['/auth/login', '/auth/register', '/auth/refresh'].includes(path)
  if (response.status === 401 && canRefresh) {
    if (await refreshSession()) response = await send()
    else if (path !== '/auth/me') window.dispatchEvent(new Event('auth-expired'))
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    if (Array.isArray(detail.detail)) {
      const fieldErrors: Record<string, string> = {}
      for (const issue of detail.detail as ValidationIssue[]) {
        const location = issue.loc || []
        const field = String(location[location.length - 1] || 'form')
        fieldErrors[field] ||= validationMessage(field, issue)
      }
      throw new ApiError(Object.values(fieldErrors)[0] || '请检查输入内容', fieldErrors)
    }
    const message = typeof detail.detail === 'string' ? detail.detail : detail.error?.message || '请求失败'
    throw new ApiError(message)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export type City = { id: number; slug: string; name: string; description: string; season: string; budget: string; recommended_days: string; image_url: string; support_level: string; planning_enabled: boolean }
export type Attraction = { id: number; city_id: number; name: string; description: string; tags: string[]; opening_hours: string; ticket_price: number; duration_minutes: number; area: string; image_url: string; source: string }
export type Ranking = { rank: number; attraction_id?: number; city_id?: number; name: string; score: number; reason: string; data_source?: string }
export type UserProfile = { display_name: string | null; preferences: string[]; avoid_places: string[] }
export type FavoriteItem = { target_type: 'city' | 'attraction' | 'itinerary'; target_id: number; name: string; description: string; image_url: string; city_id?: number }
export type RecentView = FavoriteItem & { viewed_at: string }
export type Itinerary = { id: number; title: string; city_name: string; days: number; status: string; budget_total: number; budget_scope: string; preferences: string[]; lock_version: number; validation?: Record<string, unknown>; itinerary_days: { day_number: number; title: string; stops: { id: number; attraction_id?: number; name: string; start_time: string; end_time: string; note: string }[] }[] }

export async function getCities() { return api<City[]>('/cities') }
export async function searchCities(query: string) { return api<City[]>(`/cities/search?q=${encodeURIComponent(query)}`) }
export async function getAttractions(cityId: number) { return api<Attraction[]>(`/cities/${cityId}/attractions`) }
export async function getRankings(type = 'city', cityId?: number) {
  const params = new URLSearchParams({ type })
  if (cityId) params.set('city_id', String(cityId))
  return api<Ranking[]>(`/rankings?${params.toString()}`)
}
export async function getUserProfile() { return api<UserProfile>('/auth/profile') }
export async function updateUserProfile(profile: UserProfile) { return api<UserProfile>('/auth/profile', { method: 'PATCH', body: JSON.stringify(profile) }) }
export async function getFavorites() { return api<FavoriteItem[]>('/favorites') }
export async function setFavorite(type: 'city' | 'attraction' | 'itinerary', id: number, active: boolean) { return api(`/favorites/${type}/${id}`, { method: active ? 'PUT' : 'DELETE', body: active ? '{}' : undefined }) }
export async function getRecentViews() { return api<RecentView[]>('/recent-views') }
export async function clearRecentViews() { return api('/recent-views', { method: 'DELETE', body: '{}' }) }
export async function recordRecentView(type: 'city' | 'attraction', id: number) { return api(`/recent-views?target_type=${type}&target_id=${id}`, { method: 'POST', body: '{}' }) }
export async function getItinerary(id: number) { return api<Itinerary>(`/itineraries/${id}`) }
export async function updateItinerary(id: number, body: Record<string, unknown>) { return api<Itinerary>(`/itineraries/${id}`, { method: 'PUT', body: JSON.stringify(body) }) }
export async function replanItinerary(id: number, instruction: string) { return api<Itinerary>(`/itineraries/${id}/replan`, { method: 'POST', body: JSON.stringify({ instruction }) }) }
export async function getItineraryRevisions(id: number) { return api<{ id: number; version_no: number; reason: string; created_at: string }[]>(`/itineraries/${id}/revisions`) }
export async function restoreItineraryRevision(id: number, version: number) { return api<Itinerary>(`/itineraries/${id}/revisions/${version}/restore`, { method: 'POST', body: '{}' }) }
export async function createShare(id: number, expires_days = 30) { return api<{ id: number; share_url: string; expires_at: string }>(`/itineraries/${id}/shares`, { method: 'POST', body: JSON.stringify({ expires_days }) }) }
export async function saveFeedback(id: number, rating: number, comment: string) { return api(`/itineraries/${id}/feedback`, { method: 'PUT', body: JSON.stringify({ rating, comment }) }) }
export async function getFeedback(id: number) { return api<{ rating: number | null; comment: string; average: number | null; count: number }>(`/itineraries/${id}/feedback`) }
export async function getAuthSessions() { return api<{ id: number; device_name: string | null; created_at: string; last_used_at: string; expires_at: string; current: boolean }[]>('/auth/sessions') }
export async function revokeAuthSession(id: number) { return api(`/auth/sessions/${id}`, { method: 'DELETE' }) }
export async function changePassword(current_password: string, new_password: string) { return api('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }) }
export async function changeEmail(password: string, email: string) { return api('/auth/me/email', { method: 'PATCH', body: JSON.stringify({ password, email }) }) }
export async function logoutAllDevices() { return api('/auth/logout-all', { method: 'POST', body: '{}' }) }
