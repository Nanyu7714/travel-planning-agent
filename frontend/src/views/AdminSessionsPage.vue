<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Database, RotateCcw, Search } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api } from '../api'

type SessionState = 'all' | 'active' | 'archived' | 'deleted'
type AdminSession = { id: number; user_id: number | null; username: string; email: string; title: string; state: Exclude<SessionState, 'all'>; message_count: number; job_count: number; created_at: string; updated_at: string | null; deleted_at: string | null }
const sessions = ref<AdminSession[]>([])
const state = ref<SessionState>('all')
const search = ref('')
const page = ref(1)
const pageSize = 10
const total = ref(0)
const loading = ref(false)
const busyId = ref<number | null>(null)
const error = ref('')
let searchTimer: ReturnType<typeof window.setTimeout> | null = null
const stateLabel = { active: '当前', archived: '已归档', deleted: '用户已删除' }
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const pageNumbers = computed(() => {
  const start = Math.max(1, Math.min(page.value - 2, pageCount.value - 4))
  const end = Math.min(pageCount.value, start + 4)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})
function formatDate(value: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-' }
async function loadSessions(targetPage = page.value) {
  loading.value = true
  try {
    const params = new URLSearchParams({ state: state.value, page: String(targetPage), page_size: String(pageSize) })
    if (search.value.trim()) params.set('search', search.value.trim())
    const result = await api<{ items: AdminSession[]; total: number; page: number; page_size: number }>(`/admin/sessions?${params.toString()}`)
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize))
    if (targetPage > lastPage) return loadSessions(lastPage)
    sessions.value = result.items; total.value = result.total; page.value = result.page
  } catch (exception) { error.value = exception instanceof Error ? exception.message : '加载失败' }
  finally { loading.value = false }
}
function setState(value: SessionState) { state.value = value; void loadSessions(1) }
function goToPage(value: number) { if (value >= 1 && value <= pageCount.value && value !== page.value) void loadSessions(value) }
async function restoreSession(session: AdminSession) {
  if (!window.confirm(`确定恢复“${session.title}”吗？恢复后会重新出现在用户的会话列表中。`)) return
  busyId.value = session.id
  try { await api(`/admin/sessions/${session.id}/restore`, { method: 'POST', body: '{}' }); await loadSessions(page.value) }
  catch (exception) { window.alert(exception instanceof Error ? exception.message : '恢复失败') }
  finally { busyId.value = null }
}
watch(search, () => { if (searchTimer) window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { void loadSessions(1) }, 300) })
onBeforeUnmount(() => { if (searchTimer) window.clearTimeout(searchTimer) })
onMounted(() => { void loadSessions() })
</script>

<template><div class="page-container"><AdminModuleHeader eyebrow="CONVERSATION DATA" title="会话管理" description="查看当前、归档和用户已删除的会话记录，并恢复误删会话。" /><div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2></div><template v-else><div class="admin-toolbar"><div class="admin-toolbar-group"><button v-for="item in ([['all', '全部'], ['active', '当前'], ['archived', '已归档'], ['deleted', '用户已删除']] as const)" :key="item[0]" :class="['admin-filter-button', { active: state === item[0] }]" @click="setState(item[0])">{{ item[1] }}</button></div><input v-model="search" class="admin-search" aria-label="搜索会话" placeholder="搜索会话或所属用户" /></div><div class="admin-table-wrap"><table class="admin-data-table"><thead><tr><th>会话</th><th>所属用户</th><th>数据量</th><th>更新时间</th><th>状态</th><th aria-label="操作"></th></tr></thead><tbody><tr v-for="session in sessions" :key="session.id"><td><strong>{{ session.title }}</strong><small>ID {{ session.id }}</small></td><td>{{ session.username }}<small>{{ session.email }}</small></td><td>{{ session.message_count }} 条消息<small>{{ session.job_count }} 个任务</small></td><td>{{ formatDate(session.updated_at || session.created_at) }}</td><td><span :class="['admin-status', session.state === 'deleted' ? 'danger' : session.state === 'archived' ? 'muted' : '']">{{ stateLabel[session.state] }}</span><small v-if="session.deleted_at">{{ formatDate(session.deleted_at) }}</small></td><td><button v-if="session.state === 'deleted'" class="admin-table-action" :disabled="busyId === session.id" title="恢复会话" @click="restoreSession(session)"><RotateCcw :size="16" /></button></td></tr></tbody></table><div v-if="loading" class="admin-page-empty"><p>正在加载会话...</p></div><div v-else-if="!sessions.length" class="admin-page-empty"><Search :size="20" /><p>没有匹配的会话</p></div></div><div v-if="total" class="admin-pagination"><span>共 {{ total }} 个会话，第 {{ page }} / {{ pageCount }} 页</span><div><button class="admin-page-button" :disabled="page === 1 || loading" title="上一页" @click="goToPage(page - 1)"><ChevronLeft :size="16" /></button><button v-for="number in pageNumbers" :key="number" :class="['admin-page-button', { active: number === page }]" :disabled="loading" @click="goToPage(number)">{{ number }}</button><button class="admin-page-button" :disabled="page === pageCount || loading" title="下一页" @click="goToPage(page + 1)"><ChevronRight :size="16" /></button></div></div></template></div></template>
