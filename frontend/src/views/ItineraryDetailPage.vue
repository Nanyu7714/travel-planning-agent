<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowDown, ArrowLeft, ArrowUp, Bot, Check, Clock3, Copy, Edit3, Heart, History, Map, Plus, Save, Send, Star, Trash2, X } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { createShare as createShareApi, getAttractions, getCities, getFavorites, getFeedback, getItinerary, getItineraryAgentRun, getItineraryRevisions, replanItinerary, restoreItineraryRevision, saveFeedback, setFavorite, updateItinerary, type AgentRun, type Attraction, type Itinerary } from '../api'
const route = useRoute(); const itinerary = ref<Itinerary | null>(null); const draft = ref<Itinerary | null>(null); const attractions = ref<Attraction[]>([]); const agentRun = ref<AgentRun | null>(null); const revisions = ref<{ id:number; version_no:number; reason:string; created_at:string }[]>([]); const feedback = ref<{ rating:number|null; comment:string; average:number|null; count:number; status:'open'|'in_progress'|'resolved'|null; admin_reply:string|null; replied_at:string|null }>({ rating:null, comment:'', average:null, count:0, status:null, admin_reply:null, replied_at:null }); const editing = ref(false); const showHistory = ref(false); const saving = ref(false); const instruction = ref(''); const shareUrl = ref(''); const favorite = ref(false); const error = ref(''); const message = ref(''); const rating = ref(0); const comment = ref('')
async function load() { try { const id = Number(route.params.id); const [current, currentFeedback, cities, favorites] = await Promise.all([getItinerary(id), getFeedback(id), getCities(), getFavorites()]); itinerary.value = current; draft.value = structuredClone(current); feedback.value = currentFeedback; rating.value = currentFeedback.rating || 0; comment.value = currentFeedback.comment; favorite.value = favorites.some((item) => item.target_type === 'itinerary' && item.target_id === id); const city = cities.find((item) => item.name === current.city_name); attractions.value = city ? await getAttractions(city.id) : []; agentRun.value = await getItineraryAgentRun(id).catch(() => null) } catch (e) { error.value = e instanceof Error ? e.message : '行程加载失败' } }
function agentStepName(name: string) { return ({ search_attractions: '检索景点资料', select_stops: '筛选候选景点', validate_plan: '校验行程约束' } as Record<string, string>)[name] || name }
function validationSection(name: string): Record<string, any> { return (itinerary.value?.validation?.[name] || {}) as Record<string, any> }
function formatDuration(seconds: unknown) { const minutes = Math.max(0, Math.round(Number(seconds || 0) / 60)); return minutes >= 60 ? `${Math.floor(minutes / 60)}小时${minutes % 60}分钟` : `${minutes}分钟` }
function formatDistance(meters: unknown) { const value = Number(meters || 0); return value >= 1000 ? `${(value / 1000).toFixed(1)}公里` : `${value}米` }
function transportName(value: unknown) { return ({ public_transport: '公共交通', taxi: '打车', walking: '步行优先', driving: '自驾' } as Record<string, string>)[String(value)] || '未指定' }
function edit() { if (itinerary.value) { draft.value = structuredClone(itinerary.value); editing.value = true } }
async function save() { if (!draft.value || !itinerary.value) return; saving.value = true; try { itinerary.value = await updateItinerary(itinerary.value.id, { title: draft.value.title, budget_total: draft.value.budget_total, preferences: draft.value.preferences, expected_version: itinerary.value.lock_version, itinerary_days: draft.value.itinerary_days }); draft.value = structuredClone(itinerary.value); editing.value = false; message.value = '行程已保存' } catch (e) { error.value = e instanceof Error ? e.message : '保存失败' } finally { saving.value = false } }
function moveStop(day: Itinerary['itinerary_days'][number], index: number, offset: number) { const target = index + offset; if (target < 0 || target >= day.stops.length) return; const item = day.stops[index]; day.stops.splice(index, 1); day.stops.splice(target, 0, item) }
function replaceStop(stop: Itinerary['itinerary_days'][number]['stops'][number], attractionId: number) { const attraction = attractions.value.find((item) => item.id === attractionId); if (!attraction) return; stop.attraction_id = attraction.id; stop.name = attraction.name; stop.note = `${attraction.area} · 建议游览${attraction.duration_minutes}分钟 · 开放时间${attraction.opening_hours}` }
function addStop(day: Itinerary['itinerary_days'][number]) { if (!draft.value) return; const used = new Set(draft.value.itinerary_days.flatMap((item) => item.stops.map((stop) => stop.attraction_id))); const attraction = attractions.value.find((item) => !used.has(item.id)); if (!attraction) { message.value = '同城资料中的景点都已加入，可先删除或替换现有景点'; return } const id = -Date.now(); day.stops.push({ id, attraction_id: attraction.id, name: attraction.name, start_time: '09:00', end_time: '11:00', note: `${attraction.area} · 建议游览${attraction.duration_minutes}分钟 · 开放时间${attraction.opening_hours}` }) }
function removeStop(day: Itinerary['itinerary_days'][number], index: number) { day.stops.splice(index, 1) }
function addDay() { if (!draft.value || draft.value.itinerary_days.length >= 10) return; const number = draft.value.itinerary_days.length + 1; draft.value.itinerary_days.push({ day_number: number, title: `第${number}天 · ${draft.value.city_name}探索`, stops: [] }); draft.value.days = draft.value.itinerary_days.length }
function removeDay(index: number) { if (!draft.value || draft.value.itinerary_days.length <= 1) return; draft.value.itinerary_days.splice(index, 1); draft.value.itinerary_days.forEach((day, dayIndex) => { day.day_number = dayIndex + 1 }); draft.value.days = draft.value.itinerary_days.length }
async function replan() { if (!itinerary.value || !instruction.value.trim()) return; saving.value = true; try { itinerary.value = await replanItinerary(itinerary.value.id, instruction.value); draft.value = structuredClone(itinerary.value); instruction.value = ''; message.value = '已按要求调整行程' } catch (e) { error.value = e instanceof Error ? e.message : '自然语言调整失败' } finally { saving.value = false } }
async function history() { if (!itinerary.value) return; showHistory.value = !showHistory.value; if (showHistory.value) revisions.value = await getItineraryRevisions(itinerary.value.id) }
async function restore(version: number) { if (!itinerary.value || !window.confirm(`恢复到第 ${version} 个历史版本？`)) return; itinerary.value = await restoreItineraryRevision(itinerary.value.id, version); draft.value = structuredClone(itinerary.value); revisions.value = await getItineraryRevisions(itinerary.value.id); message.value = '历史版本已恢复' }
async function submitFeedback() { if (!itinerary.value || !rating.value) return; await saveFeedback(itinerary.value.id, rating.value, comment.value); feedback.value = await getFeedback(itinerary.value.id); message.value = '感谢你的评分' }
async function createShare() { if (!itinerary.value || itinerary.value.status !== 'saved') return; error.value = ''; try { const data = await createShareApi(itinerary.value.id); shareUrl.value = data.share_url; await navigator.clipboard?.writeText(data.share_url); message.value = '分享链接已复制' } catch (e) { error.value = e instanceof Error ? e.message : '分享链接创建失败' } }
async function toggleFavorite() { if (!itinerary.value) return; favorite.value = !favorite.value; await setFavorite('itinerary', itinerary.value.id, favorite.value) }
onMounted(load)
</script>
<template>
  <div class="page-container itinerary-detail-page">
    <div v-if="error && !itinerary" class="empty-state"><h2>{{ error }}</h2></div>
    <template v-else-if="itinerary">
      <RouterLink class="back-link" to="/itineraries"><ArrowLeft :size="16" />返回历史行程</RouterLink>
      <header class="itinerary-hero">
        <div><span class="eyebrow">{{ itinerary.city_name }} · {{ itinerary.days }} DAYS</span><h1>{{ editing && draft ? draft.title : itinerary.title }}</h1><p>这是你的行程工作台，可以继续修改、保存、分享和评价。</p></div>
        <div class="hero-actions">
          <button class="icon-button" :class="{ active: favorite }" title="收藏行程" aria-label="收藏行程" @click="toggleFavorite"><Heart :size="19" :fill="favorite ? 'currentColor' : 'none'" /></button>
          <button class="secondary-button" @click="edit"><Edit3 :size="16" />修改行程</button>
          <button class="secondary-button" :disabled="itinerary.status !== 'saved'" :title="itinerary.status === 'saved' ? '创建分享链接' : '请先保存行程'" @click="createShare"><Send :size="16" />分享</button>
          <button class="secondary-button" @click="history"><History :size="16" />历史版本</button>
        </div>
      </header>
      <p v-if="message" class="success-banner"><Check :size="15" />{{ message }}</p>
      <p v-if="error" class="form-error">{{ error }}</p>

      <section class="plan-facts">
        <div class="section-heading"><div><span class="eyebrow">ROUTE & BUDGET</span><h2>路线与预算</h2></div><Map :size="19" /></div>
        <p class="fact-message">{{ validationSection('travel').message || '路线数据待生成' }}</p>
        <div class="fact-grid">
          <div><span>交通方式</span><strong>{{ transportName(validationSection('travel').transport) }}</strong></div>
          <div><span>景点间距离</span><strong>{{ formatDistance(validationSection('travel').total_distance_meters) }}</strong></div>
          <div><span>路线耗时</span><strong>{{ formatDuration(validationSection('travel').total_duration_seconds) }}</strong></div>
          <div><span>景点间交通</span><strong>¥{{ validationSection('travel').total_cost || 0 }}</strong></div>
        </div>
        <div class="intercity-facts">
          <p><strong>往返跨城</strong><span>{{ validationSection('intercity_travel').message || '未选择出发城市，暂未计算跨城费用' }}</span></p>
          <div v-if="validationSection('intercity_travel').origin_city" class="fact-grid">
            <div><span>路线</span><strong>{{ validationSection('intercity_travel').origin_city }} ↔ {{ validationSection('intercity_travel').destination_city }}</strong></div>
            <div><span>往返距离</span><strong>{{ formatDistance(validationSection('intercity_travel').total_distance_meters) }}</strong></div>
            <div><span>往返耗时</span><strong>{{ formatDuration(validationSection('intercity_travel').total_duration_seconds) }}</strong></div>
            <div><span>往返交通</span><strong>¥{{ validationSection('intercity_travel').total_cost || 0 }}</strong></div>
          </div>
        </div>
        <div class="budget-breakdown">
          <div><span>门票</span><strong>¥{{ validationSection('budget').breakdown?.tickets || 0 }}</strong></div>
          <div><span>往返跨城</span><strong>¥{{ validationSection('budget').breakdown?.intercity_transport || 0 }}</strong></div>
          <div><span>餐饮</span><strong>¥{{ validationSection('budget').breakdown?.meals || 0 }}</strong></div>
          <div><span>住宿</span><strong>¥{{ validationSection('budget').breakdown?.hotel || 0 }}</strong></div>
          <div><span>完整估算</span><strong>¥{{ validationSection('budget').breakdown?.total ?? itinerary.budget_total }}</strong></div>
        </div>
        <p class="scope-note">{{ itinerary.budget_scope }}</p>
        <p v-if="validationSection('opening_hours').message" class="opening-note">营业时间：{{ validationSection('opening_hours').message }}</p>
      </section>

      <section v-if="editing && draft" class="edit-panel">
        <div class="section-heading"><div><span class="eyebrow">EDIT</span><h2>编辑行程</h2></div><button class="icon-button" title="关闭编辑" aria-label="关闭编辑" @click="editing = false"><X :size="18" /></button></div>
        <label>行程名称<input v-model="draft.title" /></label>
        <label>预算估算<input v-model.number="draft.budget_total" type="number" min="0" /></label>
        <label>本次偏好<input :value="draft.preferences.join('、')" placeholder="例如：摄影、美食、轻松" @input="draft.preferences = ($event.target as HTMLInputElement).value.split(/[、,，]/).map((item) => item.trim()).filter(Boolean)" /></label>

        <div v-for="(day, dayIndex) in draft.itinerary_days" :key="day.day_number" class="edit-day">
          <div class="edit-day-heading"><strong>第{{ day.day_number }}天</strong><button class="icon-button danger-icon" title="删除这一天" aria-label="删除这一天" :disabled="draft.itinerary_days.length <= 1" @click="removeDay(dayIndex)"><Trash2 :size="15" /></button></div>
          <label>标题<input v-model="day.title" /></label>
          <div v-for="(stop, stopIndex) in day.stops" :key="stop.id" class="edit-stop">
            <select :value="stop.attraction_id" aria-label="替换景点" @change="replaceStop(stop, Number(($event.target as HTMLSelectElement).value))"><option v-for="item in attractions" :key="item.id" :value="item.id">{{ item.name }}</option></select>
            <input v-model="stop.start_time" type="time" aria-label="开始时间" />
            <input v-model="stop.end_time" type="time" aria-label="结束时间" />
            <input v-model="stop.note" aria-label="备注" />
            <div class="stop-actions">
              <button class="icon-button" title="上移" aria-label="上移景点" :disabled="stopIndex === 0" @click="moveStop(day, stopIndex, -1)"><ArrowUp :size="14" /></button>
              <button class="icon-button" title="下移" aria-label="下移景点" :disabled="stopIndex === day.stops.length - 1" @click="moveStop(day, stopIndex, 1)"><ArrowDown :size="14" /></button>
              <button class="icon-button danger-icon" title="删除景点" aria-label="删除景点" @click="removeStop(day, stopIndex)"><Trash2 :size="14" /></button>
            </div>
          </div>
          <button class="text-button add-row-button" @click="addStop(day)"><Plus :size="15" />添加景点</button>
        </div>
        <div class="edit-footer"><button class="secondary-button" :disabled="draft.itinerary_days.length >= 10" @click="addDay"><Plus :size="16" />增加一天</button><button class="primary-button" :disabled="saving" @click="save"><Save :size="16" />保存修改</button></div>
      </section>

      <section v-if="showHistory" class="history-panel">
        <div class="section-heading"><h2>历史版本</h2><History :size="18" /></div>
        <div v-if="!revisions.length" class="small-empty">还没有编辑历史</div>
        <div v-for="revision in revisions" :key="revision.id" class="revision-row"><span>版本 {{ revision.version_no }}<small>{{ revision.reason }} · {{ new Date(revision.created_at).toLocaleString() }}</small></span><button class="text-button" @click="restore(revision.version_no)">恢复</button></div>
      </section>

      <section class="replan-panel">
        <div class="section-heading"><div><span class="eyebrow">NATURAL LANGUAGE EDIT</span><h2>告诉 AI 你想怎么改</h2></div><Map :size="19" /></div>
        <div class="replan-line"><input v-model="instruction" placeholder="例如：把行程改成 3 天，预算调整为 1200 元" @keydown.enter="replan" /><button class="primary-button" :disabled="saving || !instruction.trim()" @click="replan"><Send :size="16" />调整</button></div>
        <small>当前支持天数、预算、删除和替换景点等明确指令；完整大模型重新规划后续接入。</small>
      </section>

      <section v-if="agentRun" class="agent-trace-panel">
        <div class="section-heading"><div><span class="eyebrow">AGENT TRACE</span><h2>规划依据</h2></div><Bot :size="19" /></div>
        <p class="trace-summary">已从 {{ agentRun.steps.find((step) => step.tool_name === 'search_attractions')?.output.candidate_count || 0 }} 个候选景点中选择 {{ agentRun.summary?.selected_count || 0 }} 个景点。</p>
        <p v-if="agentRun.summary?.budget_repair_applied" class="trace-note">初始候选超过门票预算，已优先保留预算内的相关景点。</p>
        <ol class="trace-list"><li v-for="step in agentRun.steps" :key="step.sequence"><strong>{{ agentStepName(step.tool_name) }}</strong><span v-if="step.tool_name === 'select_stops'">已选择 {{ step.output.selected_count || 0 }} 个景点</span><span v-else-if="step.tool_name === 'validate_plan'">预算与单日负荷已完成校验</span><span v-else>已按目的地、兴趣和排除项查询资料</span></li></ol>
      </section>

      <section class="timeline">
        <div v-for="day in itinerary.itinerary_days" :key="day.day_number" class="day-block">
          <div class="day-label"><b>DAY {{ String(day.day_number).padStart(2, '0') }}</b><span>{{ day.title }}</span></div>
          <div v-for="stop in day.stops" :key="stop.id" class="stop-row"><div class="stop-time"><Clock3 :size="14" />{{ stop.start_time }}<small>{{ stop.end_time }}</small></div><div class="stop-dot"></div><div class="stop-content"><h3>{{ stop.name }}</h3><p>{{ stop.note }}</p></div></div>
          <p v-if="!day.stops.length" class="muted-text">当天保留为自由安排。</p>
        </div>
      </section>

      <section class="feedback-panel">
        <div class="section-heading"><div><span class="eyebrow">YOUR REVIEW</span><h2>给这份行程打分</h2></div><Star :size="19" class="accent-icon" /></div>
        <div class="rating-line">
          <div class="star-picker">
            <span v-for="star in 5" :key="star" class="star-control">
              <span class="star-base">★</span><span class="star-fill" :style="{ width: rating >= star * 2 ? '100%' : rating === star * 2 - 1 ? '50%' : '0' }">★</span>
              <button class="star-hit star-hit-left" :aria-label="`${star * 2 - 1}/10 分`" @click="rating = star * 2 - 1"></button><button class="star-hit star-hit-right" :aria-label="`${star * 2}/10 分`" @click="rating = star * 2"></button>
            </span>
          </div>
          <strong>{{ rating ? `${rating}/10` : '未评分' }}</strong><small v-if="feedback.average">平均 {{ feedback.average }}/10（{{ feedback.count }} 条）</small>
        </div>
        <textarea v-model="comment" rows="4" placeholder="这份行程哪里最有帮助？"></textarea><button class="primary-button" :disabled="!rating" @click="submitFeedback"><Star :size="16" />提交评分和评论</button>
        <div v-if="feedback.admin_reply" class="admin-reply"><strong>管理员回复</strong><span v-if="feedback.status === 'resolved'">已解决</span><p>{{ feedback.admin_reply }}</p><small>{{ feedback.replied_at ? new Date(feedback.replied_at).toLocaleString() : '' }}</small></div>
      </section>
      <div v-if="shareUrl" class="share-banner"><Copy :size="16" /><input readonly :value="shareUrl" @focus="($event.target as HTMLInputElement).select()" /></div>
    </template>
  </div>
</template>
<style scoped>.itinerary-detail-page{max-width:920px}.back-link{display:inline-flex;align-items:center;gap:6px;color:var(--primary);font-size:13px;margin-bottom:26px}.itinerary-hero{display:flex;justify-content:space-between;gap:22px;align-items:flex-end;border-bottom:1px solid var(--border);padding-bottom:25px}.hero-actions{display:flex;align-items:center;gap:7px;flex-wrap:wrap;justify-content:flex-end}.icon-button.active{color:var(--accent)}.success-banner,.share-banner{display:flex;align-items:center;gap:7px;padding:11px;background:var(--primary-soft);color:var(--primary);font-size:12px;margin-top:18px}.edit-panel,.history-panel,.replan-panel,.feedback-panel{margin-top:25px;padding:22px;border:1px solid var(--border);background:var(--surface)}.edit-panel label{display:grid;gap:6px;color:var(--secondary);font-size:12px;margin-bottom:12px}.edit-panel input,.replan-line input,.feedback-panel textarea,.share-banner input{width:100%;padding:9px;border:1px solid var(--border);background:var(--bg);outline:0}.edit-day{border-top:1px solid var(--border);padding:14px 0}.edit-day>label{margin-top:10px}.edit-stop{display:grid;grid-template-columns:1.2fr 80px 80px 1.4fr;gap:6px;margin:7px 0}.edit-stop input{min-width:0}.history-panel{padding-bottom:8px}.revision-row{display:flex;justify-content:space-between;gap:10px;padding:11px 0;border-top:1px solid var(--border);font-size:13px}.revision-row small{display:block;color:var(--secondary);font-size:10px;margin-top:4px}.replan-line{display:flex;gap:8px}.replan-line input{flex:1}.replan-panel>small{display:block;color:var(--secondary);font-size:11px;margin-top:9px}.timeline{margin-top:35px}.feedback-panel textarea{display:block;margin:17px 0;resize:vertical}.rating-line{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.star-picker{display:flex}.star-pair{display:flex}.star-pair button{width:19px;padding:0;border:0;background:transparent;color:#d5dcd9;font-size:25px;line-height:1}.star-pair button.on{color:#e6a62e}.rating-line small{color:var(--secondary);font-size:11px}.share-banner input{border:0;background:transparent;color:var(--primary)}@media(max-width:680px){.itinerary-hero{align-items:flex-start;flex-direction:column}.hero-actions{justify-content:flex-start}.edit-stop{grid-template-columns:1fr 1fr}.replan-line{align-items:stretch;flex-direction:column}}
.edit-day-heading{display:flex;align-items:center;justify-content:space-between}.edit-panel select{min-width:0;width:100%;padding:9px;border:1px solid var(--border);background:var(--bg);outline:0}.edit-stop{grid-template-columns:minmax(140px,1.1fr) 90px 90px minmax(180px,1.4fr) auto;align-items:center}.stop-actions{display:flex;align-items:center}.danger-icon{color:var(--danger)}.add-row-button{margin-top:6px}.edit-footer{display:flex;justify-content:space-between;gap:10px;margin-top:10px}.star-control{position:relative;width:29px;height:32px;display:inline-block;color:#d5dcd9;font-size:29px;line-height:32px}.star-base,.star-fill{position:absolute;inset:0;display:block;overflow:hidden;white-space:nowrap}.star-fill{color:#e6a62e}.star-hit{position:absolute;z-index:2;top:0;bottom:0;width:50%;padding:0;border:0;background:transparent}.star-hit-left{left:0}.star-hit-right{right:0}@media(max-width:760px){.edit-stop{grid-template-columns:1fr 1fr}.edit-stop select,.edit-stop input[aria-label="备注"]{grid-column:1/-1}.stop-actions{justify-content:flex-end}.edit-footer{align-items:stretch;flex-direction:column}}
.itinerary-detail-page { max-width: 1280px; }
.itinerary-hero { align-items: flex-start; padding-bottom: 24px; border-bottom-color: var(--color-border-soft); }
.itinerary-hero h1 { margin: 0 0 10px; color: var(--color-ink); font-size: 28px; }
.hero-actions { gap: 8px; }
.hero-actions .icon-button.active { color: var(--color-primary); }
.success-banner, .share-banner { border-radius: var(--radius-control); background: var(--color-surface-soft); color: var(--color-ink); }
.edit-panel, .history-panel, .replan-panel, .feedback-panel, .agent-trace-panel { border: 1px solid var(--color-border-soft); border-radius: var(--radius-card); background: var(--color-surface); box-shadow: none; }
.admin-reply{margin-top:18px;padding:14px;border-left:3px solid var(--color-primary);background:var(--color-surface-soft)}.admin-reply strong{font-size:13px}.admin-reply span{margin-left:8px;color:var(--color-primary);font-size:12px}.admin-reply p{margin:8px 0;color:var(--color-body)}.admin-reply small{color:var(--color-muted);font-size:11px}
.edit-panel label { color: var(--color-muted); }
.edit-panel input, .edit-panel select, .replan-line input, .feedback-panel textarea { min-height: 48px; padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-ink); }
.edit-panel input:focus, .edit-panel select:focus, .replan-line input:focus, .feedback-panel textarea:focus { border-color: var(--color-ink); }
.edit-day { border-top-color: var(--color-border-soft); }
.edit-day-heading strong { color: var(--color-ink); }
.history-panel { padding-bottom: 12px; }
.revision-row { border-top-color: var(--color-border-soft); }
.replan-panel > small, .rating-line small { color: var(--color-muted); }
.agent-trace-panel { max-width: 760px; margin-top: 25px; padding: 22px; }
.trace-summary, .trace-note { margin: 14px 0 0; color: var(--color-muted); font-size: 14px; line-height: 1.5; }
.trace-note { color: var(--color-ink); }
.trace-list { display: grid; gap: 10px; margin: 18px 0 0; padding-left: 22px; }
.trace-list li { display: grid; gap: 3px; padding-left: 4px; color: var(--color-muted); font-size: 13px; }
.trace-list strong { color: var(--color-ink); font-size: 14px; }
.timeline { margin-top: 48px; }
.day-block { margin-bottom: 36px; }
.day-label { margin-bottom: 18px; }
.day-label b { color: var(--color-primary); font-size: 13px; }
.day-label span { color: var(--color-muted); font-size: 14px; }
.stop-time { color: var(--color-primary); }
.stop-dot { background: var(--color-primary); }
.stop-dot::after { background: var(--color-border-strong); }
.stop-content p { color: var(--color-muted); }
.feedback-panel { max-width: 760px; margin-top: 48px; }
.star-control { color: var(--color-border-strong); }
.star-fill { color: var(--color-ink); }
.share-banner { margin-top: 24px; }
@media (max-width: 744px) { .itinerary-hero { flex-direction: column; } .hero-actions { width: 100%; justify-content: flex-start; } .hero-actions .secondary-button { flex: 1; } .edit-panel, .history-panel, .replan-panel, .feedback-panel, .agent-trace-panel { border-radius: var(--radius-control); } }
.plan-facts { max-width: 760px; margin-top: 25px; padding: 22px; border: 1px solid var(--color-border-soft); border-radius: var(--radius-card); background: var(--color-surface); }
.fact-message, .scope-note, .opening-note { margin: 13px 0 0; color: var(--color-muted); font-size: 13px; line-height: 1.5; }
.opening-note { color: var(--color-ink); }
.intercity-facts { margin-top: 18px; }
.intercity-facts > p { display: grid; gap: 5px; margin: 0; color: var(--color-muted); font-size: 13px; line-height: 1.5; }
.intercity-facts > p strong { color: var(--color-ink); }
.fact-grid, .budget-breakdown { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-top: 18px; border: 1px solid var(--color-border-soft); background: var(--color-border-soft); }
.fact-grid > div, .budget-breakdown > div { display: grid; gap: 5px; padding: 13px; background: var(--color-surface); }
.fact-grid span, .budget-breakdown span { color: var(--color-muted); font-size: 11px; }
.fact-grid strong, .budget-breakdown strong { color: var(--color-ink); font-size: 15px; }
@media (max-width: 744px) { .plan-facts { border-radius: var(--radius-control); } .fact-grid, .budget-breakdown { grid-template-columns: 1fr 1fr; } }
</style>
