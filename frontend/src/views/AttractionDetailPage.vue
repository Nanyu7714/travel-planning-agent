<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowLeft, CalendarDays, Clock3, Heart, MapPin } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { api, getCities, recordRecentView, setFavorite, type Attraction, type City } from '../api'

const route = useRoute()
const attraction = ref<Attraction | null>(null)
const city = ref<City | null>(null)
const favorite = ref(false)
const error = ref('')
const loading = ref(true)
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
  <div class="page-container detail-page"><div v-if="loading" class="loading-state">正在加载景点资料...</div><div v-else-if="error" class="empty-state"><MapPin :size="28" /><h2>{{ error }}</h2></div><template v-else-if="attraction"><RouterLink class="back-link" :to="city ? `/cities/${city.slug}` : '/'"><ArrowLeft :size="16" />返回{{ city?.name || '发现' }}</RouterLink><section class="detail-hero"><div class="detail-placeholder"><span>{{ attraction.tags.includes('美食') ? '🍜' : attraction.tags.includes('自然') ? '🌿' : '🏛️' }}</span><small>景点图片待核验</small></div><div class="detail-hero-copy"><span class="eyebrow">ATTRACTION · {{ city?.name }}</span><h1>{{ attraction.name }}</h1><p>{{ attraction.description }}</p><div class="detail-facts"><span><Clock3 :size="15" />{{ attraction.opening_hours }}</span><span><CalendarDays :size="15" />建议 {{ attraction.duration_minutes }} 分钟</span><span>{{ attraction.ticket_price ? `¥${attraction.ticket_price}` : '免费' }}</span></div><div class="tag-line"><span v-for="tag in attraction.tags" :key="tag">{{ tag }}</span></div><button class="secondary-button" :class="{ active: favorite }" @click="toggleFavorite"><Heart :size="16" :fill="favorite ? 'currentColor' : 'none'" />{{ favorite ? '已收藏' : '收藏景点' }}</button></div></section><section class="detail-section"><span class="eyebrow">VISITOR NOTE</span><h2>规划提示</h2><p>当前为平台整理资料，出发前请再次核对开放时间、预约要求和临时调整。</p></section></template></div>
</template>
<style scoped>
.detail-page { max-width: 1050px; }.back-link { display:inline-flex; align-items:center; gap:6px; color:var(--primary); font-size:13px; margin-bottom:26px; }.detail-hero { display:grid; grid-template-columns:minmax(260px,.9fr) 1.1fr; gap:42px; padding-bottom:44px; border-bottom:1px solid var(--border); }.detail-placeholder { min-height:300px; display:grid; place-items:center; align-content:center; gap:10px; background:var(--muted); border:1px solid var(--border); }.detail-placeholder span { font-size:76px; }.detail-placeholder small { color:var(--secondary); font-size:12px; }.detail-hero-copy { align-self:center; }.detail-facts { display:flex; flex-wrap:wrap; gap:18px; margin:22px 0; color:var(--secondary); font-size:12px; }.detail-facts span { display:flex; align-items:center; gap:5px; }.secondary-button.active { color:var(--accent); background:#fff0e9; }.tag-line { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:22px; }.tag-line span { color:var(--primary); background:var(--primary-soft); padding:4px 8px; border-radius:3px; font-size:11px; }.detail-section { padding-top:42px; }@media(max-width:680px){.detail-hero{grid-template-columns:1fr;}.detail-placeholder{min-height:220px;}}
</style>
