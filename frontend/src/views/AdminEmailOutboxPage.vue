<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ChevronLeft, ChevronRight, Database, MailCheck, Search } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api } from '../api'

type DeliveryStatus = 'all' | 'sent' | 'failed' | 'simulated'
type EmailDelivery = {
  id: number
  user_id: number | null
  username: string | null
  purpose: string
  recipient_masked: string
  subject: string
  status: Exclude<DeliveryStatus, 'all'>
  attempt_count: number
  retry_count: number
  last_error_code: string | null
  sent_at: string | null
  created_at: string
  updated_at: string
}

const deliveries = ref<EmailDelivery[]>([])
const status = ref<DeliveryStatus>('all')
const page = ref(1)
const pageSize = 20
const total = ref(0)
const loading = ref(false)
const error = ref('')
const statusLabel = { sent: '已投递', failed: '失败', simulated: '本地模拟' }
const purposeLabel: Record<string, string> = { verify_email: '验证邮箱', reset_password: '重设密码', change_email: '确认新邮箱' }
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const pageNumbers = computed(() => {
  const start = Math.max(1, Math.min(page.value - 2, pageCount.value - 4))
  const end = Math.min(pageCount.value, start + 4)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})

function formatDate(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '-'
}

async function loadDeliveries(targetPage = page.value) {
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ status: status.value, page: String(targetPage), page_size: String(pageSize) })
    const result = await api<{ items: EmailDelivery[]; total: number; page: number; page_size: number }>(`/admin/email-outbox?${params.toString()}`)
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize))
    if (targetPage > lastPage) return loadDeliveries(lastPage)
    deliveries.value = result.items
    total.value = result.total
    page.value = result.page
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '邮件投递记录加载失败'
  } finally {
    loading.value = false
  }
}

function setStatus(value: DeliveryStatus) {
  status.value = value
  void loadDeliveries(1)
}

function goToPage(value: number) {
  if (value >= 1 && value <= pageCount.value && value !== page.value) void loadDeliveries(value)
}

onMounted(() => { void loadDeliveries() })
</script>

<template>
  <div class="page-container">
    <AdminModuleHeader eyebrow="DELIVERY LOG" title="邮件投递" description="查看认证邮件的投递结果。收件人、验证码和一次性链接不会在这里显示。" />
    <div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2></div>
    <template v-else>
      <div class="admin-toolbar">
        <div class="admin-toolbar-group">
          <button v-for="item in ([['all', '全部'], ['sent', '已投递'], ['failed', '失败'], ['simulated', '本地模拟']] as const)" :key="item[0]" :class="['admin-filter-button', { active: status === item[0] }]" @click="setStatus(item[0])">{{ item[1] }}</button>
        </div>
        <span class="admin-result-count">仅保留脱敏投递元数据</span>
      </div>

      <div class="admin-table-wrap">
        <table class="admin-data-table email-outbox-table">
          <thead><tr><th>邮件类型</th><th>所属用户</th><th>收件人</th><th>投递状态</th><th>尝试</th><th>发送时间</th><th>失败类别</th></tr></thead>
          <tbody>
            <tr v-for="delivery in deliveries" :key="delivery.id">
              <td><strong>{{ purposeLabel[delivery.purpose] || delivery.purpose }}</strong><small>{{ delivery.subject }}</small></td>
              <td>{{ delivery.username || '已删除用户' }}<small v-if="delivery.user_id">用户 ID {{ delivery.user_id }}</small></td>
              <td>{{ delivery.recipient_masked }}</td>
              <td><span :class="['admin-status', delivery.status === 'failed' ? 'danger' : delivery.status === 'simulated' ? 'muted' : '']"><MailCheck :size="14" />{{ statusLabel[delivery.status] }}</span></td>
              <td>{{ delivery.attempt_count }} 次<small>重试 {{ delivery.retry_count }} 次</small></td>
              <td>{{ formatDate(delivery.sent_at || delivery.created_at) }}</td>
              <td>{{ delivery.last_error_code || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="loading" class="admin-page-empty"><p>正在加载投递记录...</p></div>
        <div v-else-if="!deliveries.length" class="admin-page-empty"><Search :size="20" /><p>没有匹配的投递记录</p></div>
      </div>

      <div v-if="total" class="admin-pagination">
        <span>共 {{ total }} 条记录，第 {{ page }} / {{ pageCount }} 页</span>
        <div>
          <button class="admin-page-button" :disabled="page === 1 || loading" title="上一页" @click="goToPage(page - 1)"><ChevronLeft :size="16" /></button>
          <button v-for="number in pageNumbers" :key="number" :class="['admin-page-button', { active: number === page }]" :disabled="loading" @click="goToPage(number)">{{ number }}</button>
          <button class="admin-page-button" :disabled="page === pageCount || loading" title="下一页" @click="goToPage(page + 1)"><ChevronRight :size="16" /></button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.email-outbox-table { min-width: 980px; }
.email-outbox-table td:nth-child(3), .email-outbox-table td:nth-child(7) { overflow-wrap: anywhere; }
</style>
