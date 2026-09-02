<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowLeft, ImagePlus, Send, X } from 'lucide-vue-next'
import { createCommunityPost, uploadCommunityImages, type Itinerary } from '../api'
import { onMounted } from 'vue'
import { api } from '../api'
import { useRouter } from 'vue-router'

const router = useRouter()
const itineraries = ref<Itinerary[]>([])
const selectedId = ref<number | null>(null)
const title = ref('')
const body = ref('')
const files = ref<File[]>([])
const error = ref('')
const submitting = ref(false)
const selected = computed(() => itineraries.value.find((item) => item.id === selectedId.value) || null)

function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const candidates = Array.from(input.files || [])
  const valid = candidates.filter((file) => ['image/jpeg', 'image/png', 'image/webp'].includes(file.type) && file.size <= 8 * 1024 * 1024)
  if (valid.length !== candidates.length) error.value = '仅支持不超过 8MB 的 JPEG、PNG 或 WebP 图片'
  files.value = [...files.value, ...valid].slice(0, 9)
  input.value = ''
}
function removeFile(index: number) { files.value.splice(index, 1) }
function selectItinerary() { if (selected.value && !title.value) title.value = selected.value.title }
async function publish() {
  if (!selectedId.value || !title.value.trim()) return
  submitting.value = true; error.value = ''
  try {
    const post = await createCommunityPost({ itinerary_id: selectedId.value, title: title.value.trim(), body: body.value.trim() })
    if (files.value.length) await uploadCommunityImages(post.id, files.value)
    await router.push(`/community/posts/${post.id}`)
  } catch (exception) { error.value = exception instanceof Error ? exception.message : '发布失败' } finally { submitting.value = false }
}
onMounted(async () => { try { itineraries.value = (await api<Itinerary[]>('/itineraries')).filter((item) => item.status === 'saved') } catch (exception) { error.value = exception instanceof Error ? exception.message : '请先登录后发布行程' } })
</script>

<template>
  <div class="page-container publish-page">
    <RouterLink class="back-link" to="/community"><ArrowLeft :size="16" />返回旅行灵感</RouterLink>
    <header><span class="eyebrow">PUBLISH A TRIP</span><h1>发布行程</h1><p>从已保存的行程开始，补充属于你的旅行片段。</p></header>
    <form class="publish-form" @submit.prevent="publish">
      <label>选择已保存行程<select v-model.number="selectedId" required @change="selectItinerary"><option :value="null" disabled>选择一份行程</option><option v-for="item in itineraries" :key="item.id" :value="item.id">{{ item.city_name }} · {{ item.title }} · {{ item.days }} 天</option></select></label>
      <div v-if="selected" class="trip-summary"><strong>{{ selected.city_name }} · {{ selected.days }} 天</strong><span>预算 ¥{{ selected.budget_total }}</span></div>
      <label>标题<input v-model="title" maxlength="120" placeholder="给这段旅程起个名字" required /></label>
      <label>旅行心得<textarea v-model="body" maxlength="5000" rows="7" placeholder="写下让这趟旅行特别的瞬间" /></label>
      <section class="upload-section"><div><strong>景点照片</strong><small>{{ files.length }}/9</small></div><label class="upload-trigger" title="添加照片"><ImagePlus :size="20" /><span>添加照片</span><input type="file" accept="image/jpeg,image/png,image/webp" multiple @change="chooseFiles" /></label><div v-if="files.length" class="file-list"><div v-for="(file, index) in files" :key="`${file.name}-${index}`"><span>{{ file.name }}</span><button type="button" :aria-label="`移除 ${file.name}`" title="移除照片" @click="removeFile(index)"><X :size="15" /></button></div></div></section>
      <p v-if="error" class="form-error">{{ error }}</p><button class="primary-button publish-button" :disabled="submitting || !selectedId || !title.trim()" type="submit"><Send :size="16" />{{ submitting ? '发布中...' : '发布到社区' }}</button>
    </form>
  </div>
</template>

<style scoped>
.publish-page { max-width: 760px; }.back-link { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 28px; color: var(--color-primary); font-size: 14px; }.publish-page h1 { margin: 0 0 10px; color: var(--color-ink); font-size: 28px; }.publish-page header > p { margin: 0; }.publish-form { display: grid; gap: 20px; margin-top: 40px; }.publish-form > label { display: grid; gap: 8px; color: var(--color-ink); font-size: 14px; font-weight: 600; }.publish-form input, .publish-form select, .publish-form textarea { width: 100%; min-height: 48px; padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-control); outline: 0; color: var(--color-ink); background: var(--color-surface); font-weight: 400; }.publish-form textarea { min-height: 156px; resize: vertical; line-height: 1.5; }.publish-form input:focus, .publish-form select:focus, .publish-form textarea:focus { border-color: var(--color-ink); }.trip-summary { display: flex; justify-content: space-between; gap: 16px; padding: 16px 0; border-top: 1px solid var(--color-border-soft); border-bottom: 1px solid var(--color-border-soft); color: var(--color-muted); font-size: 14px; }.trip-summary strong { color: var(--color-ink); }.upload-section { display: grid; gap: 14px; padding-top: 4px; }.upload-section > div:first-child { display: flex; justify-content: space-between; }.upload-section small { color: var(--color-muted); }.upload-trigger { display: flex; min-height: 112px; align-items: center; justify-content: center; gap: 8px; border: 1px dashed var(--color-border-strong); border-radius: var(--radius-card); color: var(--color-muted); background: var(--color-surface-soft); cursor: pointer; }.upload-trigger:hover { border-color: var(--color-primary); color: var(--color-primary); }.upload-trigger input { display: none; }.file-list { display: grid; gap: 8px; }.file-list > div { display: flex; min-height: 42px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 10px 0 12px; border: 1px solid var(--color-border-soft); border-radius: var(--radius-control); color: var(--color-muted); font-size: 13px; }.file-list span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.file-list button { display: grid; width: 32px; height: 32px; flex: none; place-items: center; border: 0; border-radius: var(--radius-pill); color: var(--color-muted); background: transparent; }.file-list button:hover { color: var(--color-primary); background: var(--color-surface-soft); }.publish-button { justify-self: start; min-width: 156px; }@media (max-width: 600px) { .publish-button { width: 100%; }.trip-summary { align-items: flex-start; flex-direction: column; gap: 5px; } }
</style>
