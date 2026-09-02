<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Database, Search, UserCheck, UserX } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api } from '../api'

type AdminUser = { id: number; public_id: string | null; username: string; email: string; role: string; is_active: boolean; created_at: string; session_count: number; deleted_session_count: number }
const users = ref<AdminUser[]>([])
const search = ref('')
const status = ref<'all' | 'active' | 'disabled'>('all')
const page = ref(1)
const pageSize = 20
const total = ref(0)
const loading = ref(false)
const busyId = ref<number | null>(null)
const error = ref('')
let searchTimer: ReturnType<typeof window.setTimeout> | null = null
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const pageNumbers = computed(() => {
  const start = Math.max(1, Math.min(page.value - 2, pageCount.value - 4))
  const end = Math.min(pageCount.value, start + 4)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
async function loadUsers(targetPage = page.value) {
  loading.value = true
  try {
    const params = new URLSearchParams({ page: String(targetPage), page_size: String(pageSize), status: status.value })
    if (search.value.trim()) params.set('search', search.value.trim())
    const result = await api<{ items: AdminUser[]; total: number; page: number; page_size: number }>(`/admin/users?${params.toString()}`)
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize))
    if (targetPage > lastPage) return loadUsers(lastPage)
    users.value = result.items
    total.value = result.total
    page.value = result.page
  } catch (exception) { error.value = exception instanceof Error ? exception.message : '加载失败' }
  finally { loading.value = false }
}
function setStatus(value: 'all' | 'active' | 'disabled') { status.value = value; void loadUsers(1) }
function goToPage(value: number) { if (value >= 1 && value <= pageCount.value && value !== page.value) void loadUsers(value) }
async function toggleUser(user: AdminUser) {
  const action = user.is_active ? '停用' : '启用'
  if (!window.confirm(`确定${action}账号“${user.username}”吗？`)) return
  busyId.value = user.id
  try {
    const updated = await api<AdminUser>(`/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !user.is_active }) })
    users.value[users.value.findIndex((item) => item.id === user.id)] = updated
    await loadUsers(page.value)
  } catch (exception) { window.alert(exception instanceof Error ? exception.message : `${action}失败`) }
  finally { busyId.value = null }
}
watch(search, () => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { void loadUsers(1) }, 300)
})
onBeforeUnmount(() => { if (searchTimer) window.clearTimeout(searchTimer) })
onMounted(() => { void loadUsers() })
</script>

<template><div class="page-container"><AdminModuleHeader eyebrow="USER ACCOUNTS" title="用户管理" description="查看注册账号、会话数量和账号启用状态。" /><div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2></div><template v-else><div class="admin-toolbar"><div class="admin-toolbar-group"><button v-for="item in ([['all', '全部'], ['active', '正常'], ['disabled', '已停用']] as const)" :key="item[0]" :class="['admin-filter-button', { active: status === item[0] }]" @click="setStatus(item[0])">{{ item[1] }}</button></div><input v-model="search" class="admin-search" aria-label="搜索用户" placeholder="搜索用户名、邮箱或用户 ID" /></div><div class="admin-table-wrap"><table class="admin-data-table"><thead><tr><th>用户</th><th>角色</th><th>会话</th><th>注册时间</th><th>状态</th><th aria-label="操作"></th></tr></thead><tbody><tr v-for="user in users" :key="user.id"><td><strong>{{ user.username }}</strong><small>{{ user.email }} · ID {{ user.public_id || '已释放' }}</small></td><td>{{ user.role === 'admin' ? '管理员' : '普通用户' }}</td><td>{{ user.session_count }} 个<small v-if="user.deleted_session_count">用户已删除 {{ user.deleted_session_count }} 个</small></td><td>{{ formatDate(user.created_at) }}</td><td><span :class="['admin-status', user.is_active ? '' : 'danger']">{{ user.is_active ? '正常' : '已停用' }}</span></td><td><button class="admin-table-action" :disabled="busyId === user.id" :title="user.is_active ? '停用账号' : '启用账号'" @click="toggleUser(user)"><UserX v-if="user.is_active" :size="16" /><UserCheck v-else :size="16" /></button></td></tr></tbody></table><div v-if="loading" class="admin-page-empty"><p>正在加载用户...</p></div><div v-else-if="!users.length" class="admin-page-empty"><Search :size="20" /><p>没有匹配的用户</p></div></div><div v-if="total" class="admin-pagination"><span>共 {{ total }} 个用户，第 {{ page }} / {{ pageCount }} 页</span><div><button class="admin-page-button" :disabled="page === 1 || loading" title="上一页" @click="goToPage(page - 1)"><ChevronLeft :size="16" /></button><button v-for="number in pageNumbers" :key="number" :class="['admin-page-button', { active: number === page }]" :disabled="loading" @click="goToPage(number)">{{ number }}</button><button class="admin-page-button" :disabled="page === pageCount || loading" title="下一页" @click="goToPage(page + 1)"><ChevronRight :size="16" /></button></div></div></template></div></template>
