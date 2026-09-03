<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Download, ImageOff, ImagePlus, Search, Trash2 } from 'lucide-vue-next'
import AdminModuleHeader from '../components/AdminModuleHeader.vue'
import {
  deleteAdminPhoto,
  fetchAdminPhotos,
  getAdminPhotos,
  getAttractions,
  getCities,
  getPhotoProviders,
  usePhotoAsCover,
  type Attraction,
  type City,
  type MediaAsset,
  type PhotoProviderInfo,
} from '../api'

const cities = ref<City[]>([])
const formAttractions = ref<Attraction[]>([])
const attractionNames = ref<Record<number, string>>({})
const photos = ref<MediaAsset[]>([])
const providers = ref<PhotoProviderInfo | null>(null)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const deletingId = ref<number | null>(null)
const settingId = ref<number | null>(null)
const failedIds = ref(new Set<number>())

const cityId = ref(0)
const attractionId = ref(0)
const keyword = ref('')
const limit = ref(3)
const filterCityId = ref(0)

const filteredPhotos = computed(() => (
  filterCityId.value ? photos.value.filter((photo) => photo.city_id === filterCityId.value) : photos.value
))

function cityName(id: number) {
  return cities.value.find((city) => city.id === id)?.name || `城市 #${id}`
}

function targetName(photo: MediaAsset) {
  if (photo.attraction_id) return attractionNames.value[photo.attraction_id] || `景点 #${photo.attraction_id}`
  return '城市相片'
}

function markFailed(id: number) {
  failedIds.value = new Set([...failedIds.value, id])
}

async function load() {
  error.value = ''
  try {
    const [cityData, photoData] = await Promise.all([getCities(), getAdminPhotos()])
    cities.value = cityData
    photos.value = photoData
    providers.value = await getPhotoProviders().catch(() => null)
    const groups = await Promise.all(cityData.map((city) => getAttractions(city.id).catch(() => [])))
    attractionNames.value = Object.fromEntries(groups.flat().map((item) => [item.id, item.name]))
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '相片加载失败'
  }
}

watch(cityId, async (value) => {
  attractionId.value = 0
  formAttractions.value = value ? await getAttractions(value).catch(() => []) : []
  keyword.value = value ? cityName(value) : ''
})

watch(attractionId, (value) => {
  if (value) {
    const item = formAttractions.value.find((candidate) => candidate.id === value)
    if (item) keyword.value = item.name
  } else if (cityId.value) {
    keyword.value = cityName(cityId.value)
  }
})

async function submit() {
  if (!cityId.value || !keyword.value) {
    error.value = '请先选择城市并填写关键词'
    return
  }
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await fetchAdminPhotos({
      city_id: cityId.value,
      attraction_id: attractionId.value || null,
      keyword: keyword.value,
      limit: limit.value,
      auto_approve: false,
    })
    notice.value = `已抓取 ${result.fetched} 张${result.skipped ? `，跳过重复 ${result.skipped} 张` : ''}`
    await load()
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '抓取失败'
  } finally {
    busy.value = false
  }
}

async function remove(photo: MediaAsset) {
  if (!window.confirm(`确定删除这张相片吗？\n${photo.alt_text}`)) return
  deletingId.value = photo.id
  try {
    await deleteAdminPhoto(photo.id)
    photos.value = photos.value.filter((item) => item.id !== photo.id)
    notice.value = '相片已删除'
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '删除失败'
  } finally {
    deletingId.value = null
  }
}

async function setCover(photo: MediaAsset) {
  settingId.value = photo.id
  error.value = ''
  notice.value = ''
  try {
    await usePhotoAsCover(photo.id)
    notice.value = `已填入${photo.attraction_id ? '景点' : '城市'}封面（待核验），请到图片管理页核验并启用`
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '设为封面失败'
  } finally {
    settingId.value = null
  }
}

onMounted(load)
</script>

<template>
  <div class="page-container photos-page">
    <AdminModuleHeader eyebrow="PHOTO ALBUM" title="相片库" description="按城市或景点自动抓取免费授权图片。抓取的相片只存进相册，不会改变景点封面。" />
    <p v-if="error" class="form-error">{{ error }}</p>
    <template v-else>
      <form class="photo-fetch" @submit.prevent="submit">
        <label>城市
          <select v-model.number="cityId" required>
            <option :value="0" disabled>请选择城市</option>
            <option v-for="city in cities" :key="city.id" :value="city.id">{{ city.name }}</option>
          </select>
        </label>
        <label>景点（可选）
          <select v-model.number="attractionId" :disabled="!cityId">
            <option :value="0">不限（存为城市相片）</option>
            <option v-for="item in formAttractions" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
        </label>
        <label>关键词<small class="keyword-hint">按所选城市/景点自动填入，可手动修改</small>
          <input v-model.trim="keyword" placeholder="例如 西湖、外滩" required />
        </label>
        <label>数量
          <select v-model.number="limit">
            <option :value="1">1 张</option>
            <option :value="3">3 张</option>
            <option :value="5">5 张</option>
            <option :value="8">8 张</option>
          </select>
        </label>
        <button class="primary-button" type="submit" :disabled="busy"><Download :size="16" />{{ busy ? '抓取中…' : '自动抓取' }}</button>
      </form>
      <p v-if="providers" class="photo-providers">可用渠道：{{ providers.providers.join('、') }}<template v-if="providers.download_enabled"> · 图片会下载保存到本地</template></p>
      <p v-if="notice" class="photo-notice">{{ notice }}</p>

      <div class="admin-toolbar photo-toolbar">
        <div class="admin-toolbar-group">
          <button type="button" :class="['admin-filter-button', { active: filterCityId === 0 }]" @click="filterCityId = 0">全部</button>
          <button v-for="city in cities" :key="city.id" type="button" :class="['admin-filter-button', { active: filterCityId === city.id }]" @click="filterCityId = city.id">{{ city.name }}</button>
        </div>
      </div>

      <div v-if="filteredPhotos.length" class="photo-grid">
        <figure v-for="photo in filteredPhotos" :key="photo.id" class="photo-card">
          <div class="photo-card__image">
            <img v-if="photo.url && !failedIds.has(photo.id)" :src="photo.url" :alt="photo.alt_text" loading="lazy" @error="markFailed(photo.id)" />
            <ImageOff v-else :size="24" aria-hidden="true" />
          </div>
          <figcaption>
            <strong>{{ cityName(photo.city_id) }} · {{ targetName(photo) }}</strong>
            <p>{{ photo.alt_text }}</p>
            <small>{{ photo.source_name || '未登记来源' }}<template v-if="photo.license_name"> · {{ photo.license_name }}</template></small>
            <div class="photo-card__actions">
              <a v-if="photo.attribution_url" :href="photo.attribution_url" target="_blank" rel="noreferrer">来源</a>
              <button type="button" :title="photo.attraction_id ? '设为景点封面' : '设为城市封面'" :disabled="settingId === photo.id" @click="setCover(photo)"><ImagePlus :size="15" /></button>
              <button type="button" title="删除相片" :disabled="deletingId === photo.id" @click="remove(photo)"><Trash2 :size="15" /></button>
            </div>
          </figcaption>
        </figure>
      </div>
      <div v-else class="admin-page-empty"><Search :size="20" /><p>还没有相片，选择城市并输入关键词即可自动抓取</p></div>
    </template>
  </div>
</template>

<style scoped>
.photo-fetch { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)) auto; gap: 14px; align-items: end; padding: 18px; border: 1px solid var(--color-border-soft); border-radius: var(--radius-card); background: var(--color-surface); }
.photo-fetch label { display: grid; gap: 6px; color: var(--color-muted); font-size: 12px; }
.photo-fetch .keyword-hint { color: var(--color-muted); font-size: 11px; }
.photo-fetch select, .photo-fetch input { min-height: 44px; padding: 10px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); color: var(--color-ink); }
.photo-fetch .primary-button { min-height: 44px; }
.photo-providers, .photo-notice { margin: 12px 0 0; color: var(--color-muted); font-size: 13px; }
.photo-notice { color: var(--color-primary); }
.photo-toolbar { padding-bottom: 12px; }
.photo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; margin-top: 20px; }
.photo-card { display: flex; flex-direction: column; overflow: hidden; border: 1px solid var(--color-border-soft); border-radius: var(--radius-card); background: var(--color-surface); }
.photo-card__image { aspect-ratio: 4 / 3; display: grid; place-items: center; overflow: hidden; background: var(--color-surface-soft); color: var(--color-muted); }
.photo-card__image img { width: 100%; height: 100%; object-fit: cover; }
.photo-card figcaption { display: grid; gap: 6px; padding: 12px 14px 14px; }
.photo-card figcaption strong { color: var(--color-ink); font-size: 14px; }
.photo-card figcaption p { margin: 0; overflow: hidden; color: var(--color-body); font-size: 13px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.photo-card figcaption small { color: var(--color-muted); font-size: 12px; }
.photo-card__actions { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.photo-card__actions a, .photo-card__actions button { display: grid; width: 32px; height: 32px; place-items: center; border: 0; border-radius: var(--radius-pill); color: var(--color-muted); background: transparent; font-size: 12px; }
.photo-card__actions a:hover, .photo-card__actions button:hover:not(:disabled) { color: var(--color-primary); background: var(--color-surface-soft); }
.photo-card__actions button:disabled { opacity: 0.45; }
@media (max-width: 744px) { .photo-fetch { grid-template-columns: 1fr; } .photo-fetch .primary-button { width: 100%; justify-content: center; } .photo-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; } }
@media (max-width: 520px) { .photo-grid { grid-template-columns: 1fr; } }
</style>
