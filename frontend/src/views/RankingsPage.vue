<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ArrowLeft, TrendingUp } from 'lucide-vue-next'
import { getCities, getRankings, type City, type Ranking } from '../api'
const cities = ref<City[]>([]); const selectedCityId = ref(0); const rankingType = ref<'city' | 'attraction'>('attraction'); const rankings = ref<Ranking[]>([]); const loading = ref(true); const error = ref('')
async function load() { loading.value = true; error.value = ''; try { rankings.value = await getRankings(rankingType.value, rankingType.value === 'attraction' ? selectedCityId.value || undefined : undefined) } catch (e) { error.value = e instanceof Error ? e.message : '排行加载失败' } finally { loading.value = false } }
watch([selectedCityId, rankingType], load)
onMounted(async () => { cities.value = await getCities(); await load() })
function sourceLabel(item: Ranking) { return item.data_source === 'initialization_heuristic' ? '初始化算法' : item.data_source || '平台综合数据' }
</script>
<template><div class="page-container ranking-page"><RouterLink class="back-link" to="/discover"><ArrowLeft :size="16" />返回发现</RouterLink><div class="page-title-row"><div><span class="eyebrow">CURRENT DATA RANKING</span><h1>热门排行</h1><p>根据平台当前可用数据，查看城市与景点的热度排序。</p></div><TrendingUp :size="28" class="accent-icon" /></div><div class="ranking-layout"><main><div class="ranking-tabs" role="tablist" aria-label="排行类型"><button type="button" :class="{ active: rankingType === 'city' }" role="tab" :aria-selected="rankingType === 'city'" @click="rankingType = 'city'; selectedCityId = 0">城市排行</button><button type="button" :class="{ active: rankingType === 'attraction' }" role="tab" :aria-selected="rankingType === 'attraction'" @click="rankingType = 'attraction'">景点排行</button></div><div v-if="rankingType === 'attraction'" class="ranking-filter" aria-label="城市筛选"><button type="button" :class="['admin-filter-button', { active: selectedCityId === 0 }]" @click="selectedCityId = 0">全部城市</button><button v-for="city in cities" :key="city.id" type="button" :class="['admin-filter-button', { active: selectedCityId === city.id }]" @click="selectedCityId = city.id">{{ city.name }}</button></div><div v-if="loading" class="loading-state">正在计算排行...</div><div v-else-if="error" class="empty-state"><h2>{{ error }}</h2></div><div v-else-if="!rankings.length" class="empty-state"><h2>暂无排行数据</h2><p>当前筛选条件下还没有可展示的数据。</p></div><div v-else class="ranking-list"><div v-for="item in rankings" :key="`${item.city_id}-${item.attraction_id}`" class="ranking-row"><span class="rank-number">{{ String(item.rank).padStart(2, '0') }}</span><strong>{{ item.name }}<small>{{ rankingType === 'attraction' ? `${cities.find((city) => city.id === item.city_id)?.name || '未知城市'} · ${sourceLabel(item)}` : sourceLabel(item) }}</small></strong><span class="score">{{ item.score }}</span></div></div></main><aside class="ranking-note"><span class="eyebrow">ABOUT THE DATA</span><h2>热度如何计算</h2><p>排行会参考资料完整度、标签匹配、可达性和游览时长等平台数据。</p><div><strong>{{ rankings.length }}</strong><span>条当前结果</span></div><small>没有历史快照时，不绘制趋势图。</small></aside></div></div></template>
<style scoped>
.ranking-page { max-width: 1280px; }
.back-link { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 26px; color: var(--color-primary); font-size: 14px; }
.accent-icon { margin-top: 20px; color: var(--color-primary); }
.ranking-layout { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(260px, .75fr); gap: 64px; margin-top: 48px; }
.ranking-tabs { display: flex; gap: 24px; border-bottom: 1px solid var(--color-border-soft); }
.ranking-tabs button { min-height: 44px; padding: 0 0 12px; border: 0; border-bottom: 2px solid transparent; color: var(--color-muted); background: transparent; font-size: 16px; font-weight: 600; }
.ranking-tabs button:hover, .ranking-tabs button.active { border-bottom-color: var(--color-ink); color: var(--color-ink); }
.ranking-filter { display: flex; flex-wrap: wrap; gap: 8px; margin: 24px 0 16px; }
.admin-filter-button { min-height: 40px; padding: 8px 16px; border: 1px solid var(--color-border); border-radius: var(--radius-pill); color: var(--color-muted); background: var(--color-surface); font-size: 14px; }
.admin-filter-button:hover, .admin-filter-button.active { border-color: var(--color-ink); color: var(--color-ink); }
.ranking-list { border-top: 1px solid var(--color-border); }
.ranking-list .ranking-row { min-height: 72px; padding: 16px 4px; }
.ranking-row strong { display: grid; gap: 4px; }
.ranking-row small { color: var(--color-muted); font-size: 13px; font-weight: 400; }
.ranking-note { align-self: start; padding-top: 44px; border-top: 1px solid var(--color-border); }
.ranking-note h2 { margin: 0 0 10px; }
.ranking-note p { margin-bottom: 24px; }
.ranking-note div { display: flex; align-items: baseline; gap: 8px; padding: 16px 0; border-top: 1px solid var(--color-border-soft); border-bottom: 1px solid var(--color-border-soft); }
.ranking-note strong { color: var(--color-ink); font-size: 28px; }
.ranking-note span, .ranking-note small { color: var(--color-muted); font-size: 13px; }
.ranking-note small { display: block; margin-top: 16px; line-height: 1.5; }
@media (max-width: 900px) { .ranking-layout { grid-template-columns: 1fr; gap: 32px; }.ranking-note { padding-top: 0; } }
@media (max-width: 744px) { .ranking-layout { margin-top: 32px; }.ranking-tabs { gap: 20px; } }
</style>
