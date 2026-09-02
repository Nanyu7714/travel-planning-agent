<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronLeft, ChevronRight, Database, ScrollText } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api } from '../api'

type AuditLog = { id: number; actor_username: string; action: string; target_type: string; target_id: number | null; summary: string; created_at: string }
const items = ref<AuditLog[]>([]); const total = ref(0); const page = ref(1); const pageSize = 20; const error = ref('')
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
async function load(targetPage = page.value) { try { const result = await api<{ items: AuditLog[]; total: number; page: number }>(`/admin/audit-logs?page=${targetPage}&page_size=${pageSize}`); items.value = result.items; total.value = result.total; page.value = result.page } catch (exception) { error.value = exception instanceof Error ? exception.message : '加载失败' } }
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) }
onMounted(() => { void load() })
</script>

<template><div class="page-container"><AdminModuleHeader eyebrow="ADMIN AUDIT" title="操作审计" description="记录后台内容维护、删除和批量导入操作。" /><div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2></div><template v-else><div class="admin-table-wrap"><table class="admin-data-table"><thead><tr><th>时间</th><th>管理员</th><th>操作</th><th>对象</th><th>摘要</th></tr></thead><tbody><tr v-for="item in items" :key="item.id"><td>{{ formatDate(item.created_at) }}</td><td>{{ item.actor_username }}</td><td>{{ item.action }}</td><td>{{ item.target_type }}<small v-if="item.target_id">ID {{ item.target_id }}</small></td><td>{{ item.summary }}</td></tr></tbody></table><div v-if="!items.length" class="admin-page-empty"><ScrollText :size="20" /><p>暂时没有操作记录</p></div></div><div v-if="total" class="admin-pagination"><span>共 {{ total }} 条记录，第 {{ page }} / {{ pageCount }} 页</span><div><button class="admin-page-button" :disabled="page === 1" title="上一页" @click="load(page - 1)"><ChevronLeft :size="16" /></button><button class="admin-page-button" :disabled="page === pageCount" title="下一页" @click="load(page + 1)"><ChevronRight :size="16" /></button></div></div></template></div></template>
