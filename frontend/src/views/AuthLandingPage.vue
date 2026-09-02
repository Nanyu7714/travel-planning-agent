<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, Compass, LockKeyhole, Mail, UserRound } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { ApiError, api, registerAccount } from '../api'

type CurrentUser = { id: number; public_id: string; username: string; email: string; email_verified: boolean; role: string }
type AuthMode = 'login' | 'register'

const router = useRouter()
const mode = ref<AuthMode>('login')
const submitting = ref(false)
const error = ref('')
const notice = ref('')
const devActionUrl = ref('')
const fieldErrors = ref<Record<string, string>>({})
const loginForm = ref({ account: '', password: '' })
const registerForm = ref({ username: '', email: '', password: '' })
const sceneIndex = ref(0)
const sceneOffset = ref({ x: 0, y: 0 })

const scenes = [
  { id: 'beijing', name: '北京', imageUrl: '/hero/beijing.jpeg' },
  { id: 'chengdu', name: '成都', imageUrl: '/hero/chengdu.jpg' },
  { id: 'guangzhou', name: '广州', imageUrl: '/hero/guangzhou.jpeg' },
  { id: 'nanjing', name: '南京', imageUrl: '/hero/nanjing.jpeg' },
  { id: 'shanghai', name: '上海', imageUrl: '/hero/shanghai.jpg' },
  { id: 'changsha', name: '长沙', imageUrl: '/hero/changsha.jpg' },
]
const activeScene = computed(() => scenes[sceneIndex.value])
const sceneStyle = computed(() => ({ '--scene-x': `${sceneOffset.value.x}px`, '--scene-y': `${sceneOffset.value.y}px` }))

function switchMode(nextMode: AuthMode) {
  mode.value = nextMode
  error.value = ''
  notice.value = ''
  devActionUrl.value = ''
  fieldErrors.value = {}
}

function clearFieldError(field: string) {
  if (fieldErrors.value[field]) delete fieldErrors.value[field]
}

function validateRegistration() {
  const nextErrors: Record<string, string> = {}
  const username = registerForm.value.username.trim()
  const email = registerForm.value.email.trim()
  if (username.length < 2) nextErrors.username = '用户名至少输入 2 个字符'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) nextErrors.email = '请输入有效的邮箱地址'
  if (registerForm.value.password.length < 10) nextErrors.password = '密码至少输入 10 个字符'
  fieldErrors.value = nextErrors
  return !Object.keys(nextErrors).length
}

async function submit() {
  if (submitting.value) return
  error.value = ''
  notice.value = ''
  devActionUrl.value = ''
  fieldErrors.value = {}
  if (mode.value === 'register' && !validateRegistration()) return
  submitting.value = true
  try {
    if (mode.value === 'register') {
      const result = await registerAccount(registerForm.value.username.trim(), registerForm.value.email.trim(), registerForm.value.password)
      notice.value = result.message
      devActionUrl.value = result.dev_action_url || ''
      registerForm.value.password = ''
    } else {
      await api<CurrentUser>('/auth/login', { method: 'POST', body: JSON.stringify({ account: loginForm.value.account.trim(), password: loginForm.value.password }) })
      window.dispatchEvent(new Event('auth-signed-in'))
      await router.replace('/planner')
    }
  } catch (exception) {
    if (exception instanceof ApiError) fieldErrors.value = exception.fieldErrors
    if (!(exception instanceof ApiError) || !Object.keys(exception.fieldErrors).length) error.value = exception instanceof Error ? exception.message : '暂时无法完成登录，请稍后再试'
  } finally {
    submitting.value = false
  }
}

function browseAsGuest() {
  router.push('/discover')
}

function updateScene(event: PointerEvent) {
  if (event.pointerType !== 'mouse') return
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const x = Math.min(0.9999, Math.max(0, (event.clientX - bounds.left) / bounds.width))
  const y = Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height))
  const nextIndex = Math.floor(x * scenes.length)
  if (nextIndex !== sceneIndex.value) sceneIndex.value = nextIndex
  sceneOffset.value = { x: (0.5 - x) * 26, y: (0.5 - y) * 18 }
}

function resetScene() {
  sceneOffset.value = { x: 0, y: 0 }
}
</script>

<template>
  <main class="auth-entry" :style="sceneStyle" @pointermove="updateScene" @pointerleave="resetScene">
    <Transition name="auth-scene">
      <img :key="activeScene.id" class="auth-entry__image" :src="activeScene.imageUrl" :alt="`${activeScene.name}旅行风景`" />
    </Transition>
    <div class="auth-entry__scrim" aria-hidden="true"></div>

    <div class="auth-entry__content">
      <section class="auth-entry__intro" aria-labelledby="entry-title">
        <div class="auth-entry__brand"><Compass :size="21" />行旅</div>
        <span class="auth-entry__eyebrow">TRAVEL, AT YOUR OWN PACE</span>
        <h1 id="entry-title">把每一次想出发，<br />变成一段好旅程。</h1>
        <p>在城市之间慢慢走，也把想去的地方一一安放好。</p>
      </section>

      <section class="auth-entry__panel" aria-labelledby="auth-title">
        <div class="auth-entry__panel-header">
          <span class="eyebrow">{{ mode === 'login' ? 'WELCOME BACK' : 'JOIN THE JOURNEY' }}</span>
          <h2 id="auth-title">{{ mode === 'login' ? '欢迎回来' : '创建你的行旅账号' }}</h2>
          <p>{{ mode === 'login' ? '继续整理下一段想去的地方。' : '从一座想去的城市开始。' }}</p>
        </div>

        <div class="auth-entry__tabs" role="tablist" aria-label="登录或注册">
          <button type="button" role="tab" :aria-selected="mode === 'login'" :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
          <button type="button" role="tab" :aria-selected="mode === 'register'" :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
        </div>

        <form class="auth-entry__form" @submit.prevent="submit">
          <template v-if="mode === 'login'">
            <label><span>账号</span><div class="auth-entry__input"><UserRound :size="17" /><input v-model="loginForm.account" autocomplete="username" placeholder="用户名、邮箱或用户 ID" required /></div></label>
            <label><span>密码</span><div class="auth-entry__input"><LockKeyhole :size="17" /><input v-model="loginForm.password" type="password" autocomplete="current-password" placeholder="输入密码" required /></div></label>
          </template>
          <template v-else>
            <label><span>用户名</span><div class="auth-entry__input" :class="{ invalid: !!fieldErrors.username }"><UserRound :size="17" /><input v-model="registerForm.username" autocomplete="username" placeholder="例如：小蓝" @input="clearFieldError('username')" /></div><small v-if="fieldErrors.username">{{ fieldErrors.username }}</small></label>
            <label><span>邮箱</span><div class="auth-entry__input" :class="{ invalid: !!fieldErrors.email }"><Mail :size="17" /><input v-model="registerForm.email" type="email" autocomplete="email" placeholder="name@example.com" @input="clearFieldError('email')" /></div><small v-if="fieldErrors.email">{{ fieldErrors.email }}</small></label>
            <label><span>密码</span><div class="auth-entry__input" :class="{ invalid: !!fieldErrors.password }"><LockKeyhole :size="17" /><input v-model="registerForm.password" type="password" autocomplete="new-password" placeholder="至少 10 个字符" @input="clearFieldError('password')" /></div><small v-if="fieldErrors.password">{{ fieldErrors.password }}</small></label>
          </template>
          <p v-if="error" class="auth-entry__error">{{ error }}</p>
          <p v-if="notice" class="auth-entry__notice">{{ notice }}</p>
          <a v-if="devActionUrl" class="auth-entry__dev-link" :href="devActionUrl">打开本地测试邮件链接</a>
          <button class="auth-entry__submit" type="submit" :disabled="submitting">{{ submitting ? '正在处理...' : mode === 'login' ? '登录并继续' : '注册并发送验证邮件' }}<ArrowRight :size="17" /></button>
          <div v-if="mode === 'login'" class="auth-entry__help-links"><RouterLink to="/auth/forgot-password">忘记密码</RouterLink><RouterLink to="/auth/resend-verification">重新发送验证邮件</RouterLink></div>
        </form>

        <div class="auth-entry__guest">
          <span></span><small>或者</small><span></span>
          <button type="button" @click="browseAsGuest"><Compass :size="17" />以游客身份浏览</button>
        </div>
      </section>
    </div>
  </main>
</template>

<style scoped>
.auth-entry { position: relative; display: grid; min-height: 100svh; overflow: hidden; background: var(--color-ink); isolation: isolate; }
.auth-entry__image, .auth-entry__scrim { position: absolute; inset: -28px; width: calc(100% + 56px); height: calc(100% + 56px); }
.auth-entry__image { z-index: -2; object-fit: cover; transform: translate3d(var(--scene-x), var(--scene-y), 0) scale(1.04); transition: transform 520ms ease; will-change: transform, filter, opacity; }
.auth-entry__scrim { z-index: -1; background: rgba(0, 0, 0, 0.48); }
.auth-scene-enter-active, .auth-scene-leave-active { transition: opacity 520ms ease, filter 520ms ease, transform 520ms ease; }
.auth-scene-enter-from, .auth-scene-leave-to { opacity: 0; filter: blur(16px); transform: scale(1.08); }
.auth-entry__content { display: grid; width: min(1180px, calc(100% - 64px)); grid-template-columns: minmax(0, 1fr) minmax(380px, 438px); align-items: center; gap: 72px; margin: auto; padding: 48px 0; }
.auth-entry__intro { align-self: center; color: var(--color-on-dark); }
.auth-entry__brand { display: inline-flex; align-items: center; gap: 8px; margin-bottom: 88px; color: var(--color-on-dark); font-size: 20px; font-weight: 600; }
.auth-entry__brand svg { color: var(--color-primary); }
.auth-entry__eyebrow { display: block; margin-bottom: 14px; color: var(--color-on-dark); font-size: 11px; font-weight: 700; letter-spacing: 1.6px; }
.auth-entry__intro h1 { max-width: 540px; margin: 0 0 16px; color: var(--color-on-dark); font-size: 40px; font-weight: 700; line-height: 1.25; }
.auth-entry__intro p { max-width: 380px; margin: 0; color: rgba(255, 255, 255, 0.9); font-size: 16px; line-height: 1.5; }
.auth-entry__panel { padding: 32px; border-radius: var(--radius-card); background: var(--color-canvas); box-shadow: var(--shadow-hover); }
.auth-entry__panel-header .eyebrow { margin-bottom: 8px; }
.auth-entry__panel-header h2 { margin: 0 0 6px; font-size: 22px; font-weight: 600; line-height: 1.18; }
.auth-entry__panel-header p { margin: 0; color: var(--color-muted); }
.auth-entry__tabs { display: grid; grid-template-columns: repeat(2, 1fr); margin: 28px 0 24px; border-bottom: 1px solid var(--color-border-soft); }
.auth-entry__tabs button { min-height: 44px; padding: 0 8px 12px; border: 0; border-bottom: 2px solid transparent; color: var(--color-muted); background: transparent; font-size: 16px; font-weight: 600; }
.auth-entry__tabs button.active { border-bottom-color: var(--color-ink); color: var(--color-ink); }
.auth-entry__form { display: grid; gap: 16px; }
.auth-entry__form label { display: grid; gap: 8px; color: var(--color-body); font-size: 13px; font-weight: 500; }
.auth-entry__input { display: flex; min-height: 56px; align-items: center; gap: 10px; padding: 0 14px; border: 1px solid var(--color-border); border-radius: var(--radius-control); color: var(--color-muted); background: var(--color-canvas); transition: border-color 180ms ease; }
.auth-entry__input:focus-within { border: 2px solid var(--color-ink); padding: 0 13px; color: var(--color-ink); }
.auth-entry__input.invalid { border-color: var(--color-danger); }
.auth-entry__input input { width: 100%; min-width: 0; border: 0; outline: 0; color: var(--color-ink); background: transparent; font-size: 16px; }
.auth-entry__input input::placeholder { color: var(--color-muted-soft); }
.auth-entry__form small, .auth-entry__error { margin: 0; color: var(--color-danger); font-size: 12px; line-height: 1.4; }
.auth-entry__notice { margin: 0; color: var(--color-body); font-size: 13px; line-height: 1.55; }
.auth-entry__dev-link { color: var(--color-primary); font-size: 13px; text-decoration: underline; }
.auth-entry__help-links { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
.auth-entry__help-links a { color: var(--color-muted); }
.auth-entry__submit, .auth-entry__guest button { display: inline-flex; min-height: 48px; align-items: center; justify-content: center; gap: 8px; border-radius: var(--radius-control); font-size: 16px; font-weight: 500; }
.auth-entry__submit { width: 100%; margin-top: 4px; padding: 14px 24px; border: 0; color: var(--color-on-primary); background: var(--color-primary); }
.auth-entry__submit:hover:not(:disabled) { background: var(--color-primary-active); }
.auth-entry__submit:disabled { cursor: not-allowed; background: var(--color-primary-disabled); }
.auth-entry__guest { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 12px; margin-top: 24px; }
.auth-entry__guest > span { height: 1px; background: var(--color-border-soft); }
.auth-entry__guest small { color: var(--color-muted); font-size: 12px; }
.auth-entry__guest button { grid-column: 1 / -1; width: 100%; padding: 13px 23px; border: 1px solid var(--color-ink); color: var(--color-ink); background: var(--color-canvas); }
.auth-entry__guest button:hover { background: var(--color-surface-soft); }
@media (max-width: 744px) { .auth-entry__content { width: min(100% - 32px, 440px); grid-template-columns: 1fr; gap: 32px; padding: 28px 0; } .auth-entry__brand { margin-bottom: 0; } .auth-entry__intro { display: grid; gap: 12px; } .auth-entry__eyebrow { margin: 0; } .auth-entry__intro h1 { font-size: 28px; } .auth-entry__intro p { font-size: 14px; } .auth-entry__panel { padding: 24px; } }
@media (prefers-reduced-motion: reduce) { .auth-entry__image, .auth-scene-enter-active, .auth-scene-leave-active { transition: none; } }
</style>
