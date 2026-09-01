<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ArrowUpRight, Database, Landmark, MapPinned, MessageSquareText, Users } from 'lucide-vue-next'
import { api } from '../api'

type Overview = { cities: number; attractions: number; users: number; jobs: number; sessions: number; deleted_sessions: number; feedback: number }
const overview = ref<Overview | null>(null)
const error = ref('')
onMounted(async () => {
  try { overview.value = await api<Overview>('/admin/overview') }
  catch (exception) { error.value = exception instanceof Error ? exception.message : '无权访问' }
})
</script>

<template>
  <div class="page-container admin-page">
    <div class="page-title-row"><div><span class="eyebrow">OPERATIONS</span><h1>管理后台</h1><p>选择一个模块进入对应的管理页面。</p></div><span class="admin-badge">管理员模式</span></div>
    <div v-if="error" class="empty-state"><Database :size="28" /><h2>{{ error }}</h2><p>请使用管理员账号登录。</p></div>
    <template v-else-if="overview">
      <div class="admin-module-grid">
        <RouterLink class="admin-module" to="/admin/cities"><MapPinned :size="24" /><span>城市管理</span><strong>{{ overview.cities }}</strong><small>目的地资料与规划状态</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/attractions"><Landmark :size="24" /><span>景点管理</span><strong>{{ overview.attractions }}</strong><small>景点资料、城市与来源</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/users"><Users :size="24" /><span>用户管理</span><strong>{{ overview.users }}</strong><small>注册账号与启用状态</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/sessions"><MessageSquareText :size="24" /><span>会话管理</span><strong>{{ overview.sessions }}</strong><small>用户已删除 {{ overview.deleted_sessions }} 个，后台保留</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
        <RouterLink class="admin-module" to="/admin/feedback"><MessageSquareText :size="24" /><span>反馈收件箱</span><strong>{{ overview.feedback }}</strong><small>用户行程评分和评论</small><ArrowUpRight class="module-arrow" :size="18" /></RouterLink>
      </div>
      <section class="admin-section"><div class="section-heading"><div><span class="eyebrow">PLATFORM STATUS</span><h2>运行概况</h2></div></div><div class="admin-status-line"><span>累计规划任务</span><strong>{{ overview.jobs }}</strong><small>任务记录可在会话管理中按所属会话查看</small></div></section>
    </template>
  </div>
</template>

<style scoped>
.admin-module-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 18px; margin-top: 34px; }
.admin-module { min-height: 194px; position: relative; display: flex; flex-direction: column; align-items: flex-start; padding: 25px; border: 1px solid var(--border); background: var(--surface); transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }
.admin-module > svg:first-child { color: var(--primary); }
.admin-module span { margin-top: 16px; color: var(--secondary); font-size: 13px; }
.admin-module strong { margin-top: 12px; color: var(--text); font-size: 34px; font-weight: 600; }
.admin-module small { margin-top: auto; color: #97a3a8; font-size: 11px; }
.module-arrow { position: absolute; top: 24px; right: 24px; color: var(--secondary); }
.admin-module:hover, .admin-module:focus-visible { border-color: var(--primary); box-shadow: 0 8px 22px rgba(35, 82, 79, .09); transform: translateY(-2px); outline: none; }
.admin-module:hover .module-arrow { color: var(--primary); }
.admin-status-line { display: grid; grid-template-columns: 1fr auto; gap: 7px 20px; padding: 18px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
.admin-status-line span { font-size: 13px; }.admin-status-line strong { grid-row: span 2; font-size: 28px; }.admin-status-line small { color: var(--secondary); font-size: 11px; }
@media (max-width: 1000px) { .admin-module-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .admin-module-grid { grid-template-columns: 1fr; }.admin-module { min-height: 170px; } }
</style>
