<script setup lang="ts">
import { onMounted, ref } from 'vue'
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
const imageFailed = ref(false)
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
      <RouterLink class="back-link" to="/discover"><ArrowLeft :size="16" />返回发现</RouterLink>
      <section class="detail-hero">
        <div class="detail-hero-media"><img v-if="city.image_url && !imageFailed" :src="city.image_url" :alt="`${city.name}城市景观`" @error="imageFailed = true" /><div v-else class="detail-placeholder" aria-hidden="true"><MapPin :size="32" /><small>图片待核验</small></div></div>
        <div class="detail-hero-copy"><span class="eyebrow">DESTINATION · {{ city.slug.toUpperCase() }}</span><h1>{{ city.name }}</h1><p>{{ city.description }}</p><div class="detail-facts"><span><CalendarDays :size="15" />{{ city.season }}</span><span>建议 {{ city.recommended_days }}</span><span>{{ city.budget }}</span></div><div class="detail-actions"><RouterLink class="primary-button" :to="{ path: '/planner', query: { city: city.slug } }"><Search :size="16" />为我规划</RouterLink><button class="secondary-button" :class="{ active: favorite }" @click="toggleFavorite"><Heart :size="16" :fill="favorite ? 'currentColor' : 'none'" />{{ favorite ? '已收藏' : '收藏城市' }}</button></div></div>
      </section>
      <section class="detail-section"><div class="section-heading"><div><span class="eyebrow">EXPLORE</span><h2>{{ city.name }}景点</h2></div><span class="section-count">{{ attractions.length }} 个景点</span></div><div class="detail-attraction-grid"><RouterLink v-for="item in attractions" :key="item.id" class="detail-attraction-card" :to="`/attractions/${item.id}`"><div class="attraction-placeholder"><img v-if="item.image_url" :src="item.image_url" :alt="`${item.name}图片`" /><span v-else>{{ item.tags.includes('美食') ? '🍜' : item.tags.includes('自然') ? '🌿' : '🏛️' }}</span></div><div class="attraction-card-copy"><span class="rank-chip">热度 {{ ranking.find((row) => row.attraction_id === item.id)?.score || '-' }}</span><h3>{{ item.name }}</h3><p>{{ item.description }}</p><small>{{ item.tags.join(' · ') }}</small></div></RouterLink></div></section><section class="detail-section"><div class="section-heading"><div><span class="eyebrow">TOP 10</span><h2>{{ city.name }}景点热度榜</h2></div><Star :size="20" class="accent-icon" /></div><div class="local-ranking"><div v-for="item in ranking" :key="item.attraction_id" class="ranking-row"><span class="rank-number">{{ String(item.rank).padStart(2, '0') }}</span><strong>{{ item.name }}</strong><span class="score">{{ item.score }}</span></div></div></section>
    </template>
  </div>
</template>

<style scoped>
.detail-page { max-width: 1280px; }
.back-link { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 26px; color: var(--color-primary); font-size: 14px; }
.detail-hero { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(320px, .95fr); gap: 48px; padding-bottom: 48px; border-bottom: 1px solid var(--color-border-soft); }
.detail-hero-media { min-width: 0; overflow: hidden; border-radius: var(--radius-card); background: var(--color-surface-soft); aspect-ratio: 4 / 3; }
.detail-hero-media > img { display: block; width: 100%; height: 100%; object-fit: cover; }
.detail-placeholder { display: grid; width: 100%; height: 100%; place-items: center; align-content: center; gap: 10px; color: var(--color-muted); background: var(--color-surface-soft); }
.detail-placeholder small { font-size: 13px; }
.detail-hero-copy { align-self: center; max-width: 560px; }.detail-hero-copy h1 { margin-bottom: 14px; }.detail-hero-copy p { max-width: 570px; font-size: 16px; line-height: 1.5; }
.detail-facts { display: flex; flex-wrap: wrap; gap: 18px; margin: 24px 0; color: var(--color-muted); font-size: 14px; }.detail-facts span { display: flex; align-items: center; gap: 6px; }.detail-actions { display: flex; flex-wrap: wrap; gap: 10px; }.secondary-button.active { color: var(--color-primary); background: var(--color-primary-disabled); }
.detail-section { padding-top: 64px; }.detail-attraction-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }.detail-attraction-card { display: block; overflow: hidden; border: 1px solid var(--color-border-soft); border-radius: var(--radius-card); background: var(--color-surface); }.detail-attraction-card:hover { border-color: var(--color-border-strong); box-shadow: var(--shadow-hover); }.attraction-placeholder { aspect-ratio: 4 / 3; display: grid; place-items: center; overflow: hidden; background: var(--color-surface-soft); font-size: 35px; }.attraction-placeholder img { display: block; width: 100%; height: 100%; object-fit: cover; }.attraction-card-copy { padding: 16px; }.detail-attraction-card h3 { margin: 6px 0; }.detail-attraction-card p { margin-bottom: 8px; }.detail-attraction-card small { color: var(--color-muted); font-size: 13px; }.rank-chip { color: var(--color-primary); font-size: 12px; }.local-ranking { max-width: 680px; }
@media (max-width: 1128px) { .detail-hero { gap: 32px; }.detail-attraction-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 744px) { .detail-hero { grid-template-columns: 1fr; gap: 28px; }.detail-hero-copy { max-width: none; }.detail-attraction-grid { grid-template-columns: 1fr; }.detail-section { padding-top: 48px; } }
</style>
