<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, MapPinned, Search } from 'lucide-vue-next'
import type { City } from '../api'
import { getAttractions, getCities } from '../api'
import CityCard from '../components/CityCard.vue'

type ListedCity = City & { attractionCount: number }

const cities = ref<ListedCity[]>([])
const loading = ref(true)
const error = ref('')
const query = ref('')
const availability = ref<'all' | 'ready' | 'preview'>('all')
const filteredCities = computed(() => {
  const normalizedQuery = query.value.trim().toLowerCase()
  return cities.value.filter((city) => {
    const matchesQuery = !normalizedQuery || `${city.name} ${city.description}`.toLowerCase().includes(normalizedQuery)
    const matchesAvailability = availability.value === 'all' || (availability.value === 'ready' ? city.planning_enabled : !city.planning_enabled)
    return matchesQuery && matchesAvailability
  })
})

onMounted(async () => {
  try {
    const cityData = await getCities()
    const counts = await Promise.all(cityData.map(async (city) => {
      try { return (await getAttractions(city.id)).length } catch { return 0 }
    }))
    cities.value = cityData.map((city, index) => ({ ...city, attractionCount: counts[index] }))
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '城市加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page-container city-list-page">
    <RouterLink class="back-link" to="/discover"><ArrowLeft :size="16" />返回发现</RouterLink>
    <header class="city-list-header">
      <div>
        <span class="eyebrow">DESTINATIONS</span>
        <h1>城市灵感</h1>
        <p>从熟悉的目的地开始，寻找下一段值得走走的路线。</p>
      </div>
      <div class="city-list-count"><MapPinned :size="18" /><strong>{{ cities.length }}</strong><span>个城市</span></div>
    </header>

    <div class="city-list-toolbar">
      <label class="city-search"><Search :size="17" aria-hidden="true" /><input v-model="query" aria-label="搜索城市" placeholder="搜索城市" /></label>
      <div class="city-filters" aria-label="城市支持状态">
        <button v-for="item in ([['all', '全部城市'], ['ready', '可规划'], ['preview', '即将开放']] as const)" :key="item[0]" type="button" :class="{ active: availability === item[0] }" @click="availability = item[0]">{{ item[1] }}</button>
      </div>
    </div>

    <div v-if="loading" class="city-list-empty"><p>正在加载城市…</p></div>
    <div v-else-if="error" class="city-list-empty"><Search :size="22" /><h2>城市加载失败</h2><p>{{ error }}</p><RouterLink class="text-button" to="/discover">返回发现页</RouterLink></div>
    <template v-else>
      <TransitionGroup v-if="filteredCities.length" name="city-list" tag="section" class="city-list-grid" aria-label="城市列表" appear>
        <CityCard v-for="city in filteredCities" :key="city.id" :name="city.name" :image-url="city.image_url" :attraction-count="city.attractionCount" :href="`/cities/${city.slug}`" />
      </TransitionGroup>
      <div v-else class="city-list-empty"><Search :size="22" /><h2>没有找到匹配的城市</h2><p>试试其他城市名称，或清除当前筛选。</p><button type="button" class="text-button" @click="query = ''; availability = 'all'">清除筛选</button></div>
    </template>
  </div>
</template>

<style scoped>
.city-list-page { max-width: 1280px; }
.back-link { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 26px; color: var(--color-primary); font-size: 14px; }
.city-list-header { display: flex; align-items: end; justify-content: space-between; gap: 24px; padding-bottom: 28px; border-bottom: 1px solid var(--color-border-soft); }
.city-list-header h1 { margin-bottom: 10px; }
.city-list-header p { margin-bottom: 0; }
.city-list-count { display: flex; align-items: center; gap: 8px; flex: none; color: var(--color-muted); font-size: 14px; }
.city-list-count svg { color: var(--color-primary); }
.city-list-count strong { color: var(--color-ink); font-size: 28px; font-weight: 700; }
.city-list-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 24px 0 8px; }
.city-search { display: flex; width: min(100%, 360px); min-height: 48px; align-items: center; gap: 9px; padding: 0 16px; border: 1px solid var(--color-border); border-radius: var(--radius-pill); color: var(--color-muted); background: var(--color-surface); }
.city-search:focus-within { border-color: var(--color-ink); }
.city-search input { min-width: 0; flex: 1; border: 0; outline: 0; color: var(--color-ink); background: transparent; font-size: 14px; }
.city-filters { display: flex; flex-wrap: wrap; gap: 8px; }
.city-filters button { min-height: 40px; padding: 8px 16px; border: 1px solid var(--color-border); border-radius: var(--radius-pill); color: var(--color-muted); background: var(--color-surface); font-size: 14px; }
.city-filters button:hover, .city-filters button.active { border-color: var(--color-ink); color: var(--color-ink); }
.city-list-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; padding-top: 24px; }
.city-list-empty { display: grid; min-height: 260px; place-items: center; align-content: center; gap: 10px; padding-top: 24px; color: var(--color-muted); text-align: center; }
.city-list-empty h2 { margin: 0; color: var(--color-ink); font-size: 20px; }
.city-list-empty p { margin: 0; }
.city-list-empty .text-button { color: var(--color-primary); }
.city-list-enter-active { transition: opacity 260ms ease, transform 260ms ease; }
.city-list-enter-from { opacity: 0; transform: translateY(10px); }
@media (max-width: 1128px) { .city-list-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 744px) { .city-list-header { align-items: flex-start; flex-direction: column; } .city-list-toolbar { align-items: stretch; flex-direction: column; } .city-search { width: 100%; } .city-list-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 520px) { .city-list-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .city-list-enter-active { transition: none; } .city-list-enter-from { opacity: 1; transform: none; } }
</style>
