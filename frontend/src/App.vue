<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { Compass, LogIn, Menu, UserRound, X } from 'lucide-vue-next'
import { ApiError, api } from './api'

const route = useRoute()
const router = useRouter()
const menuOpen = ref(false)
const profileMenuOpen = ref(false)
type CurrentUser = { id: number; public_id: string; username: string; email: string; role: string }
const account = ref<CurrentUser | null>(null)
const loginOpen = ref(false)
const form = ref({ account: '', password: '' })
const registerForm = ref({ username: '', email: '', password: '' })
const authMode = ref<'login' | 'register'>('login')
const loginError = ref('')
const fieldErrors = ref<Record<string, string>>({})
const pageTitle = computed(() => route.path === '/planner' ? 'AI 规划' : route.path === '/itineraries' ? '我的行程' : route.path === '/cities' ? '城市' : route.path === '/admin' ? '管理后台' : '发现')

async function loadUser() {
  account.value = await api<CurrentUser>('/auth/me').catch(() => null)
}
function handleAuthExpired() {
  account.value = null
  loginError.value = '登录已超过 7 天，请重新登录'
  loginOpen.value = true
}
function handleAccountDeleted() { account.value = null }
function handleSignedOut() { account.value = null }
async function login() {
  loginError.value = ''
  fieldErrors.value = {}
  if (authMode.value === 'register') {
    const username = registerForm.value.username.trim()
    const email = registerForm.value.email.trim()
    if (username.length < 2) fieldErrors.value.username = '用户名至少输入 2 个字符'
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) fieldErrors.value.email = '邮箱格式不正确，请输入类似 name@example.com 的地址'
    if (registerForm.value.password.length < 6) fieldErrors.value.password = '密码至少输入 6 个字符'
    if (Object.keys(fieldErrors.value).length) return
  }
  try {
    const path = authMode.value === 'login' ? '/auth/login' : '/auth/register'
    const body = authMode.value === 'login' ? form.value : registerForm.value
    account.value = await api<CurrentUser>(path, { method: 'POST', body: JSON.stringify(body) })
    loginOpen.value = false
    if (route.path === '/') router.push('/planner')
  } catch (error) {
    if (error instanceof ApiError) fieldErrors.value = error.fieldErrors
    if (!(error instanceof ApiError) || !Object.keys(error.fieldErrors).length) loginError.value = error instanceof Error ? error.message : '登录失败'
  }
}
function clearFieldError(field: string) {
  if (fieldErrors.value[field]) delete fieldErrors.value[field]
}
function switchAuthMode(mode: 'login' | 'register') { authMode.value = mode; loginError.value = ''; fieldErrors.value = {} }
async function logout() { await api('/auth/logout', { method: 'POST' }).catch(() => undefined); account.value = null; router.push('/') }
onMounted(() => { window.addEventListener('auth-expired', handleAuthExpired); window.addEventListener('account-deleted', handleAccountDeleted); window.addEventListener('auth-signed-out', handleSignedOut); void loadUser() })
onBeforeUnmount(() => { window.removeEventListener('auth-expired', handleAuthExpired); window.removeEventListener('account-deleted', handleAccountDeleted); window.removeEventListener('auth-signed-out', handleSignedOut) })
</script>

<template>
  <header class="topbar">
    <div class="nav-shell">
      <RouterLink class="brand" to="/"><span class="brand-mark"><Compass :size="19" /></span>行旅</RouterLink>
      <nav :class="['nav-links', { open: menuOpen }]">
        <RouterLink to="/" @click="menuOpen = false">发现</RouterLink>
        <RouterLink to="/cities" @click="menuOpen = false">城市</RouterLink>
        <RouterLink to="/planner" @click="menuOpen = false">AI 规划</RouterLink>
        <RouterLink to="/itineraries" @click="menuOpen = false">我的行程</RouterLink>
        <RouterLink to="/rankings" @click="menuOpen = false">热度排行</RouterLink>
        <RouterLink v-if="account?.role === 'admin'" to="/admin" @click="menuOpen = false">管理后台</RouterLink>
      </nav>
      <div class="nav-actions">
        <div v-if="account" class="profile-menu-wrap"><button class="account-name" title="打开用户主页" @click="profileMenuOpen = !profileMenuOpen"><UserRound :size="16" />{{ account.username }}</button><div v-if="profileMenuOpen" class="profile-menu"><RouterLink to="/me" @click="profileMenuOpen = false">用户主页</RouterLink><RouterLink to="/me/settings/security" @click="profileMenuOpen = false">账号安全</RouterLink></div></div>
        <button v-if="account" class="text-button" @click="logout">退出</button>
        <button v-else class="login-button" @click="loginOpen = true"><LogIn :size="16" />登录</button>
        <button class="menu-button" aria-label="打开菜单" @click="menuOpen = !menuOpen"><X v-if="menuOpen" :size="20" /><Menu v-else :size="20" /></button>
      </div>
    </div>
  </header>
  <main>
    <RouterView />
  </main>
  <div v-if="loginOpen" class="modal-backdrop">
    <section class="modal-panel">
      <div class="section-heading"><div><span class="eyebrow">{{ authMode === 'login' ? 'WELCOME BACK' : 'JOIN THE JOURNEY' }}</span><h2>{{ authMode === 'login' ? '登录行旅' : '注册行旅账号' }}</h2></div><button class="icon-button" aria-label="关闭" @click="loginOpen = false"><X :size="18" /></button></div>
      <form @submit.prevent="login">
        <template v-if="authMode === 'login'">
          <label>用户名、邮箱或用户 ID<input v-model="form.account" autocomplete="username" placeholder="用户名、邮箱或 4 位用户 ID" required /></label>
          <label>密码<input v-model="form.password" type="password" autocomplete="current-password" required /></label>
        </template>
        <template v-else>
          <label>用户名<input v-model="registerForm.username" autocomplete="username" placeholder="例如：小蓝" :aria-invalid="!!fieldErrors.username" @input="clearFieldError('username')" /><span v-if="fieldErrors.username" class="field-error">{{ fieldErrors.username }}</span></label>
          <label>邮箱<input v-model="registerForm.email" type="email" autocomplete="email" placeholder="name@example.com" :aria-invalid="!!fieldErrors.email" @input="clearFieldError('email')" /><span v-if="fieldErrors.email" class="field-error">{{ fieldErrors.email }}</span></label>
          <label>密码<input v-model="registerForm.password" type="password" autocomplete="new-password" placeholder="至少 6 位" :aria-invalid="!!fieldErrors.password" @input="clearFieldError('password')" /><span v-if="fieldErrors.password" class="field-error">{{ fieldErrors.password }}</span></label>
        </template>
        <p v-if="loginError" class="form-error">{{ loginError }}</p>
        <button class="primary-button wide" type="submit">{{ authMode === 'login' ? '登录' : '注册并登录' }}</button>
      </form>
      <p class="helper-text auth-switch"><template v-if="authMode === 'login'">还没有账号？<button class="text-button" type="button" @click="switchAuthMode('register')">立即注册</button></template><template v-else>已有账号？<button class="text-button" type="button" @click="switchAuthMode('login')">返回登录</button></template></p>
    </section>
  </div>
  <footer class="footer"><span>行旅 · 让每一段出发，都有清晰的下一站</span><span>数据来源与更新时间以页面展示为准</span></footer>
</template>

<style>
.profile-menu-wrap { position: relative; }
.profile-menu-wrap > .account-name { border: 0; background: transparent; cursor: pointer; }
.profile-menu { position: absolute; z-index: 30; top: 44px; right: 0; min-width: 120px; padding: 5px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); box-shadow: var(--airbnb-shadow-hover); }
.profile-menu a { display: block; padding: 9px 10px; color: var(--text); font-size: 12px; white-space: nowrap; }
.profile-menu a:hover { color: var(--primary); background: var(--primary-soft); }
.planner-actions { display: flex; align-items: center; gap: 12px; }
.planner-actions .icon-button:disabled { cursor: not-allowed; opacity: .35; }
.auth-switch { text-align: center; }
.field-error { color: var(--danger); font-size: 12px; line-height: 1.5; }
.modal-panel input[aria-invalid="true"] { border-color: var(--danger); }
</style>
