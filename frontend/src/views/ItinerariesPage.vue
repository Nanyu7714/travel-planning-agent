<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { AlertTriangle, CalendarDays, CheckCircle2, Clock3, MapPin, Save, Trash2 } from 'lucide-vue-next'
import { api } from '../api'

type ValidationItem = { status: string; message: string }
type Itinerary = { id: number; title: string; city_name: string; days: number; status: string; budget_total: number; budget_scope: string; lock_version: number; validation?: { algorithm_version: string; opening_hours: ValidationItem; travel: ValidationItem; daily_load: ValidationItem; budget: ValidationItem }; itinerary_days: { day_number: number; title: string; stops: { id: number; name: string; start_time: string; end_time: string; note: string }[] }[] }
const itineraries = ref<Itinerary[]>([]); const selected = ref<Itinerary | null>(null); const error = ref(''); const loading = ref(true)
async function load() { try { itineraries.value = await api<Itinerary[]>('/itineraries'); selected.value = itineraries.value[0] || null } catch (e) { error.value = e instanceof Error ? e.message : '请登录后查看行程' } finally { loading.value = false } }
async function save() { if (!selected.value) return; selected.value = await api<Itinerary>(`/itineraries/${selected.value.id}`, { method: 'PATCH', body: '{}' }); await load() }
async function remove() { if (!selected.value) return; await api(`/itineraries/${selected.value.id}`, { method: 'DELETE' }); selected.value = null; await load() }
onMounted(load)
</script>

<template><div class="page-container itinerary-page"><div class="page-title-row"><div><span class="eyebrow">MY ITINERARIES</span><h1>我的行程</h1><p>把已经想好的出发，留在这里慢慢调整。</p></div><RouterLink class="primary-button" to="/planner">新建规划</RouterLink></div><div v-if="loading" class="loading-state">正在加载...</div><div v-else-if="error" class="empty-state"><MapPin :size="25" /><h2>{{ error }}</h2><RouterLink class="primary-button" to="/planner">去开始规划</RouterLink></div><div v-else-if="!selected" class="empty-state"><CalendarDays :size="28" /><h2>还没有行程</h2><p>从一个城市和几天假期开始吧。</p><RouterLink class="primary-button" to="/planner">开始规划</RouterLink></div><div v-else class="itinerary-layout"><aside class="itinerary-list"><RouterLink v-for="item in itineraries" :key="item.id" :to="`/itineraries/${item.id}`" :class="['itinerary-list-item', { active: selected.id === item.id }]" @click="selected = item"><span>{{ item.city_name }}</span><strong>{{ item.title }}</strong><small>{{ item.status === 'saved' ? '已保存' : '草稿' }} · {{ item.days }}天</small></RouterLink></aside><section class="itinerary-detail"><div class="detail-header"><div><span class="eyebrow">{{ selected.city_name }} · {{ selected.days }} DAYS</span><h2>{{ selected.title }}</h2></div><div class="detail-actions"><RouterLink class="secondary-button" :to="`/itineraries/${selected.id}`">打开行程工作台</RouterLink><button class="danger-button" aria-label="删除行程" title="删除行程" @click="remove"><Trash2 :size="17" /></button></div></div><div class="budget-strip"><div><span>预算估算</span><strong>¥{{ selected.budget_total }}</strong></div><small>{{ selected.budget_scope }}</small></div><div class="timeline"><article v-for="day in selected.itinerary_days" :key="day.day_number" class="day-block"><div class="day-label"><b>DAY {{ String(day.day_number).padStart(2, '0') }}</b><span>{{ day.title }}</span></div><div v-for="stop in day.stops" :key="stop.id" class="stop-row"><div class="stop-time"><Clock3 :size="14" />{{ stop.start_time }}<small>{{ stop.end_time }}</small></div><div class="stop-dot"></div><div class="stop-content"><h3>{{ stop.name }}</h3><p>{{ stop.note }}</p></div></div><p v-if="!day.stops.length" class="muted-text">当天暂未安排景点。</p></article></div></section></div></div></template>

<style scoped>
.validation-list { margin: -12px 0 30px; border-top: 1px solid var(--border); }
.validation-row { display: flex; align-items: flex-start; gap: 10px; padding: 11px 0; border-bottom: 1px solid var(--border); font-size: 12px; color: var(--secondary); }
.validation-row svg { flex: none; margin-top: 1px; }
.validation-row strong { color: var(--text); display: inline-block; min-width: 74px; }
.validation-row.passed svg { color: var(--success); }
.validation-row.warning svg { color: var(--gold); }
.validation-list > small { display: block; margin-top: 9px; color: var(--secondary); }
</style>
