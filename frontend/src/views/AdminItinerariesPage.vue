<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Database, RotateCcw, Search, Trash2 } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api } from '../api'

type ItineraryState = 'all' | 'active' | 'deleted'
type AdminItinerary = {
  id: number
  user_id: number | null
  username: string
  title: string
  city_name: string
  days: number
  status: string
  created_at: string
  deleted_at: string | null
  share_count: number
  feedback_count: number
  revision_count: number
  association_count: number
  can_hard_delete: boolean
}

const itineraries = ref<AdminItinerary[]>([])
const state = ref<ItineraryState>('all')
const search = ref('')
const page = ref(1)
const pageSize = 10
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

function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-'
}

async function loadItineraries(targetPage = page.value) {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ state: state.value, page: String(targetPage), page_size: String(pageSize) })
    if (search.value.trim()) params.set('search', search.value.trim())
    const result = await api<{ items: AdminItinerary[]; total: number; page: number; page_size: number }>(`/admin/itineraries?${params.toString()}`)
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize))
    if (targetPage > lastPage) return loadItineraries(lastPage)
    itineraries.value = result.items
    total.value = result.total
    page.value = result.page
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '行程数据加载失败'
  } finally {
    loading.value = false
  }
}

function setState(value: ItineraryState) {
  state.value = value
  void loadItineraries(1)
}

function goToPage(value: number) {
  if (value >= 1 && value <= pageCount.value && value !== page.value) void loadItineraries(value)
}

async function restoreItinerary(itinerary: AdminItinerary) {
  if (!window.confirm(`确定恢复“${itinerary.title}”吗？恢复后会重新出现在用户的行程列表中。`)) return
  busyId.value = itinerary.id
  try {
    await api(`/admin/itineraries/${itinerary.id}/restore`, { method: 'POST', body: '{}' })
    await loadItineraries(page.value)
  } catch (exception) {
    window.alert(exception instanceof Error ? exception.message : '恢复失败')
  } finally {
    busyId.value = null
  }
}

async function hardDeleteItinerary(itinerary: AdminItinerary) {
  if (!itinerary.can_hard_delete || !window.confirm(`彻底删除“${itinerary.title}”吗？该操作无法恢复。`)) return
  busyId.value = itinerary.id
  try {
    await api(`/admin/itineraries/${itinerary.id}`, { method: 'DELETE' })
    await loadItineraries(page.value)
  } catch (exception) {
    window.alert(exception instanceof Error ? exception.message : '彻底删除失败')
  } finally {
    busyId.value = null
  }
}

watch(search, () => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { void loadItineraries(1) }, 300)
})
onBeforeUnmount(() => { if (searchTimer) window.clearTimeout(searchTimer) })
onMounted(() => { void loadItineraries() })
</script>

<template>
  <div class="page-container">
    <AdminModuleHeader eyebrow="ITINERARY DATA" title="行程回收站" description="查看用户行程、恢复误删数据，并保护仍有关联记录的行程。" />
    <div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2></div>
    <template v-else>
      <div class="admin-toolbar">
        <div class="admin-toolbar-group">
          <button v-for="item in ([['all', '全部'], ['active', '正常'], ['deleted', '已删除']] as const)" :key="item[0]" :class="['admin-filter-button', { active: state === item[0] }]" @click="setState(item[0])">{{ item[1] }}</button>
        </div>
        <input v-model="search" class="admin-search" aria-label="搜索行程" placeholder="搜索行程、城市或所属用户" />
      </div>
      <div class="admin-table-wrap">
        <table class="admin-data-table">
          <thead><tr><th>行程</th><th>所属用户</th><th>关联数据</th><th>创建时间</th><th>状态</th><th aria-label="操作"></th></tr></thead>
          <tbody>
            <tr v-for="itinerary in itineraries" :key="itinerary.id">
              <td><strong>{{ itinerary.title }}</strong><small>{{ itinerary.city_name }} · {{ itinerary.days }} 天 · ID {{ itinerary.id }}</small></td>
              <td>{{ itinerary.username }}<small>用户 ID {{ itinerary.user_id ?? '-' }}</small></td>
              <td>{{ itinerary.association_count }} 条<small>分享 {{ itinerary.share_count }} · 反馈 {{ itinerary.feedback_count }} · 版本 {{ itinerary.revision_count }}</small></td>
              <td>{{ formatDate(itinerary.created_at) }}</td>
              <td><span :class="['admin-status', itinerary.deleted_at ? 'danger' : '']">{{ itinerary.deleted_at ? '已删除' : itinerary.status === 'saved' ? '已保存' : '草稿' }}</span><small v-if="itinerary.deleted_at">{{ formatDate(itinerary.deleted_at) }}</small></td>
              <td><div class="admin-row-actions"><button v-if="itinerary.deleted_at" class="admin-table-action" :disabled="busyId === itinerary.id" title="恢复行程" @click="restoreItinerary(itinerary)"><RotateCcw :size="16" /></button><button v-if="itinerary.deleted_at" class="admin-table-action danger-action" :disabled="busyId === itinerary.id || !itinerary.can_hard_delete" :title="itinerary.can_hard_delete ? '彻底删除' : '仍有关联数据，不能彻底删除'" @click="hardDeleteItinerary(itinerary)"><Trash2 :size="16" /></button></div></td>
            </tr>
          </tbody>
        </table>
        <div v-if="loading" class="admin-page-empty"><p>正在加载行程...</p></div>
        <div v-else-if="!itineraries.length" class="admin-page-empty"><Search :size="20" /><p>没有匹配的行程</p></div>
      </div>
      <div v-if="total" class="admin-pagination"><span>共 {{ total }} 份行程，第 {{ page }} / {{ pageCount }} 页</span><div><button class="admin-page-button" :disabled="page === 1 || loading" title="上一页" @click="goToPage(page - 1)"><ChevronLeft :size="16" /></button><button v-for="number in pageNumbers" :key="number" :class="['admin-page-button', { active: number === page }]" :disabled="loading" @click="goToPage(number)">{{ number }}</button><button class="admin-page-button" :disabled="page === pageCount || loading" title="下一页" @click="goToPage(page + 1)"><ChevronRight :size="16" /></button></div></div>
    </template>
  </div>
</template>

<style scoped>
.admin-row-actions { display: flex; justify-content: flex-end; gap: 4px; }
</style>
