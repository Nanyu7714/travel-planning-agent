<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Database, Search } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api, getAttractions, getCities, type Attraction, type City } from '../api'

type AttractionRow = Attraction & { city_id: number; city_name: string }
const route = useRoute()
const cities = ref<City[]>([])
const attractions = ref<AttractionRow[]>([])
const cityFilter = ref(Number(route.query.city) || 0)
const search = ref('')
const error = ref('')
const filteredAttractions = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return attractions.value.filter((item) => (!cityFilter.value || item.city_id === cityFilter.value) && (!keyword || `${item.name} ${item.description} ${item.tags.join(' ')}`.toLowerCase().includes(keyword)))
})
onMounted(async () => {
  try {
    await api('/admin/overview')
    cities.value = await getCities()
    const groups = await Promise.all(cities.value.map(async (city) => (await getAttractions(city.id)).map((item) => ({ ...item, city_id: city.id, city_name: city.name }))))
    attractions.value = groups.flat()
  } catch (exception) { error.value = exception instanceof Error ? exception.message : '加载失败' }
})
</script>

<template><div class="page-container"><AdminModuleHeader eyebrow="ATTRACTION DATA" title="景点管理" description="按城市检查景点内容、开放信息、票价和资料来源。" /><div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2></div><template v-else><div class="admin-toolbar"><div class="admin-toolbar-group"><button :class="['admin-filter-button', { active: cityFilter === 0 }]" @click="cityFilter = 0">全部城市</button><button v-for="city in cities" :key="city.id" :class="['admin-filter-button', { active: cityFilter === city.id }]" @click="cityFilter = city.id">{{ city.name }}</button></div><input v-model="search" class="admin-search" placeholder="搜索景点、介绍或标签" /></div><div class="admin-table-wrap"><table class="admin-data-table"><thead><tr><th>景点</th><th>城市</th><th>区域</th><th>开放时间</th><th>票价</th><th>建议时长</th><th>资料来源</th></tr></thead><tbody><tr v-for="item in filteredAttractions" :key="item.id"><td><strong>{{ item.name }}</strong><small>{{ item.tags.join(' · ') }}</small></td><td>{{ item.city_name }}</td><td>{{ item.area }}</td><td>{{ item.opening_hours }}</td><td>¥{{ item.ticket_price }}</td><td>{{ item.duration_minutes }} 分钟</td><td>{{ item.source }}</td></tr></tbody></table><div v-if="!filteredAttractions.length" class="admin-page-empty"><Search :size="20" /><p>没有匹配的景点</p></div></div></template></div></template>
