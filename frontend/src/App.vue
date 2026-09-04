<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { Compass, LogIn, Menu, UserRound, X } from 'lucide-vue-next'
import { ApiError, api, registerAccount } from './api'

const route = useRoute()
const router = useRouter()
const menuOpen = ref(false)
const profileMenuOpen = ref(false)
type CurrentUser = { id: number; public_id: string; username: string; email: string; email_verified: boolean; role: string }
const account = ref<CurrentUser | null>(null)
const authReady = ref(false)
const loginOpen = ref(false)
const authSubmitting = ref(false)
const authCloseButton = ref<HTMLButtonElement | null>(null)
const form = ref({ account: '', password: '' })
const registerForm = ref({ username: '', email: '', password: '' })
const authMode = ref<'login' | 'register'>('login')
const loginError = ref('')
const authNotice = ref('')
const fieldErrors = ref<Record<string, string>>({})
const pageTitle = computed(() => route.path === '/planner' ? 'AI 规划' : route.path === '/itineraries' ? '我的行程' : route.path === '/cities' ? '城市' : route.path === '/admin' ? '管理后台' : '发现')
const isEntryPage = computed(() => route.name === 'entry')

async function loadUser() {
  try {
    account.value = await api<CurrentUser>('/auth/me')
  } catch {
    account.value = null
  } finally {
    authReady.value = true
  }
}
function handleAuthExpired() {
  account.value = null
  loginError.value = '登录已超过 7 天，请重新登录'
  loginOpen.value = true
}
function handleAccountDeleted() { account.value = null }
function handleSignedOut() { account.value = null }
function handleSignedIn() { void loadUser() }
async function login() {
  if (authSubmitting.value) return
  loginError.value = ''
  fieldErrors.value = {}
  if (authMode.value === 'register') {
    const username = registerForm.value.username.trim()
    const email = registerForm.value.email.trim()
    if (username.length < 2) fieldErrors.value.username = '用户名至少输入 2 个字符'
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) fieldErrors.value.email = '邮箱格式不正确，请输入类似 name@example.com 的地址'
    if (registerForm.value.password.length < 10) fieldErrors.value.password = '密码至少输入 10 个字符'
    if (Object.keys(fieldErrors.value).length) return
  }
  authSubmitting.value = true
  try {
    authNotice.value = ''
    if (authMode.value === 'register') {
      const registrationEmail = registerForm.value.email.trim()
      await registerAccount(registerForm.value.username.trim(), registrationEmail, registerForm.value.password)
      loginOpen.value = false
      await router.push({ name: 'auth-verify', query: { email: registrationEmail } })
    } else {
      account.value = await api<CurrentUser>('/auth/login', { method: 'POST', body: JSON.stringify(form.value) })
      authReady.value = true
      loginOpen.value = false
      if (route.path === '/') router.push('/planner')
    }
  } catch (error) {
    if (error instanceof ApiError) fieldErrors.value = error.fieldErrors
    if (!(error instanceof ApiError) || !Object.keys(error.fieldErrors).length) loginError.value = error instanceof Error ? error.message : '登录失败'
  } finally { authSubmitting.value = false }
}
function clearFieldError(field: string) {
  if (fieldErrors.value[field]) delete fieldErrors.value[field]
}
function switchAuthMode(mode: 'login' | 'register') { authMode.value = mode; loginError.value = ''; authNotice.value = ''; fieldErrors.value = {} }
async function logout() { closeMenus(); await api('/auth/logout', { method: 'POST' }).catch(() => undefined); account.value = null; router.push('/') }
function closeMenus() { menuOpen.value = false; profileMenuOpen.value = false }
function handleKeydown(event: KeyboardEvent) { if (event.key === 'Escape' && !loginOpen.value) closeMenus() }
watch(loginOpen, async (open) => { if (open) { await nextTick(); authCloseButton.value?.focus() } else { fieldErrors.value = {}; loginError.value = ''; authNotice.value = '' } })
onMounted(() => { window.addEventListener('auth-expired', handleAuthExpired); window.addEventListener('account-deleted', handleAccountDeleted); window.addEventListener('auth-signed-out', handleSignedOut); window.addEventListener('auth-signed-in', handleSignedIn); document.addEventListener('click', closeMenus); document.addEventListener('keydown', handleKeydown); void loadUser() })
onBeforeUnmount(() => { window.removeEventListener('auth-expired', handleAuthExpired); window.removeEventListener('account-deleted', handleAccountDeleted); window.removeEventListener('auth-signed-out', handleSignedOut); window.removeEventListener('auth-signed-in', handleSignedIn); document.removeEventListener('click', closeMenus); document.removeEventListener('keydown', handleKeydown) })
</script>

<template>
  <RouterView v-if="isEntryPage" />
  <template v-else>
  <header class="topbar">
    <div class="nav-shell" @click.stop>
      <RouterLink class="brand" to="/discover"><span class="brand-mark"><Compass :size="19" /></span>行旅</RouterLink>
      <nav :class="['nav-links', { open: menuOpen }]">
        <RouterLink to="/discover" @click="menuOpen = false">发现</RouterLink>
        <RouterLink to="/cities" @click="menuOpen = false">城市</RouterLink>
        <RouterLink to="/community" @click="menuOpen = false">行程社区</RouterLink>
        <RouterLink to="/planner" @click="menuOpen = false">AI 规划</RouterLink>
        <RouterLink to="/itineraries" @click="menuOpen = false">我的行程</RouterLink>
        <RouterLink to="/rankings" @click="menuOpen = false">热度排行</RouterLink>
        <RouterLink v-if="account?.role === 'admin'" to="/admin" @click="menuOpen = false">管理后台</RouterLink>
      </nav>
      <div class="nav-actions">
        <div v-if="account" class="profile-menu-wrap"><button class="account-name" title="打开用户菜单" :aria-expanded="profileMenuOpen" @click="profileMenuOpen = !profileMenuOpen"><UserRound :size="16" /><span>{{ account.username }}</span></button><div v-if="profileMenuOpen" class="profile-menu" role="menu"><RouterLink to="/me" role="menuitem" @click="profileMenuOpen = false">用户主页</RouterLink><RouterLink to="/me/shares" role="menuitem" @click="profileMenuOpen = false">我的分享</RouterLink><RouterLink to="/community?mine=1" role="menuitem" @click="profileMenuOpen = false">我的发布</RouterLink><RouterLink to="/me/settings/security" role="menuitem" @click="profileMenuOpen = false">账号安全</RouterLink><button role="menuitem" @click="logout">退出登录</button></div></div>
        <button v-else-if="authReady" class="login-button" @click="loginOpen = true"><LogIn :size="16" />登录</button>
        <span v-else class="auth-action-placeholder" aria-hidden="true"></span>
        <button class="menu-button" aria-label="打开菜单" @click="menuOpen = !menuOpen"><X v-if="menuOpen" :size="20" /><Menu v-else :size="20" /></button>
      </div>
    </div>
  </header>
  <main>
    <RouterView />
  </main>
  <div v-if="loginOpen" class="modal-backdrop">
    <section class="modal-panel auth-modal" role="dialog" aria-modal="true" aria-labelledby="auth-title">
      <div class="auth-modal__header"><div><span class="eyebrow">{{ authMode === 'login' ? 'WELCOME BACK' : 'JOIN THE JOURNEY' }}</span><h2 id="auth-title">{{ authMode === 'login' ? '登录行旅' : '注册行旅账号' }}</h2></div><button ref="authCloseButton" class="icon-button auth-close" aria-label="关闭登录窗口" title="关闭" @click="loginOpen = false"><X :size="18" /></button></div>
      <div class="auth-tabs" role="tablist" aria-label="认证方式"><button type="button" role="tab" :aria-selected="authMode === 'login'" :class="{ active: authMode === 'login' }" @click="switchAuthMode('login')">登录</button><button type="button" role="tab" :aria-selected="authMode === 'register'" :class="{ active: authMode === 'register' }" @click="switchAuthMode('register')">注册</button></div>
      <form @submit.prevent="login">
        <template v-if="authMode === 'login'">
          <label>用户名、邮箱或用户 ID<input v-model="form.account" autocomplete="username" placeholder="用户名、邮箱或 4 位用户 ID" required /></label>
          <label>密码<input v-model="form.password" type="password" autocomplete="current-password" required /></label>
        </template>
        <template v-else>
          <label>用户名<input v-model="registerForm.username" autocomplete="username" placeholder="例如：小蓝" :aria-invalid="!!fieldErrors.username" @input="clearFieldError('username')" /><span v-if="fieldErrors.username" class="field-error">{{ fieldErrors.username }}</span></label>
          <label>邮箱<input v-model="registerForm.email" type="email" autocomplete="email" placeholder="name@example.com" :aria-invalid="!!fieldErrors.email" @input="clearFieldError('email')" /><span v-if="fieldErrors.email" class="field-error">{{ fieldErrors.email }}</span></label>
          <label>密码<input v-model="registerForm.password" type="password" autocomplete="new-password" placeholder="至少 10 个字符" :aria-invalid="!!fieldErrors.password" @input="clearFieldError('password')" /><span v-if="fieldErrors.password" class="field-error">{{ fieldErrors.password }}</span></label>
        </template>
        <p v-if="loginError" class="form-error">{{ loginError }}</p>
        <p v-if="authNotice" class="helper-text">{{ authNotice }}</p>
        <button class="primary-button wide" type="submit" :disabled="authSubmitting">{{ authSubmitting ? '正在处理...' : authMode === 'login' ? '登录' : '创建账号' }}</button>
        <div v-if="authMode === 'login'" class="auth-help-links"><RouterLink to="/auth/forgot-password" @click="loginOpen = false">忘记密码</RouterLink><RouterLink to="/auth/resend-verification" @click="loginOpen = false">重新发送验证邮件</RouterLink></div>
      </form>
      <p class="helper-text auth-switch">{{ authMode === 'login' ? '登录后可以保存城市、景点和行程。' : '创建账号后，再单独发送 6 位邮箱验证码。' }}</p>
    </section>
  </div>
  <footer class="footer"><span>行旅 · 让每一段出发，都有清晰的下一站</span><span>数据来源与更新时间以页面展示为准</span></footer>
  </template>
</template>

<style>
.profile-menu-wrap { position: relative; }
.auth-action-placeholder { display: block; width: 86px; min-height: 40px; }
.profile-menu-wrap > .account-name { min-height: 40px; padding: 8px 12px; border: 1px solid var(--color-border); border-radius: var(--radius-pill); background: var(--color-surface); color: var(--color-ink); cursor: pointer; }
.profile-menu-wrap > .account-name:hover, .profile-menu-wrap > .account-name[aria-expanded="true"] { border-color: var(--color-ink); }
.profile-menu { position: absolute; z-index: 30; top: 48px; right: 0; min-width: 168px; padding: 8px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); box-shadow: var(--shadow-hover); }
.profile-menu a, .profile-menu button { display: block; width: 100%; padding: 11px 12px; border: 0; border-radius: var(--radius-control); background: transparent; color: var(--color-ink); font-size: 14px; text-align: left; white-space: nowrap; }
.profile-menu a:hover, .profile-menu button:hover { color: var(--color-ink); background: var(--color-surface-soft); }
.profile-menu button { border-top: 1px solid var(--color-border-soft); margin-top: 6px; padding-top: 14px; color: var(--color-danger); }
.planner-actions { display: flex; align-items: center; gap: 12px; }
.planner-actions .icon-button:disabled { cursor: not-allowed; opacity: .35; }
.auth-switch { text-align: center; }
.field-error { color: var(--danger); font-size: 12px; line-height: 1.5; }
.modal-panel input[aria-invalid="true"] { border-color: var(--danger); }
.auth-modal { width: min(440px, 100%); padding: 32px; border-radius: var(--radius-card); box-shadow: var(--shadow-hover); }
.auth-modal__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.auth-modal__header h2 { margin: 0; }
.auth-close { margin: -8px -8px 0 0; }
.auth-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 0; margin: 28px 0 24px; border-bottom: 1px solid var(--color-border-soft); }
.auth-tabs button { min-height: 44px; padding: 0 8px 12px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--color-muted); font-size: 16px; font-weight: 600; }
.auth-tabs button:hover, .auth-tabs button.active { border-bottom-color: var(--color-ink); color: var(--color-ink); }
.auth-modal form { gap: 16px; }
.auth-modal form label { gap: 8px; color: var(--color-muted); font-size: 13px; }
.auth-modal form input { min-height: 56px; padding: 14px 12px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-ink); }
.auth-modal form input:focus { border-color: var(--color-ink); }
.auth-modal .wide { margin-top: 4px; }
.auth-modal .helper-text { margin-bottom: 0; color: var(--color-muted); line-height: 1.5; }
.auth-dev-link { color: var(--color-primary); font-size: 13px; text-decoration: underline; }
.auth-help-links { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
.auth-help-links a { color: var(--color-muted); }
@media (max-width: 744px) {
  .profile-menu-wrap > .account-name { width: 40px; padding: 0; justify-content: center; }
  .profile-menu-wrap > .account-name span { display: none; }
  .profile-menu { top: 48px; }
  .modal-backdrop { display: flex; align-items: flex-end; padding: 0; }
  .auth-modal {
    position: relative;
    top: auto;
    right: auto;
    left: auto;
    width: 100%;
    max-height: min(82svh, 680px);
    padding: 22px 20px calc(24px + env(safe-area-inset-bottom));
    overflow-y: auto;
    border-radius: 20px 20px 0 0;
    box-shadow: 0 -8px 28px rgba(0, 0, 0, 0.16);
    transform: none;
    animation: auth-sheet-enter 220ms ease-out;
  }
  .auth-modal__header h2 { font-size: 21px; }
  .auth-tabs { margin: 20px 0; }
  .auth-modal form { gap: 14px; }
  .auth-modal form input { min-height: 52px; }
  .auth-help-links { gap: 8px; }
}

@keyframes auth-sheet-enter { from { transform: translateY(28px); } to { transform: translateY(0); } }

@media (prefers-reduced-motion: reduce) { .auth-modal { animation: none; } }
</style>
