<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, CalendarDays, MapPin, Search, Sparkles, TrendingUp } from 'lucide-vue-next'
import { getAttractions, getCities, getRankings, searchCities, type Attraction, type City, type Ranking } from '../api'
import CityCard from '../components/CityCard.vue'

const cities = ref<City[]>([])
const attractions = ref<Attraction[]>([])
const rankings = ref<Ranking[]>([])
const attractionCounts = ref<Record<number, number>>({})
const selectedCity = ref<City | null>(null)
const loading = ref(true)
const searchQuery = ref('')
const searchedCities = ref<City[] | null>(null)
const visibleCities = computed(() => searchedCities.value || cities.value)
async function loadAttractionCounts(cityList: City[]) {
  const entries = await Promise.all(cityList.map(async (city) => {
    try {
      const cityAttractions = await getAttractions(city.id)
      return [city.id, cityAttractions.length] as const
    } catch {
      return [city.id, 0] as const
    }
  }))
  attractionCounts.value = Object.fromEntries(entries)
}
async function search() {
  searchedCities.value = await searchCities(searchQuery.value)
  if (searchedCities.value[0]) await selectCity(searchedCities.value[0])
}
onMounted(async () => {
  try {
    const [cityList, globalRankings] = await Promise.all([getCities(), getRankings('attraction')])
    cities.value = cityList
    rankings.value = globalRankings
    await loadAttractionCounts(cityList)
    if (cities.value[0]) await selectCity(cities.value[0])
  } finally {
    loading.value = false
  }
})
async function selectCity(city: City) {
  selectedCity.value = city
  const cityAttractions = await getAttractions(city.id)
  if (selectedCity.value?.id !== city.id) return
  attractions.value = cityAttractions
}
function cityName(cityId?: number) {
  return cities.value.find((city) => city.id === cityId)?.name || ''
}
</script>

<template>
  <div v-if="loading" class="page-container loading-state">正在整理城市灵感...</div>
  <div v-else class="page-container">
    <section class="home-intro">
      <div><span class="eyebrow">TRAVEL, BETTER PLANNED</span><h1>把想去的地方，<br /><em>变成走得通的行程。</em></h1><p>从城市灵感到每日路线，行旅用可靠的目的地数据和清晰的规划逻辑，陪你把下一次出发想明白。</p><RouterLink class="primary-button" to="/planner"><Sparkles :size="17" />开始规划 <ArrowRight :size="17" /></RouterLink></div>
      <div class="intro-note"><span>当前支持</span><strong>北京 · 上海 · 成都</strong><small>固定数据集持续更新中</small><form class="home-search" @submit.prevent="search"><input v-model="searchQuery" placeholder="搜索城市" aria-label="搜索城市" /><button aria-label="搜索" title="搜索" type="submit"><Search :size="16" /></button></form></div>
    </section>
    <section class="section-block"><div class="section-heading"><div><span class="eyebrow">DESTINATIONS</span><h2>热门城市推荐</h2></div><span class="section-count">{{ visibleCities.length }} 个目的地</span></div><div v-if="!visibleCities.length" class="small-empty">没有找到匹配的城市</div><div v-else class="popular-city-grid"><CityCard v-for="city in visibleCities" :key="city.id" :name="city.name" :image-url="city.image_url" :attraction-count="attractionCounts[city.id] ?? 0" :href="`/cities/${city.slug}`" @click="selectCity(city)" /></div></section>
    <section class="content-grid"><div class="section-block"><div class="section-heading"><div><span class="eyebrow">{{ selectedCity?.name }} · EXPLORE</span><h2>值得加入路线的地方</h2></div><MapPin :size="20" class="muted-icon" /></div><div class="attraction-list"><RouterLink v-for="(item, index) in attractions" :key="item.id" class="attraction-row" :to="`/attractions/${item.id}`"><div class="number-mark">{{ String(index + 1).padStart(2, '0') }}</div><div class="attraction-main"><h3>{{ item.name }}</h3><p>{{ item.description }}</p><div class="tag-line"><span v-for="tag in item.tags" :key="tag">{{ tag }}</span></div></div><div class="attraction-meta"><span><CalendarDays :size="14" />{{ item.opening_hours }}</span><b>{{ item.ticket_price ? `¥${item.ticket_price}` : '免费' }}</b></div></RouterLink></div></div><aside class="ranking-panel"><div class="section-heading"><div><span class="eyebrow">CURRENT DATA RANKING</span><h2>景点热度 TOP 10</h2></div><TrendingUp :size="20" class="accent-icon" /></div><div v-for="item in rankings.slice(0, 10)" :key="item.attraction_id" class="ranking-row"><span class="rank-number">{{ String(item.rank).padStart(2, '0') }}</span><strong>{{ item.name }}<small>{{ cityName(item.city_id) }}</small></strong><span class="score">{{ item.score }}</span></div><RouterLink class="underlined-link" to="/rankings">查看完整热度排行 <ArrowRight :size="15" /></RouterLink></aside></section>
  </div>
</template>

<style scoped>
.popular-city-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.popular-city-grid :deep(.city-card) {
  width: 100%;
}

@media (max-width: 720px) {
  .popular-city-grid {
    grid-template-columns: 1fr;
  }
}
</style>
