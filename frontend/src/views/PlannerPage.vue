<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowUp, Bot, Check, Clock3, LoaderCircle, Map, Send, Square, Trash2, UserRound } from 'lucide-vue-next'
import { api, apiUrl, bulkUpdateSessions, getCities, type City, type SessionBulkAction } from '../api'
import { useRouter } from 'vue-router'
import SessionRail, { type ChatSession } from '../components/SessionRail.vue'

type MessagePayload = {
  type?: string
  itinerary_id?: number
  city?: string
  destination?: string
  destination_city_id?: number
  origin_city_id?: number
  origin?: string
  days?: number
  traveler_count?: number
  interests?: string[]
  avoid_places?: string[]
  pace?: string
  budget_total?: number | null
  transport?: string
  start_date?: string | null
  confirmed_job_id?: number
}
type Message = { id?: number; role: string; content: string; payload?: MessagePayload }
type ServerEvent = { event_id: number | null; session_id: string; turn_id: string | null; type: string; payload: Record<string, unknown> }
type AgentStatus = { mode: 'llm' | 'local'; state: 'disabled' | 'configured' | 'connected' | 'degraded'; model: string | null; label: string }
type PlanDraft = { origin_city_id: number | null; destination_city_id: number | null; destination: string; days: number; traveler_count: number; start_date: string; budget_total: number | null; interests: string; avoid_places: string; pace: 'relaxed' | 'balanced' | 'packed'; transport: 'public_transport' | 'taxi' | 'walking' | 'driving' }
const router = useRouter()
const messages = ref<Message[]>([{ role: 'assistant', content: '你好，我是行旅规划助手。我们可以先聊聊你的旅行喜好；需要规划时告诉我，我会收集完整需求并请你确认。' }])
const input = ref('')
const sending = ref(false)
const stage = ref('等待你的需求')
const sessionId = ref<number | null>(null)
const jobId = ref<number | null>(null)
const cities = ref<City[]>([])
const pendingConfirmation = ref<MessagePayload | null>(null)
const requirementDraft = ref<PlanDraft>(blankRequirement())
const agentStatus = ref<AgentStatus>({ mode: 'local', state: 'disabled', model: null, label: '正在检查大模型连接' })
const scrollBox = ref<HTMLElement | null>(null)
const lastEventId = ref(0)
const sessions = ref<ChatSession[]>([])
const archivedView = ref(false)
const railCollapsed = ref(false)
const selectionMode = ref(false)
const selectedSessionIds = ref<number[]>([])
const bulkAction = ref<SessionBulkAction | null>(null)
const bulkTargetIds = ref<number[]>([])
const bulkPassword = ref('')
const bulkError = ref('')
const bulkSubmitting = ref(false)
let eventSource: EventSource | null = null
let reconcilingSseError = false

const briefLocked = computed(() => !sessionId.value || archivedView.value || sending.value)
const bulkActionLabel = computed(() => bulkAction.value === 'delete' ? '删除' : bulkAction.value === 'restore' ? '恢复' : '归档')
const bulkNeedsPassword = computed(() => bulkAction.value === 'delete' && bulkTargetIds.value.length >= 3)

const activeSessionKey = 'travel-planner-active-session'
const eventCursorKey = (id: number) => `travel-planner-event-${id}`

function newIdempotencyKey() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
}

function blankRequirement(): PlanDraft {
  return { origin_city_id: null, destination_city_id: null, destination: '', days: 3, traveler_count: 1, start_date: new Date().toISOString().slice(0, 10), budget_total: null, interests: '', avoid_places: '', pace: 'balanced', transport: 'public_transport' }
}

function splitList(value: string) {
  return [...new Set(value.split(/[、,，]/).map((item) => item.trim()).filter(Boolean))]
}

function resetRequirement() {
  requirementDraft.value = blankRequirement()
  pendingConfirmation.value = null
}

async function loadAgentStatus() {
  try { agentStatus.value = await api<AgentStatus>('/agent/status') } catch { agentStatus.value = { mode: 'local', state: 'degraded', model: null, label: '无法读取大模型状态' } }
}

async function ensureSession() {
  if (!sessionId.value) {
    const session = await api<ChatSession>('/sessions', { method: 'POST', body: '{}' })
    sessionId.value = session.id
    sessions.value.unshift(session)
    localStorage.setItem(activeSessionKey, String(session.id))
  }
  return sessionId.value
}

async function loadSession(session: ChatSession) {
  sessionId.value = session.id
  localStorage.setItem(activeSessionKey, String(session.id))
  const [history, cursor] = await Promise.all([
    api<Message[]>(`/sessions/${session.id}/messages`),
    api<{ last_event_id: number }>(`/sessions/${session.id}/events/cursor`),
  ])
  messages.value = history.length ? history : [{ role: 'assistant', content: '这段对话还没有消息。可以先告诉我怎么称呼你，或者聊聊旅行偏好。' }]
  const latestConfirmation = [...history].reverse().find((message) => message.payload?.type === 'plan_confirm')?.payload
  if (latestConfirmation) {
    applyRequirement(latestConfirmation)
    pendingConfirmation.value = latestConfirmation.confirmed_job_id ? null : latestConfirmation
  } else {
    resetRequirement()
  }
  lastEventId.value = cursor.last_event_id
  localStorage.setItem(eventCursorKey(session.id), String(lastEventId.value))
}

async function loadSessions() {
  try {
    sessions.value = await api<ChatSession[]>(`/sessions?archived=${archivedView.value}`)
    resetSelection()
    const savedId = Number(localStorage.getItem(activeSessionKey))
    const active = sessions.value.find((session) => session.id === savedId) || sessions.value[0]
    if (active) await loadSession(active)
  } catch {
    // 未登录时保留欢迎语，发送消息时再提示登录。
  }
}

async function newSession() {
  if (archivedView.value) {
    archivedView.value = false
    sessions.value = await api<ChatSession[]>('/sessions?archived=false')
  }
  sessionId.value = null
  lastEventId.value = 0
  localStorage.removeItem(activeSessionKey)
  messages.value = [{ role: 'assistant', content: '新的对话已经准备好。可以先聊旅行偏好，需要规划时再告诉我。' }]
  resetRequirement()
  resetSelection()
}

async function switchSessionView() {
  archivedView.value = !archivedView.value
  sessions.value = await api<ChatSession[]>(`/sessions?archived=${archivedView.value}`)
  resetSelection()
  if (sessions.value[0]) await loadSession(sessions.value[0])
  else {
    sessionId.value = null
    lastEventId.value = 0
    localStorage.removeItem(activeSessionKey)
    messages.value = [{ role: 'assistant', content: archivedView.value ? '目前没有已归档的对话。' : '新的对话已经准备好。可以先聊旅行偏好，需要规划时再告诉我。' }]
    resetRequirement()
  }
}

async function updateSession(session: ChatSession, patch: { title?: string; is_pinned?: boolean; archived?: boolean }) {
  const updated = await api<ChatSession>(`/sessions/${session.id}`, { method: 'PATCH', body: JSON.stringify(patch) })
  const index = sessions.value.findIndex((item) => item.id === session.id)
  if (index >= 0) sessions.value[index] = updated
  return updated
}

async function renameSession(session: ChatSession) {
  const title = window.prompt('输入新的会话名称', session.title)?.trim()
  if (!title || title === session.title) return
  try { await updateSession(session, { title }) } catch (error) { window.alert(error instanceof Error ? error.message : '重命名失败') }
}

async function togglePin(session: ChatSession) {
  try {
    await updateSession(session, { is_pinned: !session.is_pinned })
    sessions.value.sort((a, b) => Number(b.is_pinned) - Number(a.is_pinned) || new Date(b.updated_at || b.created_at).getTime() - new Date(a.updated_at || a.created_at).getTime())
  } catch (error) { window.alert(error instanceof Error ? error.message : '操作失败') }
}

async function toggleArchive(session: ChatSession) {
  openBulkAction(session.archived_at ? 'restore' : 'archive', [session.id])
}

function deleteSession(session: ChatSession) {
  openBulkAction('delete', [session.id])
}

function resetSelection() {
  selectionMode.value = false
  selectedSessionIds.value = []
}

function toggleSelectionMode() {
  selectionMode.value = !selectionMode.value
  selectedSessionIds.value = []
}

function toggleSelection(session: ChatSession) {
  selectedSessionIds.value = selectedSessionIds.value.includes(session.id)
    ? selectedSessionIds.value.filter((id) => id !== session.id)
    : [...selectedSessionIds.value, session.id]
}

function toggleSelectAll() {
  const visibleIds = sessions.value.map((session) => session.id)
  selectedSessionIds.value = selectedSessionIds.value.length === visibleIds.length ? [] : visibleIds
}

function openBulkAction(action: SessionBulkAction, sessionIds = selectedSessionIds.value) {
  if (!sessionIds.length) return
  bulkAction.value = action
  bulkTargetIds.value = [...new Set(sessionIds)]
  bulkPassword.value = ''
  bulkError.value = ''
}

function closeBulkAction(force = false) {
  if (bulkSubmitting.value && !force) return
  bulkAction.value = null
  bulkTargetIds.value = []
  bulkPassword.value = ''
  bulkError.value = ''
}

async function confirmBulkAction() {
  if (!bulkAction.value || !bulkTargetIds.value.length) return
  bulkSubmitting.value = true
  bulkError.value = ''
  try {
    const action = bulkAction.value
    const affectedIds = [...bulkTargetIds.value]
    await bulkUpdateSessions(affectedIds, action, bulkPassword.value || undefined)
    sessions.value = sessions.value.filter((item) => !affectedIds.includes(item.id))
    affectedIds.forEach((id) => localStorage.removeItem(eventCursorKey(id)))
    const activeAffected = sessionId.value !== null && affectedIds.includes(sessionId.value)
    closeBulkAction(true)
    resetSelection()
    if (activeAffected) await newSession()
  } catch (error) {
    bulkError.value = error instanceof Error ? error.message : `${bulkActionLabel.value}失败，请重试。`
  } finally {
    bulkSubmitting.value = false
  }
}

async function clearConversation() {
  if (!sessionId.value || !window.confirm('确定删除当前对话吗？它会从你的会话列表中移除，如需恢复请联系管理员。')) return
  await api(`/sessions/${sessionId.value}/clear`, { method: 'POST', body: '{}' })
  sessions.value = sessions.value.filter((session) => session.id !== sessionId.value)
  messages.value = [{ role: 'assistant', content: '对话已从你的列表中移除。可以开始一段新的旅行对话。' }]
  lastEventId.value = 0
  localStorage.removeItem(eventCursorKey(sessionId.value))
  sessionId.value = null
  localStorage.removeItem(activeSessionKey)
}
async function sendMessage() {
  const content = input.value.trim(); if (!content || sending.value) return
  messages.value.push({ role: 'user', content }); input.value = ''; sending.value = true; stage.value = '正在处理你的消息'
  try {
    const id = await ensureSession(); const job = await api<{ job_id: number; session_title: string }>(`/sessions/${id}/messages`, { method: 'POST', headers: { 'Idempotency-Key': newIdempotencyKey() }, body: JSON.stringify({ content }) }); jobId.value = job.job_id
    const activeSession = sessions.value.find((session) => session.id === id)
    if (activeSession) activeSession.title = job.session_title
    await connectEvents(id)
  } catch (error) { messages.value.push({ role: 'assistant', content: error instanceof Error ? error.message : '请先登录后开始规划。' }); sending.value = false; stage.value = '需要登录' }
}
function applyRequirement(payload: MessagePayload) {
  const matchedCity = cities.value.find((city) => city.id === payload.destination_city_id || city.name === payload.destination)
  requirementDraft.value = {
    destination_city_id: payload.destination_city_id || matchedCity?.id || null,
    origin_city_id: payload.origin_city_id || cities.value.find((city) => city.name === payload.origin)?.id || null,
    destination: payload.destination || matchedCity?.name || '',
    days: payload.days || 3,
    traveler_count: payload.traveler_count || 1,
    start_date: payload.start_date || new Date().toISOString().slice(0, 10),
    budget_total: payload.budget_total ?? null,
    interests: (payload.interests || []).join('、'),
    avoid_places: (payload.avoid_places || []).join('、'),
    pace: payload.pace === 'relaxed' || payload.pace === 'packed' ? payload.pace : 'balanced',
    transport: payload.transport === 'taxi' || payload.transport === 'walking' || payload.transport === 'driving' ? payload.transport : 'public_transport',
  }
}
async function confirmPlan(payload?: MessagePayload) {
  if (!payload || !sessionId.value || sending.value) return
  if (!requirementDraft.value.destination_city_id) {
    messages.value.push({ role: 'assistant', content: '请先在右侧需求清单中选择目的地。' })
    return
  }
  if (!requirementDraft.value.origin_city_id) {
    messages.value.push({ role: 'assistant', content: '请选择出发城市后再生成行程，这样才能计算往返跨城路线和费用。' })
    return
  }
  if (requirementDraft.value.origin_city_id !== requirementDraft.value.destination_city_id && requirementDraft.value.transport === 'walking') {
    messages.value.push({ role: 'assistant', content: '跨城行程不支持步行方式，请选择公共交通、打车或自驾。' })
    return
  }
  sending.value = true
  stage.value = '正在提交已确认的需求'
  try {
    const job = await api<{ job_id: number }>(`/sessions/${sessionId.value}/plan-confirm`, {
      method: 'POST',
      headers: { 'Idempotency-Key': newIdempotencyKey() },
      body: JSON.stringify({ confirmed: true, patch: {
        origin_city_id: requirementDraft.value.origin_city_id,
        destination_city_id: requirementDraft.value.destination_city_id,
        days: Number(requirementDraft.value.days),
        traveler_count: Number(requirementDraft.value.traveler_count),
        start_date: requirementDraft.value.start_date,
        budget_total: requirementDraft.value.budget_total,
        interests: splitList(requirementDraft.value.interests),
        avoid_places: splitList(requirementDraft.value.avoid_places),
        pace: requirementDraft.value.pace,
        transport: requirementDraft.value.transport,
      } }),
    })
    jobId.value = job.job_id
    payload.confirmed_job_id = job.job_id
    pendingConfirmation.value = null
    await connectEvents(sessionId.value)
  } catch (error) {
    messages.value.push({ role: 'assistant', content: error instanceof Error ? error.message : '确认失败，请重试。' })
    sending.value = false
  }
}
function modifyPlan(payload?: MessagePayload) {
  if (payload) {
    applyRequirement(payload)
    pendingConfirmation.value = payload
  }
}
async function stopPlanning() {
  if (!sessionId.value) return
  await api(`/sessions/${sessionId.value}/stop`, { method: 'POST', body: '{}' })
  eventSource?.close()
  eventSource = null
  sending.value = false
  stage.value = '已停止'
}
async function connectEvents(id: number) {
  await nextTick()
  eventSource?.close()
  const source = new EventSource(apiUrl(`/sessions/${id}/events?after=${lastEventId.value}`), { withCredentials: true })
  eventSource = source
  const rememberEvent = (event: Event) => {
    const eventId = Number((event as MessageEvent).lastEventId || 0)
    if (eventId) {
      lastEventId.value = eventId
      localStorage.setItem(eventCursorKey(id), String(eventId))
    }
  }
  const parse = (event: Event) => JSON.parse((event as MessageEvent).data) as ServerEvent
  let deliveredAgentError = false
  const reconcileConnectionError = async () => {
    if (!sending.value || eventSource !== source || reconcilingSseError) return
    reconcilingSseError = true
    try {
      if (!jobId.value) { stage.value = '实时连接正在重试'; return }
      const job = await api<{ status: string; error_message: string | null }>(`/planning-jobs/${jobId.value}`)
      if (job.status === 'failed') {
        if (!deliveredAgentError) messages.value.push({ role: 'assistant', content: job.error_message || '规划失败，请调整条件后重试。' })
        source.close(); if (eventSource === source) eventSource = null; sending.value = false; stage.value = '规划失败'
      } else if (job.status === 'completed' || job.status === 'cancelled') {
        source.close(); if (eventSource === source) eventSource = null; sending.value = false; stage.value = job.status === 'cancelled' ? '已停止' : '规划完成'
      } else stage.value = '实时连接正在重试'
    } catch { stage.value = '实时连接正在重试' }
    finally { reconcilingSseError = false }
  }
  const close = (label = '处理完成') => { source.close(); if (eventSource === source) eventSource = null; sending.value = false; stage.value = label; void loadAgentStatus() }
  source.addEventListener('stage', (event) => { rememberEvent(event); stage.value = String(parse(event).payload.message || '正在处理') })
  source.addEventListener('message', (event) => { rememberEvent(event); const data = parse(event).payload; messages.value.push({ role: 'assistant', content: String(data.content || ''), payload: data as MessagePayload }) })
  source.addEventListener('clarify', (event) => { rememberEvent(event); const data = parse(event).payload; messages.value.push({ role: 'assistant', content: String(data.content || data.message || ''), payload: data as MessagePayload }) })
  source.addEventListener('plan_confirm', (event) => { rememberEvent(event); const data = parse(event).payload as MessagePayload & { content?: string }; applyRequirement(data); pendingConfirmation.value = data; messages.value.push({ role: 'assistant', content: data.content || '请确认旅行需求。', payload: data }) })
  source.addEventListener('itinerary', (event) => {
    rememberEvent(event)
    const data = parse(event).payload as MessagePayload & { content?: string }
    messages.value.push({ role: 'assistant', content: data.content || '行程已生成。', payload: data })
    pendingConfirmation.value = null
    const itineraryId = Number(data.itinerary_id || 0)
    if (itineraryId) {
      close('规划完成')
      void router.push(`/itineraries/${itineraryId}`)
    }
  })
  source.addEventListener('done', (event) => { rememberEvent(event); const status = String(parse(event).payload.status || 'completed'); close(status === 'cancelled' ? '已停止' : status === 'failed' ? '规划失败' : status === 'awaiting_confirmation' ? '等待确认' : '规划完成') })
  source.addEventListener('reset', async (event) => { const data = parse(event); messages.value.push({ role: 'assistant', content: String(data.payload.message || '事件已过期，正在重新同步。') }); const active = sessions.value.find((item) => item.id === id); if (active) await loadSession(active); close('已重新同步') })
  source.addEventListener('error', (event) => { if ((event as MessageEvent).data) { rememberEvent(event); const data = parse(event).payload; messages.value.push({ role: 'assistant', content: String(data.message || '规划失败') }) } })
  source.onerror = () => { if (sending.value) { source.close(); sending.value = false; stage.value = '连接已断开，可从任务列表恢复' } }
  source.addEventListener('agent_error', (event) => {
    rememberEvent(event)
    const data = parse(event).payload
    deliveredAgentError = true
    messages.value.push({ role: 'assistant', content: String(data.message || '规划失败，请调整条件后重试。') })
    stage.value = '规划失败，正在确认任务状态'
  })
  // Browser transport errors are retried by EventSource; first reconcile the persisted job state.
  source.onerror = () => { void reconcileConnectionError() }
}
function openItinerary(id?: number) { if (id) router.push(`/itineraries/${id}`) }
onMounted(async () => { cities.value = await getCities().catch(() => []); await Promise.all([loadSessions(), loadAgentStatus()]); await nextTick(); scrollBox.value?.scrollTo({ top: scrollBox.value.scrollHeight }) })
onBeforeUnmount(() => { eventSource?.close(); eventSource = null })
</script>

<template>
  <div :class="['planner-frame', { 'rail-collapsed': railCollapsed }]">
    <SessionRail
      :sessions="sessions"
      :active-session-id="sessionId"
      :archived-view="archivedView"
      :selection-mode="selectionMode"
      :selected-session-ids="selectedSessionIds"
      @select="loadSession"
      @create="newSession"
      @switch-view="switchSessionView"
      @rename="renameSession"
      @pin="togglePin"
      @archive="toggleArchive"
      @delete="deleteSession"
      @toggle-selection-mode="toggleSelectionMode"
      @toggle-selection="toggleSelection"
      @select-all="toggleSelectAll"
      @bulk-archive="openBulkAction(archivedView ? 'restore' : 'archive')"
      @bulk-delete="openBulkAction('delete')"
      @collapse="railCollapsed = $event"
    />

    <div class="planner-shell">
      <section class="conversation-panel">
        <div class="planner-header">
          <div><span class="eyebrow">AI TRAVEL PLANNER</span><h1>把想法说出来，路线交给我</h1></div>
          <div class="planner-actions">
            <button v-if="sending" class="icon-button stop-action" aria-label="停止当前任务" title="停止当前任务" @click="stopPlanning"><Square :size="15" /></button>
            <button class="icon-button" aria-label="清空当前对话" title="清空当前对话" :disabled="!sessionId || sending || archivedView" @click="clearConversation"><Trash2 :size="17" /></button>
            <span :class="['live-indicator', agentStatus.state]" :title="agentStatus.model || agentStatus.label"><i></i>{{ agentStatus.label }}</span>
          </div>
        </div>

        <div ref="scrollBox" class="message-list">
          <div v-for="(message, index) in messages" :key="index" :class="['message-line', message.role]">
            <div class="avatar"><UserRound v-if="message.role === 'user'" :size="16" /><Bot v-else :size="16" /></div>
            <div class="message-content">
              <p>{{ message.content }}</p>
              <div v-if="message.payload?.type === 'plan_confirm'" class="confirm-card">
                <dl>
                  <div><dt>目的地</dt><dd>{{ message.payload.destination }}</dd></div>
                  <div><dt>出发城市</dt><dd>{{ message.payload.origin || '请在右侧补充' }}</dd></div>
                  <div><dt>天数</dt><dd>{{ message.payload.days }} 天</dd></div>
                  <div><dt>人数</dt><dd>{{ message.payload.traveler_count }} 人</dd></div>
                  <div><dt>出发日期</dt><dd>{{ message.payload.start_date || '请在右侧补充' }}</dd></div>
                  <div><dt>偏好</dt><dd>{{ message.payload.interests?.join('、') }}</dd></div>
                </dl>
                <small>可在右侧清单修改条件；预算会纳入往返跨城、景点间交通、门票、餐饮和住宿估算。</small>
                <div class="confirm-actions">
                  <button class="primary-button" :disabled="archivedView || sending || !!message.payload.confirmed_job_id" @click="confirmPlan(message.payload)">{{ message.payload.confirmed_job_id ? '已确认' : '确认并生成行程' }}</button>
                  <button class="secondary-button" :disabled="archivedView || sending || !!message.payload.confirmed_job_id" @click="modifyPlan(message.payload)">在右侧修改</button>
                </div>
              </div>
              <button v-if="message.payload?.type === 'itinerary'" class="result-link" @click="openItinerary(message.payload.itinerary_id)"><Map :size="16" />查看 {{ message.payload.city }}{{ message.payload.days }}日行程</button>
            </div>
          </div>
          <div v-if="sending" class="message-line assistant"><div class="avatar"><LoaderCircle class="spin" :size="16" /></div><div class="message-content"><p class="stage-text">{{ stage }}</p></div></div>
        </div>

        <form class="composer" @submit.prevent="sendMessage">
          <textarea v-model="input" :disabled="archivedView" :placeholder="archivedView ? '归档会话为只读，恢复后可继续对话' : '例如：我想去成都玩 2 天，喜欢美食和慢节奏'" rows="2" @keydown.enter.exact.prevent="sendMessage"></textarea>
          <button class="send-button" aria-label="发送" type="submit" :disabled="archivedView"><ArrowUp v-if="input" :size="19" /><Send v-else :size="18" /></button>
          <div class="composer-note"><Clock3 :size="13" />{{ archivedView ? '恢复会话后可以继续规划' : '规划结果会区分已校验信息和待确认信息' }}</div>
        </form>
      </section>

      <aside class="summary-rail">
        <div class="summary-heading"><span class="eyebrow">TRIP BRIEF</span><h2>旅行需求清单</h2></div>
        <form class="brief-form" @submit.prevent="confirmPlan(pendingConfirmation || undefined)">
          <label>目的地<select v-model.number="requirementDraft.destination_city_id" :disabled="briefLocked"><option :value="null" disabled>待确定</option><option v-for="city in cities" :key="city.id" :value="city.id" :disabled="!city.planning_enabled">{{ city.name }}</option></select></label>
          <label>出发城市<select v-model.number="requirementDraft.origin_city_id" :disabled="briefLocked"><option :value="null" disabled>请选择出发城市</option><option v-for="city in cities" :key="city.id" :value="city.id">{{ city.name }}</option></select></label>
          <div class="brief-pair"><label>天数<input v-model.number="requirementDraft.days" type="number" min="2" max="5" :disabled="briefLocked" /></label><label>人数<input v-model.number="requirementDraft.traveler_count" type="number" min="1" max="20" :disabled="briefLocked" /></label></div>
          <label>出发日期<input v-model="requirementDraft.start_date" type="date" :disabled="briefLocked" /></label>
          <label>预算<input :value="requirementDraft.budget_total ?? ''" type="number" min="0" placeholder="待补充" :disabled="briefLocked" @input="requirementDraft.budget_total = ($event.target as HTMLInputElement).value ? Number(($event.target as HTMLInputElement).value) : null" /></label>
          <label>兴趣偏好<input v-model="requirementDraft.interests" placeholder="例如：摄影、美食" :disabled="briefLocked" /></label>
          <label>不想去的地方<input v-model="requirementDraft.avoid_places" placeholder="例如：过度拥挤" :disabled="briefLocked" /></label>
          <label>节奏<select v-model="requirementDraft.pace" :disabled="briefLocked"><option value="relaxed">轻松</option><option value="balanced">适中</option><option value="packed">紧凑</option></select></label>
          <label>交通<select v-model="requirementDraft.transport" :disabled="briefLocked"><option value="public_transport">公共交通</option><option value="taxi">打车</option><option value="walking">步行优先</option><option value="driving">自驾</option></select></label>
          <button v-if="pendingConfirmation" class="primary-button brief-confirm" type="submit" :disabled="archivedView || sending"><Check :size="16" />确认并生成行程</button>
        </form>
        <div class="summary-tip"><Check :size="16" /><span>{{ pendingConfirmation ? '清单由 AI 根据对话填写，你可以修改后再确认。' : sessionId ? '本轮对话已结束，你可以先补充或修改清单；AI 整理出完整需求后即可确认。' : '开始对话后，AI 会先整理清单并等待你确认。' }}</span></div>
      </aside>
    </div>

    <div v-if="bulkAction" class="bulk-dialog-backdrop" role="presentation" @click.self="closeBulkAction">
      <form class="bulk-dialog" role="dialog" aria-modal="true" :aria-labelledby="'bulk-dialog-title'" @submit.prevent="confirmBulkAction">
        <span class="eyebrow">CONFIRM ACTION</span>
        <h2 id="bulk-dialog-title">确认{{ bulkActionLabel }} {{ bulkTargetIds.length }} 条对话？</h2>
        <p v-if="bulkAction === 'delete'">删除后对话将从你的列表移除，如需恢复请联系管理员。</p>
        <p v-else-if="bulkAction === 'restore'">恢复后，对话会回到当前会话列表，可以继续规划。</p>
        <p v-else>归档后，对话将移到归档列表，之后可以恢复。</p>
        <label v-if="bulkNeedsPassword">当前账号密码<input v-model="bulkPassword" type="password" autocomplete="current-password" required placeholder="请输入密码确认批量删除" /></label>
        <p v-if="bulkError" class="bulk-error" role="alert">{{ bulkError }}</p>
        <div class="bulk-dialog-actions">
          <button class="secondary-button" type="button" :disabled="bulkSubmitting" @click="closeBulkAction">取消</button>
          <button :class="bulkAction === 'delete' ? 'danger-button' : 'primary-button'" type="submit" :disabled="bulkSubmitting">{{ bulkSubmitting ? '正在处理' : `确认${bulkActionLabel}` }}</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.planner-frame { max-width: 1440px; min-height: calc(100vh - 80px); margin: auto; display: grid; grid-template-columns: 220px minmax(0, 1fr) 280px; background: var(--color-canvas); transition: grid-template-columns 180ms ease; }
.planner-frame.rail-collapsed { grid-template-columns: 64px minmax(0, 1fr) 280px; }
.planner-frame > .planner-shell { display: contents; }
.conversation-panel { min-width: 0; min-height: calc(100vh - 80px); border-left: 1px solid var(--color-border-soft); border-right: 1px solid var(--color-border-soft); }
.planner-header { min-height: 88px; padding: 24px 48px; align-items: center; }
.planner-header h1 { font-size: 22px; }
.message-list { max-width: 900px; max-height: calc(100vh - 248px); margin: 0 auto; padding: 32px 48px; }
.message-line { max-width: 760px; margin-bottom: 24px; }
.message-content { max-width: 620px; }
.message-content p { border-radius: var(--radius-control); line-height: 1.5; }
.user .message-content p { background: var(--color-primary); border-color: var(--color-primary); color: var(--color-on-primary); }
.confirm-card { margin-top: 12px; padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.confirm-card dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 18px; margin: 0 0 12px; }
.confirm-card dl div { min-width: 0; }
.confirm-card dt { color: var(--color-muted); font-size: 12px; }
.confirm-card dd { margin: 4px 0 0; color: var(--color-ink); font-size: 14px; overflow-wrap: anywhere; }
.confirm-card small { color: var(--color-muted); line-height: 1.5; }
.confirm-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.summary-rail { min-width: 0; padding: 32px 24px; border-left: 0; background: var(--color-surface-soft); }
.summary-heading { padding-bottom: 16px; border-bottom-color: var(--color-border); }
.summary-heading h2 { margin: 0; font-size: 20px; }
.brief-form { display: grid; gap: 14px; padding-top: 20px; }
.brief-form label { display: grid; gap: 6px; color: var(--color-muted); font-size: 12px; }
.brief-form input, .brief-form select { width: 100%; min-width: 0; min-height: 48px; padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-ink); outline: 0; }
.brief-form input:focus, .brief-form select:focus { border-color: var(--color-ink); }
.brief-form input:disabled, .brief-form select:disabled { background: transparent; color: var(--color-ink); opacity: 1; }
.brief-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.brief-confirm { width: 100%; margin-top: 4px; }
.summary-tip { margin-top: 24px; padding: 12px; border-radius: var(--radius-control); background: var(--color-surface-strong); color: var(--color-muted); }
.stop-action { color: var(--color-danger); }
.live-indicator.disabled, .live-indicator.degraded { color: var(--color-muted); }
.live-indicator.disabled i, .live-indicator.degraded i { background: var(--color-muted); }
.live-indicator.configured { color: var(--color-muted); }
.live-indicator.configured i { background: var(--color-primary); }
.bulk-dialog-backdrop { position: fixed; z-index: 30; inset: 0; display: grid; place-items: center; padding: 20px; background: rgb(0 0 0 / 50%); }
.bulk-dialog { width: min(100%, 420px); padding: 28px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); box-shadow: 0 16px 48px rgb(31 45 48 / 22%); }
.bulk-dialog h2 { margin: 8px 0 10px; font-size: 21px; }
.bulk-dialog p { margin: 0; color: var(--color-muted); line-height: 1.6; }
.bulk-dialog label { display: grid; gap: 7px; margin-top: 18px; color: var(--color-ink); font-size: 13px; font-weight: 600; }
.bulk-dialog input { width: 100%; min-height: 48px; padding: 11px 12px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-ink); outline: 0; }
.bulk-dialog input:focus { border-color: var(--color-ink); }
.bulk-error { margin-top: 12px !important; color: var(--color-danger) !important; font-size: 13px; }
.bulk-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 24px; }
.danger-button { min-height: 42px; padding: 9px 15px; border: 1px solid var(--color-danger); border-radius: var(--radius-control); background: var(--color-danger); color: var(--color-on-primary); }
.danger-button:hover:not(:disabled) { filter: brightness(.94); }
@media (max-width: 1128px) { .planner-frame, .planner-frame.rail-collapsed { grid-template-columns: 64px minmax(0, 1fr) 260px; } .planner-frame .session-rail { display: none; } .planner-frame { grid-template-columns: minmax(0, 1fr) 260px; } }
@media (max-width: 744px) { .planner-frame, .planner-frame.rail-collapsed { display: block; min-height: calc(100vh - 64px); } .conversation-panel { min-height: auto; border: 0; } .planner-header { min-height: 0; padding: 24px 16px; align-items: flex-start; flex-direction: column; } .planner-header h1 { font-size: 21px; } .message-list { max-height: none; min-height: 420px; padding: 24px 16px; } .message-content { max-width: calc(100vw - 76px); } .composer { padding: 16px; } .summary-rail { border-top: 1px solid var(--color-border); padding: 24px 16px; } .bulk-dialog { padding: 22px; } }
@media (max-width: 520px) { .confirm-card dl { grid-template-columns: 1fr; } .confirm-actions { align-items: stretch; flex-direction: column; } .confirm-actions button { width: 100%; } }
</style>
