<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, CalendarDays, Heart, MapPin, Search, Star } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { api, getAttractions, getCities, getRankings, recordRecentView, setFavorite, type Attraction, type City, type Ranking } from '../api'

const route = useRoute()
const city = ref<City | null>(null)
const attractions = ref<Attraction[]>([])
const ranking = ref<Ranking[]>([])
const favorite = ref(false)
const error = ref('')
const loading = ref(true)
const cityEmoji: Record<string, string> = { 北京: '🏯', 上海: '🌆', 成都: '🐼' }

const emoji = computed(() => cityEmoji[city.value?.name || ''] || '🧭')
async function toggleFavorite() {
  if (!city.value) return
  try { favorite.value = !favorite.value; await setFavorite('city', city.value.id, favorite.value) }
  catch (e) { favorite.value = !favorite.value; error.value = e instanceof Error ? e.message : '请先登录后收藏' }
}
onMounted(async () => {
  try {
    const cities = await getCities()
    city.value = cities.find((item) => item.slug === route.params.slug) || null
    if (!city.value) throw new Error('城市不存在')
    ;[attractions.value, ranking.value] = await Promise.all([getAttractions(city.value.id), getRankings('attraction', city.value.id)])
    if (document.cookie.includes('csrf_token=')) void recordRecentView('city', city.value.id).catch(() => undefined)
  } catch (e) { error.value = e instanceof Error ? e.message : '城市加载失败' }
  finally { loading.value = false }
})
</script>

<template>
  <div class="page-container detail-page">
    <div v-if="loading" class="loading-state">正在加载城市资料...</div>
    <div v-else-if="error" class="empty-state"><MapPin :size="28" /><h2>{{ error }}</h2></div>
    <template v-else-if="city">
      <RouterLink class="back-link" to="/"><ArrowLeft :size="16" />返回发现</RouterLink>
      <section class="detail-hero"><div class="detail-placeholder"><span>{{ emoji }}</span><small>图片待核验</small></div><div class="detail-hero-copy"><span class="eyebrow">DESTINATION · {{ city.slug.toUpperCase() }}</span><h1>{{ city.name }}</h1><p>{{ city.description }}</p><div class="detail-facts"><span><CalendarDays :size="15" />{{ city.season }}</span><span>建议 {{ city.recommended_days }}</span><span>{{ city.budget }}</span></div><button class="secondary-button" :class="{ active: favorite }" @click="toggleFavorite"><Heart :size="16" :fill="favorite ? 'currentColor' : 'none'" />{{ favorite ? '已收藏' : '收藏城市' }}</button></div></section>
      <section class="detail-section"><div class="section-heading"><div><span class="eyebrow">EXPLORE</span><h2>{{ city.name }}景点</h2></div><span class="section-count">{{ attractions.length }} 个景点</span></div><div class="detail-attraction-grid"><RouterLink v-for="item in attractions" :key="item.id" class="detail-attraction-card" :to="`/attractions/${item.id}`"><div class="attraction-placeholder">{{ item.tags.includes('美食') ? '🍜' : item.tags.includes('自然') ? '🌿' : '🏛️' }}</div><div><span class="rank-chip">热度 {{ ranking.find((row) => row.attraction_id === item.id)?.score || '-' }}</span><h3>{{ item.name }}</h3><p>{{ item.description }}</p><small>{{ item.tags.join(' · ') }}</small></div></RouterLink></div></section><section class="detail-section"><div class="section-heading"><div><span class="eyebrow">TOP 10</span><h2>{{ city.name }}景点热度榜</h2></div><Star :size="20" class="accent-icon" /></div><div class="local-ranking"><div v-for="item in ranking" :key="item.attraction_id" class="ranking-row"><span class="rank-number">{{ String(item.rank).padStart(2, '0') }}</span><strong>{{ item.name }}</strong><span class="score">{{ item.score }}</span></div></div></section>
    </template>
  </div>
</template>

<style scoped>
.detail-page { max-width: 1050px; }
.back-link { display: inline-flex; align-items: center; gap: 6px; color: var(--primary); font-size: 13px; margin-bottom: 26px; }
.detail-hero { display: grid; grid-template-columns: minmax(260px, .9fr) 1.1fr; gap: 42px; padding-bottom: 44px; border-bottom: 1px solid var(--border); }
.detail-placeholder { min-height: 300px; display: grid; place-items: center; align-content: center; gap: 10px; background: var(--muted); border: 1px solid var(--border); }
.detail-placeholder span { font-size: 76px; }.detail-placeholder small { color: var(--secondary); font-size: 12px; }
.detail-hero-copy { align-self: center; }.detail-hero-copy h1 { margin-bottom: 14px; }.detail-hero-copy p { max-width: 570px; }.detail-facts { display: flex; flex-wrap: wrap; gap: 18px; margin: 22px 0; color: var(--secondary); font-size: 12px; }.detail-facts span { display: flex; align-items: center; gap: 5px; }.secondary-button.active { color: var(--accent); background: #fff0e9; }
.detail-section { padding-top: 42px; }.detail-attraction-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }.detail-attraction-card { display: grid; grid-template-columns: 92px 1fr; gap: 14px; padding: 12px; border: 1px solid var(--border); background: var(--surface); }.detail-attraction-card:hover { border-color: var(--primary); }.attraction-placeholder { min-height: 92px; display: grid; place-items: center; background: var(--muted); font-size: 35px; }.detail-attraction-card h3 { margin: 6px 0; }.detail-attraction-card p { font-size: 12px; margin-bottom: 8px; }.detail-attraction-card small { color: var(--secondary); font-size: 11px; }.rank-chip { color: var(--accent); font-size: 11px; }.local-ranking { max-width: 620px; }
@media (max-width: 680px) { .detail-hero, .detail-attraction-grid { grid-template-columns: 1fr; }.detail-placeholder { min-height: 220px; } }
</style>
