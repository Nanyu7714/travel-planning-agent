<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Database, RotateCcw, Search } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api } from '../api'

type SessionState = 'all' | 'active' | 'archived' | 'deleted'
type AdminSession = { id: number; user_id: number | null; username: string; email: string; title: string; state: Exclude<SessionState, 'all'>; message_count: number; job_count: number; created_at: string; updated_at: string | null; deleted_at: string | null }
const sessions = ref<AdminSession[]>([])
const state = ref<SessionState>('all')
const search = ref('')
const busyId = ref<number | null>(null)
const error = ref('')
const stateLabel = { active: '当前', archived: '已归档', deleted: '用户已删除' }
const filteredSessions = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return keyword ? sessions.value.filter((session) => `${session.title} ${session.username} ${session.email}`.toLowerCase().includes(keyword)) : sessions.value
})
function formatDate(value: string | null) { return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-' }
async function loadSessions() { sessions.value = await api<AdminSession[]>(`/admin/sessions?state=${state.value}`) }
async function setState(value: SessionState) { state.value = value; await loadSessions() }
async function restoreSession(session: AdminSession) {
  if (!window.confirm(`确定恢复“${session.title}”吗？恢复后会重新出现在用户的会话列表中。`)) return
  busyId.value = session.id
  try { await api(`/admin/sessions/${session.id}/restore`, { method: 'POST', body: '{}' }); await loadSessions() }
  catch (exception) { window.alert(exception instanceof Error ? exception.message : '恢复失败') }
  finally { busyId.value = null }
}
onMounted(async () => { try { await loadSessions() } catch (exception) { error.value = exception instanceof Error ? exception.message : '加载失败' } })
</script>

<template><div class="page-container"><AdminModuleHeader eyebrow="CONVERSATION DATA" title="会话管理" description="查看当前、归档和用户已删除的会话记录，并恢复误删会话。" /><div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2></div><template v-else><div class="admin-toolbar"><div class="admin-toolbar-group"><button v-for="item in ([['all', '全部'], ['active', '当前'], ['archived', '已归档'], ['deleted', '用户已删除']] as const)" :key="item[0]" :class="['admin-filter-button', { active: state === item[0] }]" @click="setState(item[0])">{{ item[1] }}</button></div><input v-model="search" class="admin-search" aria-label="搜索会话" placeholder="搜索会话或所属用户" /></div><div class="admin-table-wrap"><table class="admin-data-table"><thead><tr><th>会话</th><th>所属用户</th><th>数据量</th><th>更新时间</th><th>状态</th><th aria-label="操作"></th></tr></thead><tbody><tr v-for="session in filteredSessions" :key="session.id"><td><strong>{{ session.title }}</strong><small>ID {{ session.id }}</small></td><td>{{ session.username }}<small>{{ session.email }}</small></td><td>{{ session.message_count }} 条消息<small>{{ session.job_count }} 个任务</small></td><td>{{ formatDate(session.updated_at || session.created_at) }}</td><td><span :class="['admin-status', session.state === 'deleted' ? 'danger' : session.state === 'archived' ? 'muted' : '']">{{ stateLabel[session.state] }}</span><small v-if="session.deleted_at">{{ formatDate(session.deleted_at) }}</small></td><td><button v-if="session.state === 'deleted'" class="admin-table-action" :disabled="busyId === session.id" title="恢复会话" @click="restoreSession(session)"><RotateCcw :size="16" /></button></td></tr></tbody></table><div v-if="!filteredSessions.length" class="admin-page-empty"><Search :size="20" /><p>没有匹配的会话</p></div></div></template></div></template>
