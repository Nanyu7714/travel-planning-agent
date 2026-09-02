<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowLeft, ArrowRight, CalendarDays, Clock3, Heart, MapPin, Sparkles } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { api, getCities, recordRecentView, setFavorite, type Attraction, type City } from '../api'

const route = useRoute()
const attraction = ref<Attraction | null>(null)
const city = ref<City | null>(null)
const favorite = ref(false)
const error = ref('')
const loading = ref(true)
const imageFailed = ref(false)
async function toggleFavorite() {
  if (!attraction.value) return
  try { favorite.value = !favorite.value; await setFavorite('attraction', attraction.value.id, favorite.value) }
  catch (e) { favorite.value = !favorite.value; error.value = e instanceof Error ? e.message : '请先登录后收藏' }
}
onMounted(async () => {
  try {
    attraction.value = await api<Attraction>(`/attractions/${route.params.id}`)
    const cities = await getCities(); city.value = cities.find((item) => item.id === attraction.value?.city_id) || null
    if (document.cookie.includes('csrf_token=')) void recordRecentView('attraction', attraction.value.id).catch(() => undefined)
  } catch (e) { error.value = e instanceof Error ? e.message : '景点加载失败' }
  finally { loading.value = false }
})
</script>
<template>
  <div class="page-container detail-page"><div v-if="loading" class="loading-state">正在加载景点资料...</div><div v-else-if="error" class="empty-state"><MapPin :size="28" /><h2>{{ error }}</h2></div><template v-else-if="attraction"><RouterLink class="back-link" :to="city ? `/cities/${city.slug}` : '/'"><ArrowLeft :size="16" />返回{{ city?.name || '发现' }}</RouterLink><section class="detail-hero"><div class="detail-hero-media"><img v-if="attraction.image_url && !imageFailed" :src="attraction.image_url" :alt="`${attraction.name}图片`" @error="imageFailed = true" /><div v-else class="detail-placeholder" aria-hidden="true"><MapPin :size="32" /><small>景点图片待核验</small></div></div><div class="detail-hero-copy"><span class="eyebrow">ATTRACTION · {{ city?.name }}</span><h1>{{ attraction.name }}</h1><p>{{ attraction.description }}</p><div class="detail-facts"><span><Clock3 :size="15" />{{ attraction.opening_hours }}</span><span><CalendarDays :size="15" />建议 {{ attraction.duration_minutes }} 分钟</span><span>{{ attraction.ticket_price ? `¥${attraction.ticket_price}` : '免费' }}</span></div><div class="tag-line"><span v-for="tag in attraction.tags" :key="tag">{{ tag }}</span></div><div class="detail-actions"><RouterLink class="primary-button" :to="{ path: '/planner', query: { attraction: String(attraction.id) } }"><Sparkles :size="16" />用它规划 <ArrowRight :size="16" /></RouterLink><button class="secondary-button" :class="{ active: favorite }" @click="toggleFavorite"><Heart :size="16" :fill="favorite ? 'currentColor' : 'none'" />{{ favorite ? '已收藏' : '收藏景点' }}</button></div></div></section><section class="detail-section visitor-note"><span class="eyebrow">VISITOR NOTE</span><h2>规划提示</h2><p>当前为平台整理资料，出发前请再次核对开放时间、预约要求和临时调整。</p></section></template></div>
</template>
<style scoped>
.detail-page { max-width: 1050px; }
.back-link { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 26px; color: var(--color-primary); font-size: 14px; }
.detail-hero { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(320px, .95fr); gap: 48px; padding-bottom: 48px; border-bottom: 1px solid var(--color-border-soft); }
.detail-hero-media { min-width: 0; overflow: hidden; border-radius: var(--radius-card); aspect-ratio: 4 / 3; background: var(--color-surface-soft); }
.detail-hero-media > img { display: block; width: 100%; height: 100%; object-fit: cover; }
.detail-placeholder { display: grid; width: 100%; height: 100%; place-items: center; align-content: center; gap: 10px; color: var(--color-muted); background: var(--color-surface-soft); }
.detail-placeholder small { font-size: 13px; }
.detail-hero-copy { align-self: center; max-width: 560px; }.detail-hero-copy h1 { margin-bottom: 14px; }.detail-hero-copy p { max-width: 570px; font-size: 16px; line-height: 1.5; }
.detail-facts { display: flex; flex-wrap: wrap; gap: 18px; margin: 24px 0; color: var(--color-muted); font-size: 14px; }.detail-facts span { display: flex; align-items: center; gap: 6px; }.detail-actions { display: flex; flex-wrap: wrap; gap: 10px; }.secondary-button.active { color: var(--color-primary); background: var(--color-primary-disabled); }
.tag-line { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 22px; }.tag-line span { color: var(--color-ink); background: var(--color-surface-soft); padding: 4px 10px; border-radius: var(--radius-pill); font-size: 12px; }
.detail-section { padding-top: 64px; }.visitor-note { max-width: 700px; padding-bottom: 32px; }.visitor-note h2 { margin-bottom: 8px; }.visitor-note p { margin-bottom: 0; }
@media (max-width: 744px) { .detail-hero { grid-template-columns: 1fr; gap: 28px; }.detail-hero-copy { max-width: none; }.detail-section { padding-top: 48px; } }
</style>
