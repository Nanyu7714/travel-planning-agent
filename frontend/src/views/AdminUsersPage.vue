<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Database, Search, UserCheck, UserX } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api } from '../api'

type AdminUser = { id: number; public_id: string | null; username: string; email: string; role: string; is_active: boolean; created_at: string; session_count: number; deleted_session_count: number }
const users = ref<AdminUser[]>([])
const search = ref('')
const status = ref<'all' | 'active' | 'disabled'>('all')
const busyId = ref<number | null>(null)
const error = ref('')
const filteredUsers = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return users.value.filter((user) => (status.value === 'all' || (status.value === 'active') === user.is_active) && (!keyword || `${user.username} ${user.email} ${user.public_id || ''}`.toLowerCase().includes(keyword)))
})
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
async function toggleUser(user: AdminUser) {
  const action = user.is_active ? '停用' : '启用'
  if (!window.confirm(`确定${action}账号“${user.username}”吗？`)) return
  busyId.value = user.id
  try {
    const updated = await api<AdminUser>(`/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !user.is_active }) })
    users.value[users.value.findIndex((item) => item.id === user.id)] = updated
  } catch (exception) { window.alert(exception instanceof Error ? exception.message : `${action}失败`) }
  finally { busyId.value = null }
}
onMounted(async () => { try { users.value = await api<AdminUser[]>('/admin/users') } catch (exception) { error.value = exception instanceof Error ? exception.message : '加载失败' } })
</script>

<template><div class="page-container"><AdminModuleHeader eyebrow="USER ACCOUNTS" title="用户管理" description="查看注册账号、会话数量和账号启用状态。" /><div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2></div><template v-else><div class="admin-toolbar"><div class="admin-toolbar-group"><button v-for="item in ([['all', '全部'], ['active', '正常'], ['disabled', '已停用']] as const)" :key="item[0]" :class="['admin-filter-button', { active: status === item[0] }]" @click="status = item[0]">{{ item[1] }}</button></div><input v-model="search" class="admin-search" aria-label="搜索用户" placeholder="搜索用户名、邮箱或用户 ID" /></div><div class="admin-table-wrap"><table class="admin-data-table"><thead><tr><th>用户</th><th>角色</th><th>会话</th><th>注册时间</th><th>状态</th><th aria-label="操作"></th></tr></thead><tbody><tr v-for="user in filteredUsers" :key="user.id"><td><strong>{{ user.username }}</strong><small>{{ user.email }} · ID {{ user.public_id || '已释放' }}</small></td><td>{{ user.role === 'admin' ? '管理员' : '普通用户' }}</td><td>{{ user.session_count }} 个<small v-if="user.deleted_session_count">用户已删除 {{ user.deleted_session_count }} 个</small></td><td>{{ formatDate(user.created_at) }}</td><td><span :class="['admin-status', user.is_active ? '' : 'danger']">{{ user.is_active ? '正常' : '已停用' }}</span></td><td><button class="admin-table-action" :disabled="busyId === user.id" :title="user.is_active ? '停用账号' : '启用账号'" @click="toggleUser(user)"><UserX v-if="user.is_active" :size="16" /><UserCheck v-else :size="16" /></button></td></tr></tbody></table><div v-if="!filteredUsers.length" class="admin-page-empty"><Search :size="20" /><p>没有匹配的用户</p></div></div></template></div></template>
