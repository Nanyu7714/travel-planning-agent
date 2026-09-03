<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CheckCircle2, ImageOff, Images, Pencil, RefreshCw, Save, Search, ShieldCheck, Upload, X } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import { api, getAttractions, getCities, type City, uploadMediaAssetFile } from '../api'

type MediaStatus = 'approved' | 'needs_review' | 'missing' | 'rejected_wrong_city'
type MediaAsset = {
  id: number
  city_id: number
  attraction_id: number | null
  purpose: string
  content_key: string
  storage_type: string
  url: string | null
  storage_path: string | null
  mime_type: string | null
  alt_text: string
  source_name: string | null
  source_author: string | null
  license_name: string | null
  attribution_url: string | null
  verification_status: MediaStatus
  is_active: boolean
}
type MediaEditForm = Pick<MediaAsset, 'storage_type' | 'url' | 'storage_path' | 'alt_text' | 'source_name' | 'source_author' | 'license_name' | 'attribution_url' | 'verification_status' | 'is_active'>

const cities = ref<City[]>([])
const attractionNames = ref<Record<number, string>>({})
const assets = ref<MediaAsset[]>([])
const selectedCityId = ref(0)
const selectedStatus = ref<'all' | MediaStatus>('all')
const search = ref('')
const error = ref('')
const busyId = ref<number | null>(null)
const failedImageIds = ref(new Set<number>())
const editingAsset = ref<MediaAsset | null>(null)
const editForm = ref<MediaEditForm | null>(null)

const statusLabel: Record<MediaStatus, string> = {
  approved: '已核验',
  needs_review: '待核验',
  missing: '缺少图片',
  rejected_wrong_city: '已拒绝',
}

const filteredAssets = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return assets.value.filter((asset) => {
    const matchesCity = !selectedCityId.value || asset.city_id === selectedCityId.value
    const matchesStatus = selectedStatus.value === 'all' || asset.verification_status === selectedStatus.value
    const cityName = cities.value.find((city) => city.id === asset.city_id)?.name || ''
    const attractionName = asset.attraction_id ? attractionNames.value[asset.attraction_id] || '' : ''
    const matchesSearch = !keyword || `${cityName} ${attractionName} ${asset.content_key} ${asset.source_name || ''}`.toLowerCase().includes(keyword)
    return matchesCity && matchesStatus && matchesSearch
  })
})

function replaceAsset(updated: MediaAsset) {
  assets.value = assets.value.map((asset) => asset.id === updated.id ? updated : asset)
  failedImageIds.value = new Set([...failedImageIds.value].filter((id) => id !== updated.id))
}

async function load() {
  error.value = ''
  try {
    const [cityData, assetData] = await Promise.all([getCities(), api<MediaAsset[]>('/admin/media-assets')])
    cities.value = cityData
    assets.value = assetData
    const attractionGroups = await Promise.all(cityData.map(async (city) => getAttractions(city.id)))
    attractionNames.value = Object.fromEntries(attractionGroups.flat().map((attraction) => [attraction.id, attraction.name]))
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '媒体资源加载失败'
  }
}

async function autofill(asset: MediaAsset) {
  busyId.value = asset.id
  try {
    replaceAsset(await api<MediaAsset>(`/admin/media-assets/${asset.id}/autofill`, { method: 'POST', body: '{}' }))
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '未找到可用的候选图片'
  } finally {
    busyId.value = null
  }
}

async function toggleActive(asset: MediaAsset) {
  busyId.value = asset.id
  try {
    replaceAsset(await api<MediaAsset>(`/admin/media-assets/${asset.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !asset.is_active }) }))
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '展示状态更新失败'
  } finally {
    busyId.value = null
  }
}

function openEditor(asset: MediaAsset) {
  editingAsset.value = asset
  editForm.value = {
    storage_type: asset.storage_type,
    url: asset.url,
    storage_path: asset.storage_path,
    alt_text: asset.alt_text,
    source_name: asset.source_name,
    source_author: asset.source_author,
    license_name: asset.license_name,
    attribution_url: asset.attribution_url,
    verification_status: asset.verification_status,
    is_active: asset.is_active,
  }
}

async function saveEditor() {
  if (!editingAsset.value || !editForm.value) return
  busyId.value = editingAsset.value.id
  try {
    replaceAsset(await api<MediaAsset>(`/admin/media-assets/${editingAsset.value.id}`, { method: 'PATCH', body: JSON.stringify(editForm.value) }))
    editingAsset.value = null
    editForm.value = null
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '图片资料保存失败'
  } finally {
    busyId.value = null
  }
}

function targetName(asset: MediaAsset) {
  if (asset.attraction_id) return attractionNames.value[asset.attraction_id] || `景点 #${asset.attraction_id}`
  return '城市封面'
}

function cityName(cityId: number) {
  return cities.value.find((city) => city.id === cityId)?.name || `城市 #${cityId}`
}

function markImageFailed(id: number) {
  failedImageIds.value = new Set([...failedImageIds.value, id])
}

async function uploadFile(asset: MediaAsset, event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busyId.value = asset.id
  error.value = ''
  try {
    replaceAsset(await uploadMediaAssetFile(asset.id, file))
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '图片上传失败'
  } finally {
    busyId.value = null
    input.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container media-assets-page">
    <AdminModuleHeader eyebrow="MEDIA LIBRARY" title="图片管理" description="核对城市和景点图片的来源、授权、核验与展示状态。" />
    <p v-if="error" class="form-error">{{ error }}</p>
    <template v-else>
      <div class="admin-toolbar media-assets-toolbar">
        <div class="admin-toolbar-group">
          <button type="button" :class="['admin-filter-button', { active: selectedCityId === 0 }]" @click="selectedCityId = 0">全部城市</button>
          <button v-for="city in cities" :key="city.id" type="button" :class="['admin-filter-button', { active: selectedCityId === city.id }]" @click="selectedCityId = city.id">{{ city.name }}</button>
        </div>
        <div class="media-assets-toolbar__right">
          <RouterLink class="photos-entry" to="/admin/photos"><Images :size="16" />相片库</RouterLink>
          <select v-model="selectedStatus" aria-label="核验状态筛选">
            <option value="all">全部状态</option>
            <option value="approved">已核验</option>
            <option value="needs_review">待核验</option>
            <option value="missing">缺少图片</option>
            <option value="rejected_wrong_city">已拒绝</option>
          </select>
          <label><span class="sr-only">搜索媒体资源</span><input v-model="search" class="admin-search" placeholder="搜索城市、景点或来源" /></label>
        </div>
      </div>

      <div class="media-assets-list">
        <article v-for="asset in filteredAssets" :key="asset.id" class="media-asset-row">
          <div class="media-asset-preview">
            <img v-if="asset.url && !failedImageIds.has(asset.id)" :src="asset.url" :alt="asset.alt_text" @error="markImageFailed(asset.id)" />
            <ImageOff v-else :size="22" aria-hidden="true" />
          </div>
          <div class="media-asset-main">
            <div class="media-asset-title"><strong>{{ cityName(asset.city_id) }} · {{ targetName(asset) }}</strong><span :class="['admin-status', asset.verification_status === 'rejected_wrong_city' ? 'danger' : asset.verification_status === 'missing' ? 'muted' : '']">{{ statusLabel[asset.verification_status] }}</span></div>
            <p>{{ asset.alt_text }}</p>
            <small>{{ asset.source_name || '尚未登记来源' }}<template v-if="asset.source_author"> · {{ asset.source_author }}</template><template v-if="asset.license_name"> · {{ asset.license_name }}</template></small>
          </div>
          <div class="media-asset-actions">
            <a v-if="asset.attribution_url" :href="asset.attribution_url" target="_blank" rel="noreferrer">来源</a>
            <label v-if="!asset.is_active" class="media-upload" title="上传本地图片（JPEG/PNG/WebP，≤8MB）">
              <Upload :size="16" /><span class="sr-only">上传本地图片</span>
              <input type="file" accept="image/jpeg,image/png,image/webp" :disabled="busyId === asset.id" @change="uploadFile(asset, $event)" />
            </label>
            <button v-if="!asset.is_active" type="button" title="自动查找候选图片" :disabled="busyId === asset.id" @click="autofill(asset)"><RefreshCw :size="16" /></button>
            <button v-else type="button" title="停用展示" :disabled="busyId === asset.id" @click="toggleActive(asset)"><ImageOff :size="16" /></button>
            <button v-if="!asset.is_active && asset.verification_status === 'approved'" type="button" title="启用展示" :disabled="busyId === asset.id" @click="toggleActive(asset)"><CheckCircle2 :size="16" /></button>
            <button type="button" title="编辑图片资料" @click="openEditor(asset)"><Pencil :size="16" /></button>
            <ShieldCheck v-if="asset.is_active" :size="17" class="media-asset-active" aria-label="正在展示" />
          </div>
        </article>
        <div v-if="!filteredAssets.length" class="admin-page-empty"><Search :size="20" /><p>没有匹配的媒体资源</p></div>
      </div>

      <section v-if="editingAsset && editForm" class="media-editor">
        <div class="section-heading"><div><span class="eyebrow">EDIT MEDIA</span><h2>{{ cityName(editingAsset.city_id) }} · {{ targetName(editingAsset) }}</h2></div><button class="icon-button" title="关闭编辑" aria-label="关闭编辑" @click="editingAsset = null; editForm = null"><X :size="18" /></button></div>
        <div class="media-editor__body">
          <div class="media-editor__preview"><img v-if="editForm.url" :src="editForm.url" :alt="editForm.alt_text" /><ImageOff v-else :size="28" /></div>
          <form class="media-editor__form" @submit.prevent="saveEditor">
            <label>图片地址<input v-model.trim="editForm.url" type="url" placeholder="https://..." /></label>
            <label>替代文字<input v-model.trim="editForm.alt_text" /></label>
            <label>来源名称<input v-model.trim="editForm.source_name" placeholder="例如 Wikimedia Commons" /></label>
            <label>作者<input v-model.trim="editForm.source_author" /></label>
            <label>许可证<input v-model.trim="editForm.license_name" /></label>
            <label>原始页面<input v-model.trim="editForm.attribution_url" type="url" /></label>
            <label>核验状态<select v-model="editForm.verification_status"><option value="missing">缺少图片</option><option value="needs_review">待核验</option><option value="approved">已核验</option><option value="rejected_wrong_city">已拒绝</option></select></label>
            <label class="media-editor__toggle"><input v-model="editForm.is_active" type="checkbox" />启用到前台展示</label>
            <button class="primary-button" type="submit" :disabled="busyId === editingAsset.id"><Save :size="16" />保存图片资料</button>
          </form>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.media-assets-toolbar { align-items: flex-start; padding-bottom: 12px; }
.media-assets-toolbar__right { display: flex; flex-wrap: wrap; gap: 8px; }
.photos-entry { display: inline-flex; align-items: center; gap: 6px; min-height: 48px; padding: 0 14px; border: 1px solid var(--color-border); border-radius: var(--radius-control); color: var(--color-ink); font-size: 13px; white-space: nowrap; }
.photos-entry:hover { border-color: var(--color-primary); color: var(--color-primary); }
.media-assets-toolbar select { min-height: 48px; padding: 0 28px 0 12px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-ink); }
.media-assets-list { margin-top: 24px; border-top: 1px solid var(--color-border-soft); }
.media-asset-row { display: grid; grid-template-columns: 120px minmax(0, 1fr) auto; gap: 20px; align-items: center; padding: 16px 0; border-bottom: 1px solid var(--color-border-soft); }
.media-asset-preview { width: 120px; aspect-ratio: 4 / 3; display: grid; place-items: center; overflow: hidden; border-radius: var(--radius-control); background: var(--color-surface-soft); color: var(--color-muted); }
.media-asset-preview img { width: 100%; height: 100%; object-fit: cover; }
.media-asset-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.media-asset-title strong { color: var(--color-ink); font-size: 15px; }
.media-asset-main p { margin: 6px 0; color: var(--color-body); font-size: 13px; }
.media-asset-main small { color: var(--color-muted); font-size: 12px; }
.media-asset-actions { display: flex; align-items: center; gap: 6px; }
.media-asset-actions a, .media-asset-actions button { display: grid; width: 40px; height: 40px; place-items: center; border: 0; border-radius: var(--radius-pill); color: var(--color-muted); background: transparent; font-size: 13px; }
.media-asset-actions a:hover, .media-asset-actions button:hover:not(:disabled) { color: var(--color-primary); background: var(--color-surface-soft); }
.media-asset-actions button:disabled { opacity: 0.45; }
.media-asset-actions .media-upload { display: grid; width: 40px; height: 40px; place-items: center; border-radius: var(--radius-pill); color: var(--color-muted); background: transparent; cursor: pointer; }
.media-asset-actions .media-upload:hover { color: var(--color-primary); background: var(--color-surface-soft); }
.media-asset-actions .media-upload:has(input:disabled) { opacity: 0.45; pointer-events: none; }
.media-upload input { display: none; }
.media-asset-active { margin-left: 6px; color: var(--color-primary); }
.media-editor { max-width: 920px; margin-top: 28px; padding: 24px; border: 1px solid var(--color-border-soft); border-radius: var(--radius-card); background: var(--color-surface); }.media-editor__body { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 24px; margin-top: 20px; }.media-editor__preview { min-height: 210px; display: grid; place-items: center; overflow: hidden; border-radius: var(--radius-card); background: var(--color-surface-soft); color: var(--color-muted); }.media-editor__preview img { width: 100%; height: 100%; object-fit: cover; }.media-editor__form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }.media-editor__form label { display: grid; gap: 6px; color: var(--color-muted); font-size: 12px; }.media-editor__form input, .media-editor__form select { min-width: 0; min-height: 44px; padding: 10px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-ink); }.media-editor__form .media-editor__toggle { display: flex; align-items: center; gap: 8px; grid-column: 1 / -1; color: var(--color-ink); font-size: 14px; }.media-editor__form .media-editor__toggle input { min-height: auto; }.media-editor__form .primary-button { justify-self: end; }
@media (max-width: 744px) { .media-assets-toolbar__right { width: 100%; }.media-assets-toolbar__right .admin-search { min-width: 0; flex: 1; }.media-asset-row { grid-template-columns: 84px minmax(0, 1fr); gap: 12px; }.media-asset-preview { width: 84px; }.media-asset-actions { grid-column: 2; }.media-asset-main p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.media-editor { padding: 18px; border-radius: var(--radius-control); }.media-editor__body { grid-template-columns: 1fr; }.media-editor__preview { min-height: 180px; }.media-editor__form { grid-template-columns: 1fr; }.media-editor__form .primary-button { width: 100%; justify-content: center; } }
</style>
