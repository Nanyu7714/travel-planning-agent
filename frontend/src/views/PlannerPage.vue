<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowUp, Bot, Check, Clock3, LoaderCircle, Map, Send, Square, Trash2, UserRound } from 'lucide-vue-next'
import { api, apiUrl, getCities, type City } from '../api'
import { useRouter } from 'vue-router'
import SessionRail, { type ChatSession } from '../components/SessionRail.vue'

type MessagePayload = {
  type?: string
  itinerary_id?: number
  city?: string
  destination?: string
  destination_city_id?: number
  days?: number
  traveler_count?: number
  interests?: string[]
  avoid_places?: string[]
  pace?: string
  budget_total?: number | null
  transport?: string
  confirmed_job_id?: number
}
type Message = { id?: number; role: string; content: string; payload?: MessagePayload }
type ServerEvent = { event_id: number | null; session_id: string; turn_id: string | null; type: string; payload: Record<string, unknown> }
type AgentStatus = { mode: 'llm' | 'local'; state: 'disabled' | 'configured' | 'connected' | 'degraded'; model: string | null; label: string }
type PlanDraft = { destination_city_id: number | null; destination: string; days: number; traveler_count: number; budget_total: number | null; interests: string; avoid_places: string; pace: 'relaxed' | 'balanced' | 'packed'; transport: 'public_transport' | 'taxi' | 'walking' | 'driving' }
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
let eventSource: EventSource | null = null

const briefLocked = computed(() => !sessionId.value || archivedView.value || sending.value)

const activeSessionKey = 'travel-planner-active-session'
const eventCursorKey = (id: number) => `travel-planner-event-${id}`

function blankRequirement(): PlanDraft {
  return { destination_city_id: null, destination: '', days: 3, traveler_count: 1, budget_total: null, interests: '', avoid_places: '', pace: 'balanced', transport: 'public_transport' }
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
}

async function switchSessionView() {
  archivedView.value = !archivedView.value
  sessions.value = await api<ChatSession[]>(`/sessions?archived=${archivedView.value}`)
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
  try {
    await updateSession(session, { archived: !session.archived_at })
    sessions.value = sessions.value.filter((item) => item.id !== session.id)
    if (sessionId.value === session.id) await newSession()
  } catch (error) { window.alert(error instanceof Error ? error.message : '操作失败') }
}

async function deleteSession(session: ChatSession) {
  if (!window.confirm(`确定删除“${session.title}”吗？它会从你的会话列表中移除，如需恢复请联系管理员。`)) return
  try {
    await api(`/sessions/${session.id}`, { method: 'DELETE' })
    sessions.value = sessions.value.filter((item) => item.id !== session.id)
    localStorage.removeItem(eventCursorKey(session.id))
    if (sessionId.value === session.id) await newSession()
  } catch (error) { window.alert(error instanceof Error ? error.message : '删除失败') }
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
    const id = await ensureSession(); const job = await api<{ job_id: number; session_title: string }>(`/sessions/${id}/messages`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify({ content }) }); jobId.value = job.job_id
    const activeSession = sessions.value.find((session) => session.id === id)
    if (activeSession) activeSession.title = job.session_title
    await connectEvents(id)
  } catch (error) { messages.value.push({ role: 'assistant', content: error instanceof Error ? error.message : '请先登录后开始规划。' }); sending.value = false; stage.value = '需要登录' }
}
function applyRequirement(payload: MessagePayload) {
  const matchedCity = cities.value.find((city) => city.id === payload.destination_city_id || city.name === payload.destination)
  requirementDraft.value = {
    destination_city_id: payload.destination_city_id || matchedCity?.id || null,
    destination: payload.destination || matchedCity?.name || '',
    days: payload.days || 3,
    traveler_count: payload.traveler_count || 1,
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
  sending.value = true
  stage.value = '正在提交已确认的需求'
  try {
    const job = await api<{ job_id: number }>(`/sessions/${sessionId.value}/plan-confirm`, {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ confirmed: true, patch: {
        destination_city_id: requirementDraft.value.destination_city_id,
        days: Number(requirementDraft.value.days),
        traveler_count: Number(requirementDraft.value.traveler_count),
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
      @select="loadSession"
      @create="newSession"
      @switch-view="switchSessionView"
      @rename="renameSession"
      @pin="togglePin"
      @archive="toggleArchive"
      @delete="deleteSession"
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
                  <div><dt>天数</dt><dd>{{ message.payload.days }} 天</dd></div>
                  <div><dt>人数</dt><dd>{{ message.payload.traveler_count }} 人</dd></div>
                  <div><dt>偏好</dt><dd>{{ message.payload.interests?.join('、') }}</dd></div>
                </dl>
                <small>可在右侧清单修改条件；当前预算只计算门票。</small>
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
          <div class="brief-pair"><label>天数<input v-model.number="requirementDraft.days" type="number" min="2" max="5" :disabled="briefLocked" /></label><label>人数<input v-model.number="requirementDraft.traveler_count" type="number" min="1" max="20" :disabled="briefLocked" /></label></div>
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
  </div>
</template>

<style scoped>
.planner-frame { max-width: 1440px; margin: auto; min-height: calc(100vh - 64px); display: grid; grid-template-columns: 220px minmax(0, 1fr) 250px; transition: grid-template-columns .18s ease; }
.planner-frame.rail-collapsed { grid-template-columns: 56px minmax(0, 1fr) 250px; }
.planner-frame > .planner-shell { display: contents; }
.confirm-card { margin-top: 10px; border: 1px solid var(--border); background: var(--surface); padding: 16px; }
.confirm-card dl { margin: 0 0 12px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 18px; }
.confirm-card dl div { min-width: 0; }
.confirm-card dt { color: var(--secondary); font-size: 11px; }
.confirm-card dd { margin: 4px 0 0; font-size: 13px; overflow-wrap: anywhere; }
.confirm-card small { color: var(--secondary); line-height: 1.6; }
.confirm-actions { display: flex; gap: 8px; margin-top: 14px; }
.brief-form { display: grid; gap: 13px; padding-top: 18px; }
.brief-form label { display: grid; gap: 6px; color: var(--secondary); font-size: 11px; }
.brief-form input, .brief-form select { width: 100%; min-width: 0; padding: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--text); outline: 0; }
.brief-form input:focus, .brief-form select:focus { border-color: var(--primary); }
.brief-form input:disabled, .brief-form select:disabled { background: transparent; color: var(--text); opacity: 1; }
.brief-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.brief-confirm { width: 100%; margin-top: 3px; }
.stop-action { color: var(--danger); }
.live-indicator.disabled, .live-indicator.degraded { color: var(--secondary); }
@media (max-width: 1000px) { .planner-frame, .planner-frame.rail-collapsed { display: grid; grid-template-columns: minmax(0, 1fr) 220px; } }
@media (max-width: 720px) { .planner-frame, .planner-frame.rail-collapsed { display: block; } }
.live-indicator.disabled i, .live-indicator.degraded i { background: var(--secondary); }
.live-indicator.configured { color: #9a6b13; }
.live-indicator.configured i { background: #c58b1b; }
@media (max-width: 720px) { .confirm-card dl { grid-template-columns: 1fr; } .confirm-actions { align-items: stretch; flex-direction: column; } }
</style>
