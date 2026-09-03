<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowUpRight, BookOpenText, ClipboardList, Database, Globe2, Image, Images, Landmark, MailCheck, MapPinned, MessageSquareText, Route, Trophy, Users } from 'lucide-vue-next'
import { api } from '../api'

type Overview = { cities: number; attractions: number; users: number; jobs: number; sessions: number; deleted_sessions: number; itineraries?: number; deleted_itineraries?: number; feedback: number; email_outbox?: number; failed_email_outbox?: number; media_assets?: number; photos?: number; community_posts?: number; community_reports?: number; knowledge_documents?: number }
type AgentRuntime = { mode: 'llm' | 'local'; state: string; model: string | null; label: string; last_error: string | null; last_failure_at: string | null; runs: { completed: number; failed: number; running: number } }
const overview = ref<Overview | null>(null)
const agentRuntime = ref<AgentRuntime | null>(null)
const error = ref('')
onMounted(async () => {
  try {
    const overviewData = await api<Overview>('/admin/overview')
    overview.value = { ...overviewData, email_outbox: overviewData.email_outbox ?? 0, failed_email_outbox: overviewData.failed_email_outbox ?? 0, media_assets: overviewData.media_assets ?? 0, photos: overviewData.photos ?? 0, itineraries: overviewData.itineraries ?? 0, deleted_itineraries: overviewData.deleted_itineraries ?? 0, community_posts: overviewData.community_posts ?? 0, community_reports: overviewData.community_reports ?? 0, knowledge_documents: overviewData.knowledge_documents ?? 0 }
    agentRuntime.value = await api<AgentRuntime>('/admin/agent-status').catch(() => null)
  }
  catch (exception) { error.value = exception instanceof Error ? exception.message : '管理员概览加载失败' }
})
</script>

<template>
  <div class="page-container admin-page">
    <div class="page-title-row"><div><span class="eyebrow">OPERATIONS</span><h1>管理后台</h1><p>选择一个模块进入对应的管理页面。</p></div><span class="admin-badge">管理员模式</span></div>
    <div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2><p>{{ error === '需要管理员权限' ? '当前账号没有管理员权限。' : '后台资料加载失败，请检查后端服务。' }}</p></div>
    <template v-else-if="overview">
      <div class="admin-module-grid">
        <RouterLink class="admin-module" to="/admin/cities"><MapPinned :size="24" /><span>城市管理</span><strong>{{ overview.cities }}</strong><small>目的地资料与规划状态</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/attractions"><Landmark :size="24" /><span>景点管理</span><strong>{{ overview.attractions }}</strong><small>景点资料、城市与来源</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/media-assets"><Image :size="24" /><span>图片管理</span><strong>{{ overview.media_assets }}</strong><small>自动候选、核验与展示状态</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/photos"><Images :size="24" /><span>相片库</span><strong>{{ overview.photos }}</strong><small>自动抓取并保存到本地的相片</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/community"><Globe2 :size="24" /><span>社区审核</span><strong>{{ overview.community_posts }}</strong><small>公开帖子，待处理举报 {{ overview.community_reports }}</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/knowledge"><BookOpenText :size="24" /><span>攻略知识库</span><strong>{{ overview.knowledge_documents }}</strong><small>已审核资料，可用于 RAG 检索</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/rankings"><Trophy :size="24" /><span>排行管理</span><strong>维护</strong><small>手工排行和批量导入</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/audit-logs"><ClipboardList :size="24" /><span>操作审计</span><strong>记录</strong><small>内容维护操作流水</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/users"><Users :size="24" /><span>用户管理</span><strong>{{ overview.users }}</strong><small>注册账号与启用状态</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/sessions"><MessageSquareText :size="24" /><span>会话管理</span><strong>{{ overview.sessions }}</strong><small>用户已删除 {{ overview.deleted_sessions }} 个，后台保留</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/itineraries"><Route :size="24" /><span>行程回收站</span><strong>{{ overview.itineraries }}</strong><small>已删除 {{ overview.deleted_itineraries }} 份，支持恢复</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/feedback"><MessageSquareText :size="24" /><span>反馈收件箱</span><strong>{{ overview.feedback }}</strong><small>用户行程评分和评论</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/email-outbox"><MailCheck :size="24" /><span>邮件投递</span><strong>{{ overview.email_outbox }}</strong><small>失败 {{ overview.failed_email_outbox }} 条，记录已脱敏</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
      </div>
      <section class="admin-section"><div class="section-heading"><div><span class="eyebrow">PLATFORM STATUS</span><h2>运行概况</h2></div></div><div class="admin-status-line"><span>累计规划任务</span><strong>{{ overview.jobs }}</strong><small>任务记录可在会话管理中按所属会话查看</small></div></section>
      <section v-if="agentRuntime" class="admin-section agent-runtime">
        <div class="section-heading"><div><span class="eyebrow">AGENT RUNTIME</span><h2>模型与规划运行状态</h2></div></div>
        <div class="runtime-grid">
          <div><small>对话模型</small><strong>{{ agentRuntime.model || '本地规则模式' }}</strong><span>{{ agentRuntime.label }}</span></div>
          <div><small>规划运行</small><strong>{{ agentRuntime.runs.completed }} 成功 / {{ agentRuntime.runs.failed }} 失败</strong><span>进行中 {{ agentRuntime.runs.running }} 个</span></div>
          <div :class="{ 'runtime-error': agentRuntime.last_error }"><small>最近模型失败原因</small><strong>{{ agentRuntime.last_error || '暂无' }}</strong><span>{{ agentRuntime.last_failure_at ? new Date(agentRuntime.last_failure_at).toLocaleString() : '尚未记录失败' }}</span></div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.admin-module-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin-top: 48px; }
.admin-module { min-height: 172px; position: relative; display: flex; flex-direction: column; align-items: flex-start; padding: 20px; border: 1px solid var(--color-border-soft); border-radius: var(--radius-card); background: var(--color-surface); transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease; }
.admin-module > svg:first-child { color: var(--color-primary); }
.admin-module span { margin-top: 16px; color: var(--color-muted); font-size: 13px; }
.admin-module strong { margin-top: 10px; color: var(--color-ink); font-size: 32px; font-weight: 700; }
.admin-module small { margin-top: auto; color: var(--color-muted); font-size: 12px; }
.module-arrow { position: absolute; top: 24px; right: 24px; color: var(--secondary); }
.admin-module:hover, .admin-module:focus-visible { border-color: var(--color-ink); box-shadow: var(--shadow-hover); transform: translateY(-2px); outline: none; }
.admin-module:hover .module-arrow { color: var(--color-primary); }
.admin-status-line { display: grid; grid-template-columns: 1fr auto; gap: 7px 20px; padding: 18px 0; border-top: 1px solid var(--color-border-soft); border-bottom: 1px solid var(--color-border-soft); }
.admin-status-line span { font-size: 14px; }.admin-status-line strong { grid-row: span 2; color: var(--color-ink); font-size: 28px; }.admin-status-line small { color: var(--color-muted); font-size: 13px; }
.agent-runtime { margin-top: 32px; }.runtime-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }.runtime-grid > div { display: grid; gap: 7px; padding: 16px 0; border-top: 1px solid var(--color-border-soft); }.runtime-grid small, .runtime-grid span { color: var(--color-muted); font-size: 12px; }.runtime-grid strong { font-size: 15px; line-height: 1.4; }.runtime-error strong { color: var(--color-primary); }
@media (max-width: 1128px) { .admin-module-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 744px) { .admin-module-grid, .runtime-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 520px) { .admin-module-grid { grid-template-columns: 1fr; }.admin-module { min-height: 160px; } }
</style>
