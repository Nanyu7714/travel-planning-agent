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
  if ((field === 'password' || field === 'new_password') && issue.type?.includes('too_short')) return '密码至少输入 10 个字符'
  if ((field === 'password' || field === 'new_password') && issue.type?.includes('too_long')) return '密码不能超过 128 个字符'
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
    if (!(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
    if (method !== 'GET') headers.set('X-CSRF-Token', csrfToken())
    return fetch(apiUrl(path), { ...options, headers, credentials: 'include' })
  }
  let response = await send()
  const publicAuthPaths = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/verify-email', '/auth/send-verification-code', '/auth/resend-verification', '/auth/forgot-password', '/auth/reset-password', '/auth/change-email/confirm']
  const canRefresh = !publicAuthPaths.includes(path)
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

export type City = { id: number; slug: string; name: string; description: string; season: string; budget: string; recommended_days: string; image_url: string; support_level: string; planning_enabled: boolean; is_active: boolean }
export type Attraction = { id: number; city_id: number; name: string; description: string; tags: string[]; opening_hours: string; ticket_price: number; duration_minutes: number; area: string; image_url: string; source: string; is_active: boolean }
export type Ranking = { rank: number; attraction_id?: number; city_id?: number; name: string; score: number; reason: string; data_source?: string }
export type UserProfile = { display_name: string | null; preferences: string[]; avoid_places: string[] }
export type FavoriteItem = { target_type: 'city' | 'attraction' | 'itinerary'; target_id: number; name: string; description: string; image_url: string; city_id?: number }
export type RecentView = FavoriteItem & { viewed_at: string }
export type Itinerary = { id: number; title: string; city_name: string; days: number; status: string; budget_total: number; budget_scope: string; preferences: string[]; lock_version: number; validation?: Record<string, unknown>; itinerary_days: { day_number: number; title: string; stops: { id: number; attraction_id?: number; name: string; start_time: string; end_time: string; note: string }[] }[] }
export type AgentRun = { id: number; status: string; algorithm_version: string; input: Record<string, unknown>; summary: { selected_count?: number; requested_stop_count?: number; budget_repair_applied?: boolean; ticket_estimate?: number } | null; created_at: string; steps: { sequence: number; tool_name: string; input: Record<string, unknown>; output: Record<string, unknown>; status: string }[] }
export type MediaAsset = { id: number; city_id: number; attraction_id: number | null; purpose: string; content_key: string; storage_type: 'remote_url' | 'local_file' | 'object_storage'; url: string | null; storage_path: string | null; mime_type: string | null; alt_text: string; source_name: string | null; source_author: string | null; license_name: string | null; attribution_url: string | null; verification_status: 'approved' | 'needs_review' | 'missing' | 'rejected_wrong_city'; is_active: boolean }
export type SessionBulkAction = 'archive' | 'restore' | 'delete'
export type CommunityComment = { id: number; body: string; created_at: string; author: { id: number; name: string }; can_manage: boolean }
export type CommunityPost = { id: number; title: string; body: string; city_name: string; status: 'published' | 'hidden'; created_at: string; updated_at: string; author: { id: number; name: string }; itinerary: { title: string; city_name: string; days: number; budget_total: number; preferences: string[]; itinerary_days: { day_number: number; title: string; stops: { name: string; start_time: string; end_time: string }[] }[] }; images: { id: number; url: string; alt_text: string }[]; like_count: number; favorite_count: number; comment_count: number; liked: boolean; favorited: boolean; can_manage: boolean; comments?: CommunityComment[] }
export type AuthAction = { message: string; dev_action_url?: string | null; masked_email?: string | null; expires_in_seconds?: number | null; retry_after_seconds?: number | null }

export async function getCities() { return api<City[]>('/cities') }
export async function searchCities(query: string) { return api<City[]>(`/cities/search?q=${encodeURIComponent(query)}`) }
export async function searchAttractions(query: string) { return api<Attraction[]>(`/attractions/search?q=${encodeURIComponent(query)}`) }
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
export async function bulkUpdateSessions(sessionIds: number[], action: SessionBulkAction, password?: string) {
  return api<{ processed_count: number; action: SessionBulkAction }>('/sessions/bulk', { method: 'POST', body: JSON.stringify({ session_ids: sessionIds, action, password }) })
}
export async function clearRecentViews() { return api('/recent-views', { method: 'DELETE', body: '{}' }) }
export async function recordRecentView(type: 'city' | 'attraction', id: number) { return api(`/recent-views?target_type=${type}&target_id=${id}`, { method: 'POST', body: '{}' }) }
export async function getItinerary(id: number) { return api<Itinerary>(`/itineraries/${id}`) }
export async function getItineraryAgentRun(id: number) { return api<AgentRun>(`/itineraries/${id}/agent-run`) }
export async function getAdminMediaAssets(cityId?: number, status?: string) { const params = new URLSearchParams(); if (cityId) params.set('city_id', String(cityId)); if (status) params.set('verification_status', status); return api<MediaAsset[]>(`/admin/media-assets?${params.toString()}`) }
export async function autofillMediaAsset(id: number) { return api<MediaAsset>(`/admin/media-assets/${id}/autofill`, { method: 'POST', body: '{}' }) }
export async function updateMediaAsset(id: number, body: Partial<MediaAsset>) { return api<MediaAsset>(`/admin/media-assets/${id}`, { method: 'PATCH', body: JSON.stringify(body) }) }
export async function uploadMediaAssetFile(id: number, file: File) { const form = new FormData(); form.append('file', file); return api<MediaAsset>(`/admin/media-assets/${id}/upload`, { method: 'POST', body: form }) }
export type PhotoFetchResult = { keyword: string; fetched: number; skipped: number; providers: string[]; items: MediaAsset[] }
export type PhotoProviderInfo = { providers: string[]; download_enabled: boolean }
export async function getAdminPhotos(cityId?: number, attractionId?: number) { const params = new URLSearchParams(); if (cityId) params.set('city_id', String(cityId)); if (attractionId) params.set('attraction_id', String(attractionId)); return api<MediaAsset[]>(`/admin/photos?${params.toString()}`) }
export async function fetchAdminPhotos(body: { city_id: number; attraction_id?: number | null; keyword: string; limit: number; auto_approve: boolean }) { return api<PhotoFetchResult>('/admin/photos/fetch', { method: 'POST', body: JSON.stringify(body) }) }
export async function deleteAdminPhoto(id: number) { return api(`/admin/photos/${id}`, { method: 'DELETE', body: '{}' }) }
export async function usePhotoAsCover(id: number) { return api<MediaAsset>(`/admin/photos/${id}/use-as-cover`, { method: 'POST', body: '{}' }) }
export async function getPhotoProviders() { return api<PhotoProviderInfo>('/admin/photos/providers') }
export async function updateItinerary(id: number, body: Record<string, unknown>) { return api<Itinerary>(`/itineraries/${id}`, { method: 'PUT', body: JSON.stringify(body) }) }
export type ReplanAction = { type: 'set_budget' | 'set_days' | 'set_preferences' | 'remove_attraction' | 'replace_attraction'; value?: number | null; attraction_id?: number | null; new_attraction_id?: number | null; preferences?: string[] | null }
export type ReplanPreview = { status: 'ready' | 'needs_clarification'; summary: string; actions: ReplanAction[]; questions: string[]; parser: 'llm' | 'local' }
export async function previewReplanItinerary(id: number, instruction: string) { return api<ReplanPreview>(`/itineraries/${id}/replan/preview`, { method: 'POST', body: JSON.stringify({ instruction }) }) }
export async function replanItinerary(id: number, instruction: string, actions: ReplanAction[]) { return api<Itinerary>(`/itineraries/${id}/replan`, { method: 'POST', body: JSON.stringify({ instruction, actions }) }) }
export async function getItineraryRevisions(id: number) { return api<{ id: number; version_no: number; reason: string; created_at: string }[]>(`/itineraries/${id}/revisions`) }
export async function restoreItineraryRevision(id: number, version: number) { return api<Itinerary>(`/itineraries/${id}/revisions/${version}/restore`, { method: 'POST', body: '{}' }) }
export async function createShare(id: number, expires_days = 30) { return api<{ id: number; share_url: string; expires_at: string }>(`/itineraries/${id}/shares`, { method: 'POST', body: JSON.stringify({ expires_days }) }) }
export type ShareHistoryItem = { id: number; itinerary_id: number; itinerary_title: string; city_name: string; status: 'active' | 'expired' | 'revoked'; expires_at: string; revoked_at: string | null; created_at: string }
export async function getMyShares() { return api<ShareHistoryItem[]>('/shares') }
export async function revokeShare(itineraryId: number, shareId: number) { return api(`/itineraries/${itineraryId}/shares/${shareId}`, { method: 'DELETE' }) }
export async function saveFeedback(id: number, rating: number, comment: string) { return api(`/itineraries/${id}/feedback`, { method: 'PUT', body: JSON.stringify({ rating, comment }) }) }
export async function getFeedback(id: number) { return api<{ rating: number | null; comment: string; average: number | null; count: number; status: 'open' | 'in_progress' | 'resolved' | null; admin_reply: string | null; replied_at: string | null }>(`/itineraries/${id}/feedback`) }
export type AdminFeedback = { id: number; itinerary_id: number; username: string; email: string; city_name: string; itinerary_title: string; rating: number; comment: string; status: 'open' | 'in_progress' | 'resolved'; assigned_admin_id: number | null; assigned_admin_username: string | null; admin_reply: string | null; replied_at: string | null; handled_at: string | null; created_at: string; updated_at: string }
export type FeedbackAssignee = { id: number; username: string }
export async function getAdminFeedback(page = 1, status = 'all') { return api<{ items: AdminFeedback[]; total: number; page: number; page_size: number }>(`/admin/feedback?page=${page}&page_size=10&status=${status}`) }
export async function getFeedbackAssignees() { return api<FeedbackAssignee[]>('/admin/feedback/assignees') }
export async function updateAdminFeedback(id: number, body: Partial<Pick<AdminFeedback, 'status' | 'assigned_admin_id' | 'admin_reply'>>) { return api<AdminFeedback>(`/admin/feedback/${id}`, { method: 'PATCH', body: JSON.stringify(body) }) }
export async function getCommunityPosts(city = '', page = 1) { const params = new URLSearchParams({ page: String(page) }); if (city) params.set('city', city); return api<{ items: CommunityPost[]; total: number; page: number; page_size: number }>(`/community/posts?${params.toString()}`) }
export async function getMyCommunityPosts() { return api<CommunityPost[]>('/community/me/posts') }
export async function getCommunityPost(id: number) { return api<CommunityPost>(`/community/posts/${id}`) }
export async function createCommunityPost(body: { itinerary_id: number; title: string; body: string }) { return api<CommunityPost>('/community/posts', { method: 'POST', body: JSON.stringify(body) }) }
export async function updateCommunityPost(id: number, body: { title: string; body: string }) { return api<CommunityPost>(`/community/posts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }) }
export async function withdrawCommunityPost(id: number) { return api(`/community/posts/${id}`, { method: 'DELETE', body: '{}' }) }
export async function uploadCommunityImages(id: number, files: File[]) { const form = new FormData(); files.forEach((file) => form.append('files', file)); return api<{ id: number; url: string; alt_text: string }[]>(`/community/posts/${id}/images`, { method: 'POST', body: form }) }
export async function setCommunityLike(id: number, active: boolean) { return api(`/community/posts/${id}/like`, { method: active ? 'PUT' : 'DELETE', body: active ? '{}' : undefined }) }
export async function setCommunityFavorite(id: number, active: boolean) { return api(`/community/posts/${id}/favorite`, { method: active ? 'PUT' : 'DELETE', body: active ? '{}' : undefined }) }
export async function createCommunityComment(id: number, body: string) { return api<CommunityComment>(`/community/posts/${id}/comments`, { method: 'POST', body: JSON.stringify({ body }) }) }
export async function reportCommunityContent(target_type: 'post' | 'comment' | 'image', target_id: number, reason: string) { return api('/community/reports', { method: 'POST', body: JSON.stringify({ target_type, target_id, reason }) }) }
export async function getAuthSessions() { return api<{ id: number; device_name: string | null; created_at: string; last_used_at: string; expires_at: string; current: boolean }[]>('/auth/sessions') }
export async function revokeAuthSession(id: number) { return api(`/auth/sessions/${id}`, { method: 'DELETE' }) }
export async function changePassword(current_password: string, new_password: string) { return api('/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }) }
export async function registerAccount(username: string, email: string, password: string) { return api<AuthAction>('/auth/register', { method: 'POST', body: JSON.stringify({ username, email, password }) }) }
export async function verifyEmail(email: string, code: string) { return api<AuthAction>('/auth/verify-email', { method: 'POST', body: JSON.stringify({ email, code }) }) }
export async function sendVerificationCode(email: string) { return api<AuthAction>('/auth/send-verification-code', { method: 'POST', body: JSON.stringify({ email }) }) }
export async function resendVerification(email: string) { return sendVerificationCode(email) }
export async function forgotPassword(email: string) { return api<AuthAction>('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) }) }
export async function resetPassword(token: string, new_password: string) { return api('/auth/reset-password', { method: 'POST', body: JSON.stringify({ token, new_password }) }) }
export async function changeEmail(password: string, email: string) { return api<AuthAction>('/auth/change-email', { method: 'POST', body: JSON.stringify({ password, email }) }) }
export async function confirmEmailChange(token: string) { return api<AuthAction>('/auth/change-email/confirm', { method: 'POST', body: JSON.stringify({ token }) }) }
export async function logoutAllDevices() { return api('/auth/logout-all', { method: 'POST', body: '{}' }) }
