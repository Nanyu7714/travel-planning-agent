<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Copy, KeyRound, ShieldAlert, UserRound } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { api } from '../api'

type CurrentUser = { id: number; public_id: string; username: string; email: string; role: string }
const router = useRouter()
const account = ref<CurrentUser | null>(null)
const loading = ref(true)
const error = ref('')
const password = ref('')
const deleting = ref(false)
const copied = ref(false)

async function copyPublicId() {
  if (!account.value) return
  await navigator.clipboard.writeText(account.value.public_id)
  copied.value = true
  window.setTimeout(() => { copied.value = false }, 1500)
}

async function deleteAccount() {
  if (!password.value || deleting.value) return
  if (!window.confirm('确定注销账号吗？注销后公开 ID 会被释放，当前账号将无法再次登录。')) return
  deleting.value = true
  error.value = ''
  try {
    await api('/auth/me', { method: 'DELETE', body: JSON.stringify({ password: password.value }) })
    window.dispatchEvent(new Event('account-deleted'))
    await router.push('/')
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '账号注销失败'
  } finally { deleting.value = false }
}

onMounted(async () => {
  try { account.value = await api<CurrentUser>('/auth/me') }
  catch (exception) { error.value = exception instanceof Error ? exception.message : '请先登录' }
  finally { loading.value = false }
})
</script>

<template>
  <div class="page-container settings-page">
    <div class="page-title-row"><div><span class="eyebrow">ACCOUNT</span><h1>个人资料</h1><p>查看账号身份信息和登录凭据。</p></div></div>
    <div v-if="loading" class="loading-state">正在加载...</div>
    <div v-else-if="!account" class="empty-state"><UserRound :size="26" /><h2>{{ error }}</h2></div>
    <template v-else>
      <section class="profile-section">
        <div class="section-heading"><div><span class="eyebrow">IDENTITY</span><h2>账号信息</h2></div></div>
        <dl class="profile-fields">
          <div><dt>用户 ID</dt><dd><strong class="public-id">{{ account.public_id }}</strong><button class="icon-button" :aria-label="copied ? '已复制' : '复制用户 ID'" :title="copied ? '已复制' : '复制用户 ID'" @click="copyPublicId"><Copy :size="16" /></button></dd></div>
          <div><dt>用户名</dt><dd>{{ account.username }}</dd></div>
          <div><dt>邮箱</dt><dd>{{ account.email }}</dd></div>
          <div><dt>账号类型</dt><dd>{{ account.role === 'admin' ? '管理员' : '普通用户' }}</dd></div>
        </dl>
      </section>
      <section class="danger-section">
        <div class="section-heading"><div><span class="eyebrow danger-eyebrow">ACCOUNT REMOVAL</span><h2>注销账号</h2></div><ShieldAlert :size="20" /></div>
        <p>注销后所有登录设备会立即失效，公开用户 ID 会被释放。后台仍保留原有数据，但不会转移给以后获得相同公开 ID 的用户。</p>
        <form class="delete-account-form" @submit.prevent="deleteAccount"><label><span>确认当前密码</span><span class="password-field"><KeyRound :size="16" /><input v-model="password" type="password" autocomplete="current-password" required /></span></label><button class="delete-account-button" type="submit" :disabled="deleting || !password">{{ deleting ? '正在注销...' : '注销账号' }}</button></form>
        <p v-if="error" class="form-error">{{ error }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.settings-page { max-width: 900px; }
.profile-section, .danger-section { padding-top: 38px; }
.profile-fields { margin: 0; border-top: 1px solid var(--border); }
.profile-fields > div { min-height: 64px; display: grid; grid-template-columns: 180px 1fr; align-items: center; border-bottom: 1px solid var(--border); }
.profile-fields dt { color: var(--secondary); font-size: 12px; }
.profile-fields dd { margin: 0; display: flex; align-items: center; gap: 7px; font-size: 14px; }
.public-id { font-size: 20px; letter-spacing: 2px; }
.danger-section { margin-top: 28px; border-top: 1px solid var(--danger); }
.danger-section .section-heading { margin-bottom: 10px; color: var(--danger); }
.danger-eyebrow { color: var(--danger); }
.delete-account-form { max-width: 480px; display: grid; grid-template-columns: 1fr auto; align-items: end; gap: 10px; margin-top: 20px; }
.delete-account-form label { display: grid; gap: 7px; color: var(--secondary); font-size: 12px; }
.password-field { min-height: 40px; display: flex; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid var(--border); background: var(--surface); }
.password-field input { min-width: 0; flex: 1; border: 0; outline: 0; background: transparent; }
.delete-account-button { min-height: 40px; padding: 0 14px; border: 1px solid var(--danger); background: transparent; color: var(--danger); }
.delete-account-button:hover:not(:disabled) { background: var(--danger); color: white; }
.delete-account-button:disabled { opacity: .45; cursor: not-allowed; }
@media (max-width: 600px) { .profile-fields > div { grid-template-columns: 1fr; gap: 7px; padding: 13px 0; }.delete-account-form { grid-template-columns: 1fr; } }
.settings-page { max-width: 1000px; }
.profile-section { padding-top: 32px; border-top-color: var(--color-border-soft); }
.profile-fields > div { min-height: 72px; grid-template-columns: 220px minmax(0, 1fr); border-bottom-color: var(--color-border-soft); }
.profile-fields dt { color: var(--color-muted); font-size: 13px; }
.profile-fields dd { color: var(--color-ink); font-size: 14px; }
.public-id { font-size: 22px; letter-spacing: 1px; }
.danger-section { border-top-color: var(--color-danger); }
.danger-section .section-heading { color: var(--color-danger); }
.danger-eyebrow { color: var(--color-danger); }
.password-field { min-height: 48px; padding: 0 12px; border-color: var(--color-border); border-radius: var(--radius-control); }
.delete-account-button { min-height: 48px; padding: 0 16px; border-radius: var(--radius-control); }
@media (max-width: 600px) { .profile-fields > div { grid-template-columns: 1fr; min-height: 0; padding: 14px 0; } }
</style>
