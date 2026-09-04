<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowLeft, CheckCircle2, KeyRound, Mail, Send, ShieldCheck } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { confirmEmailChange, forgotPassword, resetPassword, sendVerificationCode, verifyEmail } from '../api'

const route = useRoute()
const mode = computed(() => String(route.name || ''))
const email = ref('')
const code = ref('')
const token = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const message = ref('')
const error = ref('')
const devActionUrl = ref('')
const retrySeconds = ref(0)
const verificationComplete = ref(false)
let retryTimer: number | undefined
let previousReferrerPolicy: string | null = null

const title = computed(() => mode.value === 'auth-forgot' ? '找回密码' : mode.value === 'auth-resend' ? '重新验证邮箱' : mode.value === 'auth-reset' ? '设置新密码' : mode.value === 'auth-change-confirm' ? '确认新邮箱' : '验证邮箱')
const isVerificationForm = computed(() => mode.value === 'auth-verify' || mode.value === 'auth-resend')

function startRetryCountdown(seconds: number) {
  if (retryTimer !== undefined) window.clearInterval(retryTimer)
  retrySeconds.value = Math.min(60, Math.max(0, seconds))
  if (!retrySeconds.value) return
  retryTimer = window.setInterval(() => {
    retrySeconds.value = Math.max(0, retrySeconds.value - 1)
    if (!retrySeconds.value && retryTimer !== undefined) window.clearInterval(retryTimer)
  }, 1000)
}

async function sendCode() {
  error.value = ''; message.value = ''
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())) { error.value = '请输入有效的邮箱地址'; return }
  loading.value = true
  try {
    const result = await sendVerificationCode(email.value.trim())
    message.value = result.message
    startRetryCountdown(result.retry_after_seconds || 0)
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '验证码发送失败'
  } finally { loading.value = false }
}

async function submitVerification() {
  error.value = ''
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())) { error.value = '请输入有效的邮箱地址'; return }
  if (!/^\d{6}$/.test(code.value)) { error.value = '请输入邮件中的 6 位数字验证码'; return }
  loading.value = true
  try {
    const result = await verifyEmail(email.value.trim(), code.value)
    message.value = result.message
    verificationComplete.value = true
    code.value = ''
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '验证码校验失败'
  } finally { loading.value = false }
}

async function runTokenAction() {
  if (!token.value) { error.value = '链接中缺少一次性令牌，请重新申请邮件。'; return }
  loading.value = true; error.value = ''
  try {
    const result = await confirmEmailChange(token.value)
    message.value = result.message
    window.dispatchEvent(new Event('auth-signed-out'))
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '链接处理失败'
  } finally { loading.value = false }
}

async function submitEmail() {
  loading.value = true; error.value = ''; message.value = ''; devActionUrl.value = ''
  try {
    const result = await forgotPassword(email.value)
    message.value = result.message
    devActionUrl.value = result.dev_action_url || ''
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '邮件申请失败'
  } finally { loading.value = false }
}

async function submitPassword() {
  error.value = ''; message.value = ''
  if (newPassword.value.length < 10) { error.value = '新密码至少需要 10 个字符'; return }
  if (newPassword.value !== confirmPassword.value) { error.value = '两次输入的新密码不一致'; return }
  if (!token.value) { error.value = '链接中缺少一次性令牌，请重新申请邮件。'; return }
  loading.value = true
  try {
    await resetPassword(token.value, newPassword.value)
    message.value = '密码已重置，所有旧设备都已退出。现在可以使用新密码登录。'
    window.dispatchEvent(new Event('auth-signed-out'))
    newPassword.value = ''; confirmPassword.value = ''
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '密码重置失败'
  } finally { loading.value = false }
}

onMounted(() => {
  let meta = document.querySelector<HTMLMetaElement>('meta[name="referrer"]')
  previousReferrerPolicy = meta?.content ?? null
  if (!meta) { meta = document.createElement('meta'); meta.name = 'referrer'; document.head.appendChild(meta) }
  meta.content = 'no-referrer'
  email.value = typeof route.query.email === 'string' ? route.query.email : ''
  token.value = typeof route.query.token === 'string' ? route.query.token : ''
  if (route.query.token) window.history.replaceState({}, '', route.path)
  if (mode.value === 'auth-change-confirm') void runTokenAction()
})

onBeforeUnmount(() => {
  if (retryTimer !== undefined) window.clearInterval(retryTimer)
  const meta = document.querySelector<HTMLMetaElement>('meta[name="referrer"]')
  if (meta) meta.content = previousReferrerPolicy || 'same-origin'
})
</script>

<template>
  <div class="page-container auth-action-page">
    <RouterLink class="back-link" to="/"><ArrowLeft :size="16" />返回登录</RouterLink>
    <header><span class="eyebrow">ACCOUNT SECURITY</span><h1>{{ title }}</h1></header>

    <div v-if="verificationComplete" class="action-result"><CheckCircle2 :size="28" /><h2>验证成功</h2><p>{{ message }}</p><RouterLink class="primary-button" to="/">返回登录</RouterLink></div>
    <form v-else-if="isVerificationForm" class="action-form" @submit.prevent="submitVerification">
      <label>邮箱地址<div><Mail :size="17" /><input v-model="email" type="email" autocomplete="email" placeholder="name@example.com" required /></div></label>
      <div class="code-row">
        <label>6 位验证码<div><ShieldCheck :size="17" /><input v-model="code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="000000" required /></div></label>
        <button class="secondary-button send-code-button" type="button" :disabled="loading || retrySeconds > 0" @click="sendCode"><Send :size="16" />{{ retrySeconds > 0 ? `${retrySeconds} 秒` : '发送验证码' }}</button>
      </div>
      <p v-if="message" class="form-notice">{{ message }}</p>
      <p v-if="error" class="form-error">{{ error }}</p>
      <button class="primary-button" :disabled="loading">{{ loading ? '正在处理...' : '验证邮箱' }}</button>
    </form>
    <div v-else-if="loading" class="action-status"><span class="action-spinner"></span><p>正在安全处理...</p></div>
    <div v-else-if="message" class="action-result"><CheckCircle2 :size="28" /><h2>操作完成</h2><p>{{ message }}</p><a v-if="devActionUrl" class="primary-button" :href="devActionUrl">打开本地测试邮件链接</a><RouterLink v-else class="primary-button" to="/">返回登录</RouterLink></div>
    <form v-else-if="mode === 'auth-forgot'" class="action-form" @submit.prevent="submitEmail">
      <label>邮箱地址<div><Mail :size="17" /><input v-model="email" type="email" autocomplete="email" placeholder="name@example.com" required /></div></label>
      <p v-if="error" class="form-error">{{ error }}</p>
      <button class="primary-button" :disabled="loading"><Send :size="16" />发送邮件</button>
    </form>
    <form v-else-if="mode === 'auth-reset'" class="action-form" @submit.prevent="submitPassword">
      <label>新密码<div><KeyRound :size="17" /><input v-model="newPassword" type="password" autocomplete="new-password" minlength="10" placeholder="至少 10 个字符" required /></div></label>
      <label>再次输入新密码<div><KeyRound :size="17" /><input v-model="confirmPassword" type="password" autocomplete="new-password" minlength="10" required /></div></label>
      <p v-if="error" class="form-error">{{ error }}</p>
      <button class="primary-button" :disabled="loading">保存新密码</button>
    </form>
    <div v-else-if="error" class="action-result action-result--error"><KeyRound :size="28" /><h2>无法完成操作</h2><p>{{ error }}</p><RouterLink class="secondary-button" to="/">重新申请</RouterLink></div>
  </div>
</template>

<style scoped>
.auth-action-page{width:min(calc(100% - 32px),680px);min-height:calc(100vh - 160px);padding-top:72px}.auth-action-page header{padding:24px 0 28px;border-bottom:1px solid var(--color-border-soft)}.auth-action-page h1{margin:8px 0 0;font-size:32px}.action-form{display:grid;max-width:480px;gap:18px;padding-top:32px}.action-form label{display:grid;gap:8px;color:var(--color-muted);font-size:13px}.action-form label>div{display:flex;min-height:52px;align-items:center;gap:9px;padding:0 13px;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-surface)}.action-form input{width:100%;min-width:0;border:0;outline:0;background:transparent;color:var(--color-ink)}.action-form .primary-button{width:max-content}.code-row{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:end;gap:12px}.send-code-button{display:inline-flex;min-width:132px;min-height:52px;align-items:center;justify-content:center;gap:7px}.form-notice{margin:0;color:var(--color-muted);line-height:1.6}.action-status,.action-result{display:grid;justify-items:start;gap:12px;padding:40px 0}.action-result svg{color:var(--color-primary)}.action-result h2,.action-result p{margin:0}.action-result p{max-width:540px;color:var(--color-muted);line-height:1.65}.action-result--error svg,.form-error{color:var(--color-danger)}.form-error{margin:0}.action-spinner{width:24px;height:24px;border:2px solid var(--color-border);border-top-color:var(--color-primary);border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:520px){.code-row{grid-template-columns:1fr}.send-code-button{width:100%}}
</style>
