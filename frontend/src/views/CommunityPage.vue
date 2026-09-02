<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Bookmark, CalendarDays, Heart, ImageOff, MapPin, MessageCircle, Plus, Search, Wallet } from 'lucide-vue-next'
import { getCities, getCommunityPosts, getMyCommunityPosts, type City, type CommunityPost } from '../api'
import { useRoute } from 'vue-router'

const route = useRoute()
const posts = ref<CommunityPost[]>([])
const cities = ref<City[]>([])
const city = ref('')
const loading = ref(true)
const error = ref('')
const mine = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    if (mine.value) posts.value = await getMyCommunityPosts()
    else {
      const [result, cityList] = await Promise.all([getCommunityPosts(city.value), getCities()])
      posts.value = result.items
      cities.value = cityList
    }
  } catch (exception) {
    error.value = exception instanceof Error ? exception.message : '社区内容加载失败'
  } finally { loading.value = false }
}

function changeMode(value: boolean) { mine.value = value; void load() }
function cover(post: CommunityPost) { return post.images[0]?.url || '' }
onMounted(() => { mine.value = route.query.mine === '1'; void load() })
</script>

<template>
  <div class="page-container community-page">
    <header class="community-header">
      <div><span class="eyebrow">TRAVEL STORIES</span><h1>旅行灵感</h1><p>看看别人怎样把一座城市走成自己的故事。</p></div>
      <RouterLink class="primary-button" to="/community/publish"><Plus :size="17" />发布行程</RouterLink>
    </header>

    <section class="community-tools" aria-label="社区筛选">
      <div class="mode-tabs" role="tablist" aria-label="社区内容范围">
        <button :class="{ active: !mine }" role="tab" :aria-selected="!mine" @click="changeMode(false)">最新发布</button>
        <button :class="{ active: mine }" role="tab" :aria-selected="mine" @click="changeMode(true)">我的发布</button>
      </div>
      <label v-if="!mine" class="city-filter"><Search :size="16" /><span class="sr-only">筛选城市</span><select v-model="city" @change="load"><option value="">全部城市</option><option v-for="item in cities" :key="item.id" :value="item.name">{{ item.name }}</option></select></label>
    </section>

    <div v-if="loading" class="loading-state">正在整理旅行故事...</div>
    <div v-else-if="error" class="empty-state"><MapPin :size="28" /><h2>{{ error }}</h2><RouterLink class="secondary-button" to="/">去登录</RouterLink></div>
    <div v-else-if="!posts.length" class="empty-state"><ImageOff :size="30" /><h2>{{ mine ? '还没有发布行程' : '还没有公开的行程' }}</h2><RouterLink v-if="mine" class="primary-button" to="/community/publish">发布第一份行程</RouterLink></div>
    <section v-else class="post-grid" aria-label="社区行程列表">
      <RouterLink v-for="post in posts" :key="post.id" class="post-card" :to="`/community/posts/${post.id}`">
        <div class="post-card__image">
          <img v-if="cover(post)" :src="cover(post)" :alt="post.images[0]?.alt_text || `${post.city_name}旅行照片`" />
          <div v-else class="post-card__fallback"><MapPin :size="28" /></div>
          <span v-if="post.status === 'hidden'" class="post-card__status">已撤回</span>
          <span class="post-card__city">{{ post.city_name }}</span>
        </div>
        <div class="post-card__copy">
          <h2>{{ post.title }}</h2><p class="post-card__author">{{ post.author.name }}</p>
          <div class="post-card__facts"><span><CalendarDays :size="14" />{{ post.itinerary.days }} 天</span><span><Wallet :size="14" />¥{{ post.itinerary.budget_total }}</span></div>
          <div class="post-card__engagement"><span><Heart :size="15" :fill="post.liked ? 'currentColor' : 'none'" />{{ post.like_count }}</span><span><Bookmark :size="15" :fill="post.favorited ? 'currentColor' : 'none'" />{{ post.favorite_count }}</span><span><MessageCircle :size="15" />{{ post.comment_count }}</span></div>
        </div>
      </RouterLink>
    </section>
  </div>
</template>

<style scoped>
.community-page { max-width: 1280px; }
.community-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding-bottom: 28px; border-bottom: 1px solid var(--color-border-soft); }
.community-header h1 { margin: 0 0 10px; color: var(--color-ink); font-size: 28px; }
.community-header p { margin: 0; color: var(--color-muted); }
.community-tools { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 24px 0; }
.mode-tabs { display: flex; gap: 4px; }
.mode-tabs button { min-height: 40px; padding: 0 14px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--color-muted); font-size: 14px; font-weight: 600; }
.mode-tabs button.active { border-bottom-color: var(--color-ink); color: var(--color-ink); }
.city-filter { display: flex; min-width: 178px; align-items: center; gap: 8px; padding: 0 12px; border: 1px solid var(--color-border); border-radius: var(--radius-pill); color: var(--color-muted); background: var(--color-surface); }
.city-filter select { width: 100%; min-height: 40px; border: 0; outline: 0; color: var(--color-ink); background: transparent; }
.post-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px 16px; }
.post-card { min-width: 0; overflow: hidden; border: 1px solid var(--color-border-soft); border-radius: var(--radius-card); color: var(--color-ink); background: var(--color-surface); transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease; }
.post-card__image { position: relative; aspect-ratio: 4 / 3; overflow: hidden; background: var(--color-surface-soft); }
.post-card__image img { width: 100%; height: 100%; display: block; object-fit: cover; transition: transform 280ms ease; }
.post-card__fallback { display: grid; width: 100%; height: 100%; place-items: center; color: var(--color-muted); }
.post-card__city, .post-card__status { position: absolute; top: 12px; padding: 5px 10px; border-radius: var(--radius-pill); background: rgba(255, 255, 255, .94); color: var(--color-ink); font-size: 12px; font-weight: 600; }
.post-card__city { left: 12px; }.post-card__status { right: 12px; color: var(--color-primary); }
.post-card__copy { padding: 16px; }.post-card__copy h2 { overflow: hidden; margin: 0; color: var(--color-ink); font-size: 16px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.post-card__author { margin: 7px 0 14px; color: var(--color-muted); font-size: 13px; }
.post-card__facts, .post-card__engagement { display: flex; flex-wrap: wrap; gap: 12px; color: var(--color-muted); font-size: 12px; }
.post-card__facts { padding-bottom: 14px; border-bottom: 1px solid var(--color-border-soft); }.post-card__facts span, .post-card__engagement span { display: inline-flex; align-items: center; gap: 5px; }
.post-card__engagement { padding-top: 13px; }.post-card__engagement span:first-child { color: var(--color-primary); }
@media (hover: hover) and (pointer: fine) { .post-card:hover { border-color: var(--color-border); transform: translateY(-3px); box-shadow: var(--shadow-hover); }.post-card:hover img { transform: scale(1.04); } }
@media (max-width: 900px) { .post-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .community-header { align-items: flex-start; flex-direction: column; }.community-header .primary-button { width: 100%; }.community-tools { align-items: stretch; flex-direction: column; }.mode-tabs { display: grid; grid-template-columns: 1fr 1fr; }.city-filter { min-width: 0; }.post-grid { grid-template-columns: 1fr; } }
</style>
