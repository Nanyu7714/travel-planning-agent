<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, Database, Search } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api, getAttractions, getCities, type City } from '../api'

type CityRow = City & { attraction_count: number }
const cities = ref<CityRow[]>([])
const search = ref('')
const error = ref('')
const filteredCities = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return keyword ? cities.value.filter((city) => `${city.name} ${city.description}`.toLowerCase().includes(keyword)) : cities.value
})
onMounted(async () => {
  try {
    await api('/admin/overview')
    const cityData = await getCities()
    cities.value = await Promise.all(cityData.map(async (city) => ({ ...city, attraction_count: (await getAttractions(city.id)).length })))
  } catch (exception) { error.value = exception instanceof Error ? exception.message : '加载失败' }
})
</script>

<template><div class="page-container"><AdminModuleHeader eyebrow="DESTINATIONS" title="城市管理" description="检查目的地资料、规划状态和景点覆盖情况。" /><div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2></div><template v-else><div class="admin-toolbar"><span class="admin-result-count">{{ filteredCities.length }} 个城市</span><label><span class="sr-only">搜索城市</span><input v-model="search" class="admin-search" placeholder="搜索城市或介绍" /></label></div><div class="admin-table-wrap"><table class="admin-data-table"><thead><tr><th>城市</th><th>规划状态</th><th>支持等级</th><th>建议天数</th><th>预算参考</th><th>景点</th><th aria-label="操作"></th></tr></thead><tbody><tr v-for="city in filteredCities" :key="city.id"><td><strong>{{ city.name }}</strong><small>{{ city.description }}</small></td><td><span :class="['admin-status', { muted: !city.planning_enabled }]">{{ city.planning_enabled ? '可规划' : '已停用' }}</span></td><td>{{ city.support_level }}</td><td>{{ city.recommended_days }}</td><td>{{ city.budget }}</td><td>{{ city.attraction_count }} 个</td><td><RouterLink class="admin-table-action" :to="`/admin/attractions?city=${city.id}`" title="查看城市景点"><ArrowRight :size="16" /></RouterLink></td></tr></tbody></table><div v-if="!filteredCities.length" class="admin-page-empty"><Search :size="20" /><p>没有匹配的城市</p></div></div></template></div></template>
