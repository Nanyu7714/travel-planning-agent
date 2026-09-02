<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { AlertTriangle, CalendarDays, CheckCircle2, Clock3, MapPin, Save, Trash2 } from 'lucide-vue-next'
import { api } from '../api'

type ValidationItem = { status: string; message: string }
type Itinerary = { id: number; title: string; city_name: string; days: number; status: string; budget_total: number; budget_scope: string; lock_version: number; validation?: { algorithm_version: string; opening_hours: ValidationItem; travel: ValidationItem; daily_load: ValidationItem; budget: ValidationItem }; itinerary_days: { day_number: number; title: string; stops: { id: number; name: string; start_time: string; end_time: string; note: string }[] }[] }
const itineraries = ref<Itinerary[]>([]); const selected = ref<Itinerary | null>(null); const error = ref(''); const loading = ref(true)
async function load() { try { itineraries.value = await api<Itinerary[]>('/itineraries'); selected.value = itineraries.value[0] || null } catch (e) { error.value = e instanceof Error ? e.message : '请登录后查看行程' } finally { loading.value = false } }
async function save() { if (!selected.value) return; selected.value = await api<Itinerary>(`/itineraries/${selected.value.id}`, { method: 'PATCH', body: '{}' }); await load() }
async function remove() { if (!selected.value || !window.confirm(`将“${selected.value.title}”移入回收站吗？管理员可以恢复这份行程。`)) return; await api(`/itineraries/${selected.value.id}`, { method: 'DELETE' }); selected.value = null; await load() }
onMounted(load)
</script>

<template><div class="page-container itinerary-page"><div class="page-title-row"><div><span class="eyebrow">MY ITINERARIES</span><h1>我的行程</h1><p>把已经想好的出发，留在这里慢慢调整。</p></div><RouterLink class="primary-button" to="/planner">新建规划</RouterLink></div><div v-if="loading" class="loading-state">正在加载...</div><div v-else-if="error" class="empty-state"><MapPin :size="25" /><h2>{{ error }}</h2><RouterLink class="primary-button" to="/planner">去开始规划</RouterLink></div><div v-else-if="!selected" class="empty-state"><CalendarDays :size="28" /><h2>还没有行程</h2><p>从一个城市和几天假期开始吧。</p><RouterLink class="primary-button" to="/planner">开始规划</RouterLink></div><div v-else class="itinerary-layout"><aside class="itinerary-list"><RouterLink v-for="item in itineraries" :key="item.id" :to="`/itineraries/${item.id}`" :class="['itinerary-list-item', { active: selected.id === item.id }]" @click="selected = item"><span>{{ item.city_name }}</span><strong>{{ item.title }}</strong><small>{{ item.status === 'saved' ? '已保存' : '草稿' }} · {{ item.days }}天</small></RouterLink></aside><section class="itinerary-detail"><div class="detail-header"><div><span class="eyebrow">{{ selected.city_name }} · {{ selected.days }} DAYS</span><h2>{{ selected.title }}</h2></div><div class="detail-actions"><RouterLink class="secondary-button" :to="`/itineraries/${selected.id}`">打开行程工作台</RouterLink><button class="danger-button" aria-label="将行程移入回收站" title="移入回收站" @click="remove"><Trash2 :size="17" /></button></div></div><div class="budget-strip"><div><span>预算估算</span><strong>¥{{ selected.budget_total }}</strong></div><small>{{ selected.budget_scope }}</small></div><div class="timeline"><article v-for="day in selected.itinerary_days" :key="day.day_number" class="day-block"><div class="day-label"><b>DAY {{ String(day.day_number).padStart(2, '0') }}</b><span>{{ day.title }}</span></div><div v-for="stop in day.stops" :key="stop.id" class="stop-row"><div class="stop-time"><Clock3 :size="14" />{{ stop.start_time }}<small>{{ stop.end_time }}</small></div><div class="stop-dot"></div><div class="stop-content"><h3>{{ stop.name }}</h3><p>{{ stop.note }}</p></div></div><p v-if="!day.stops.length" class="muted-text">当天暂未安排景点。</p></article></div></section></div></div></template>

<style scoped>
.validation-list { margin: -12px 0 30px; border-top: 1px solid var(--border); }
.validation-row { display: flex; align-items: flex-start; gap: 10px; padding: 11px 0; border-bottom: 1px solid var(--border); font-size: 12px; color: var(--secondary); }
.validation-row svg { flex: none; margin-top: 1px; }
.validation-row strong { color: var(--text); display: inline-block; min-width: 74px; }
.validation-row.passed svg { color: var(--success); }
.validation-row.warning svg { color: var(--gold); }
.validation-list > small { display: block; margin-top: 9px; color: var(--secondary); }
.itinerary-page { max-width: 1280px; }
.itinerary-layout { grid-template-columns: 280px minmax(0, 1fr); gap: 48px; margin-top: 48px; }
.itinerary-list { border-top: 1px solid var(--color-border); }
.itinerary-list-item { min-height: 92px; padding: 16px; border-bottom: 1px solid var(--color-border-soft); border-left: 0; background: transparent; }
.itinerary-list-item:hover { background: var(--color-surface-soft); }
.itinerary-list-item.active { border-left: 3px solid var(--color-primary); background: var(--color-surface-soft); }
.itinerary-list-item span { color: var(--color-primary); font-size: 13px; font-weight: 600; }
.itinerary-list-item strong { margin: 6px 0; color: var(--color-ink); font-size: 16px; font-weight: 600; }
.itinerary-list-item small { color: var(--color-muted); font-size: 13px; }
.itinerary-detail { min-width: 0; }
.detail-header { align-items: flex-start; padding-bottom: 24px; border-bottom-color: var(--color-border-soft); }
.detail-header h2 { margin: 0; color: var(--color-ink); font-size: 22px; }
.detail-actions { gap: 8px; }
.budget-strip { margin: 24px 0 32px; padding: 20px; border: 1px solid var(--color-border-soft); background: var(--color-surface-soft); }
.budget-strip strong { color: var(--color-ink); font-size: 28px; }
.budget-strip small { color: var(--color-muted); font-size: 13px; }
.timeline { margin-top: 0; }
.day-block { margin-bottom: 32px; }
.day-label { margin-bottom: 16px; }
.day-label b { color: var(--color-primary); font-size: 13px; }
.day-label span { color: var(--color-muted); font-size: 14px; }
.stop-row { grid-template-columns: 92px 18px minmax(0, 1fr); gap: 14px; min-height: 72px; }
.stop-time { color: var(--color-primary); font-size: 13px; }
.stop-dot { background: var(--color-primary); }
.stop-dot::after { background: var(--color-border-strong); }
.stop-content h3 { margin-bottom: 5px; }
.stop-content p { margin: 0; color: var(--color-muted); }
@media (max-width: 900px) { .itinerary-layout { grid-template-columns: 1fr; gap: 32px; } .itinerary-list { display: flex; overflow-x: auto; border-top: 0; gap: 8px; } .itinerary-list-item { min-width: 190px; border: 1px solid var(--color-border-soft); border-bottom: 1px solid var(--color-border-soft); } .itinerary-list-item.active { border: 1px solid var(--color-primary); } }
@media (max-width: 520px) { .detail-actions { width: 100%; } .detail-actions .secondary-button { flex: 1; } .stop-row { grid-template-columns: 78px 12px minmax(0, 1fr); gap: 8px; } }
</style>
