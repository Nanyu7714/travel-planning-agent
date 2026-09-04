<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Link2, ShieldOff, Trash2 } from 'lucide-vue-next'
import { getMyShares, revokeShare, type ShareHistoryItem } from '../api'

const shares = ref<ShareHistoryItem[]>([])
const loading = ref(true)
const error = ref('')
const revokingId = ref<number | null>(null)

const statusLabel = (status: ShareHistoryItem['status']) => ({ active: '有效', expired: '已失效', revoked: '已撤销' })[status]
const formatDate = (value: string | null) => value ? new Date(value).toLocaleString() : '—'

async function load() {
  try { shares.value = await getMyShares() } catch (cause) { error.value = cause instanceof Error ? cause.message : '分享记录加载失败' } finally { loading.value = false }
}

async function revoke(share: ShareHistoryItem) {
  if (share.status !== 'active' || !window.confirm(`撤销“${share.itinerary_title}”的公开分享？撤销后原链接将立即失效。`)) return
  revokingId.value = share.id
  try {
    await revokeShare(share.itinerary_id, share.id)
    shares.value = shares.value.map((item) => item.id === share.id ? { ...item, status: 'revoked', revoked_at: new Date().toISOString() } : item)
  } catch (cause) { error.value = cause instanceof Error ? cause.message : '撤销分享失败' } finally { revokingId.value = null }
}

onMounted(load)
</script>

<template>
  <div class="page-container shares-page">
    <div class="page-title-row">
      <div><span class="eyebrow">SHARE MANAGEMENT</span><h1>我的分享</h1><p>查看已创建的行程分享，并管理仍有效的公开访问。</p></div>
      <RouterLink class="secondary-button" to="/itineraries"><Link2 :size="16" />我的行程</RouterLink>
    </div>

    <div v-if="loading" class="loading-state">正在加载分享记录...</div>
    <div v-else-if="error" class="empty-state"><ShieldOff :size="28" /><h2>{{ error }}</h2><button class="secondary-button" @click="load">重新加载</button></div>
    <div v-else-if="!shares.length" class="empty-state"><Link2 :size="28" /><h2>还没有分享记录</h2><RouterLink class="primary-button" to="/itineraries">查看我的行程</RouterLink></div>
    <section v-else class="share-list" aria-label="历史分享链接">
      <article v-for="share in shares" :key="share.id" class="share-row">
        <div class="share-main"><span class="share-city">{{ share.city_name }}</span><RouterLink :to="`/itineraries/${share.itinerary_id}`">{{ share.itinerary_title }}</RouterLink><small>创建于 {{ formatDate(share.created_at) }}</small></div>
        <div class="share-expiry"><span>{{ share.status === 'active' ? '有效至' : share.status === 'revoked' ? '撤销于' : '失效于' }}</span><strong>{{ formatDate(share.status === 'revoked' ? share.revoked_at : share.expires_at) }}</strong></div>
        <span :class="['share-status', share.status]">{{ statusLabel(share.status) }}</span>
        <button v-if="share.status === 'active'" class="icon-button danger-icon" :disabled="revokingId === share.id" title="撤销分享" aria-label="撤销分享" @click="revoke(share)"><Trash2 :size="17" /></button>
      </article>
    </section>
    <p v-if="shares.length" class="security-note">完整分享链接只在创建时显示一次；历史记录不保存可访问令牌。</p>
  </div>
</template>

<style scoped>
.shares-page { max-width: 1000px; }
.share-list { margin-top: 44px; border-top: 1px solid var(--color-border-soft); }
.share-row { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(180px, .9fr) 72px 42px; align-items: center; gap: 20px; min-height: 106px; border-bottom: 1px solid var(--color-border-soft); }
.share-main { display: grid; gap: 6px; min-width: 0; }
.share-city { color: var(--color-primary); font-size: 12px; font-weight: 600; }
.share-main a { overflow: hidden; color: var(--color-ink); font-size: 16px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.share-main small, .share-expiry span, .security-note { color: var(--color-muted); font-size: 13px; }
.share-expiry { display: grid; gap: 6px; }
.share-expiry strong { color: var(--color-ink); font-size: 13px; font-weight: 500; }
.share-status { justify-self: start; padding: 4px 8px; border: 1px solid var(--color-border); border-radius: var(--radius-control); color: var(--color-muted); font-size: 12px; }
.share-status.active { border-color: var(--color-primary); color: var(--color-primary); }
.share-status.revoked { color: var(--color-danger); }
.danger-icon { justify-self: end; color: var(--color-danger); }
.security-note { margin: 16px 0 0; line-height: 1.5; }
@media (max-width: 700px) { .share-row { grid-template-columns: minmax(0, 1fr) auto 40px; gap: 12px; padding: 16px 0; } .share-expiry { grid-column: 1 / -1; } .share-status { justify-self: end; } }
</style>
