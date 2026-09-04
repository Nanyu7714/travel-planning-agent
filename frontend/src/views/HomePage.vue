<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, CalendarDays, ChevronLeft, ChevronRight, Compass, MapPin, Search, Sparkles, TrendingUp } from 'lucide-vue-next'
import { getAttractions, getCities, getRankings, searchAttractions, searchCities, type Attraction, type City, type Ranking } from '../api'
import PopularCityCard from '../components/PopularCityCard.vue'

const router = useRouter()
const cities = ref<City[]>([])
const attractions = ref<Attraction[]>([])
const rankings = ref<Ranking[]>([])
const cityRankings = ref<Ranking[]>([])
const attractionCounts = ref<Record<number, number>>({})
const selectedCity = ref<City | null>(null)
const loading = ref(true)
const loadError = ref('')
const searchQuery = ref('')
const searchedCities = ref<City[]>([])
const searchedAttractions = ref<Attraction[]>([])
const searchMenuOpen = ref(false)
const searchPending = ref(false)
const heroImageIndex = ref(0)
const failedHeroImageUrls = ref<string[]>([])
const localHeroImages = [
  { id: 'beijing', name: '北京', imageUrl: '/hero/beijing.jpeg' },
  { id: 'chengdu', name: '成都', imageUrl: '/hero/chengdu.jpg' },
  { id: 'guangzhou', name: '广州', imageUrl: '/hero/guangzhou.jpeg' },
  { id: 'nanjing', name: '南京', imageUrl: '/hero/nanjing.jpeg' },
  { id: 'shanghai', name: '上海', imageUrl: '/hero/shanghai.jpg' },
  { id: 'changsha', name: '长沙', imageUrl: '/hero/changsha.jpg' },
]
const heroImages = computed(() => localHeroImages.filter((image) => !failedHeroImageUrls.value.includes(image.imageUrl)))
const activeHeroImage = computed(() => heroImages.value[heroImageIndex.value] || null)
const featuredAttractions = computed(() => attractions.value.slice(0, 4))
const topRankings = computed(() => rankings.value.slice(0, 5))
const rankingScoreMax = computed(() => Math.max(...topRankings.value.map((item) => item.score), 1))
type PopularCity = { city: City; rank: number }
const popularCities = computed<PopularCity[]>(() => {
  const cityByName = new Map(cities.value.map((city) => [city.name, city]))
  const rankedCities = cityRankings.value
    .map((ranking) => {
      const city = cityByName.get(ranking.name)
      return city ? { city, rank: ranking.rank } : null
    })
    .filter((item): item is PopularCity => item !== null)

  return (rankedCities.length ? rankedCities : cities.value.map((city, index) => ({ city, rank: index + 1 }))).slice(0, 5)
})

const popularRail = ref<HTMLElement | null>(null)
const canScrollPopularPrev = ref(false)
const canScrollPopularNext = ref(false)
const popularRailProgress = ref(0)
const isPopularRailDragging = ref(false)
let activePointerId: number | null = null
let dragStartX = 0
let dragStartScrollLeft = 0
let shouldSuppressRailClick = false
let searchTimer: number | undefined
let searchRequestId = 0

function updatePopularRailState() {
  const rail = popularRail.value
  if (!rail) return
  const maxScroll = rail.scrollWidth - rail.clientWidth
  popularRailProgress.value = maxScroll > 0 ? rail.scrollLeft / maxScroll : 0
  canScrollPopularPrev.value = rail.scrollLeft > 1
  canScrollPopularNext.value = rail.scrollLeft < maxScroll - 1
}

function scrollPopularCities(direction: 1 | -1) {
  const rail = popularRail.value
  if (!rail) return
  rail.scrollBy({ left: Math.round(rail.clientWidth * 0.84) * direction, behavior: 'smooth' })
}

function startPopularRailDrag(event: PointerEvent) {
  if (event.pointerType !== 'mouse' || event.button !== 0 || !popularRail.value) return
  activePointerId = event.pointerId
  dragStartX = event.clientX
  dragStartScrollLeft = popularRail.value.scrollLeft
  shouldSuppressRailClick = false
  popularRail.value.setPointerCapture(event.pointerId)
}

function dragPopularRail(event: PointerEvent) {
  const rail = popularRail.value
  if (!rail || activePointerId !== event.pointerId) return
  const distance = event.clientX - dragStartX
  if (Math.abs(distance) > 4) isPopularRailDragging.value = true
  if (!isPopularRailDragging.value) return
  rail.scrollLeft = dragStartScrollLeft - distance
  updatePopularRailState()
  event.preventDefault()
}

function endPopularRailDrag(event: PointerEvent) {
  const rail = popularRail.value
  if (!rail || activePointerId !== event.pointerId) return
  if (rail.hasPointerCapture(event.pointerId)) rail.releasePointerCapture(event.pointerId)
  shouldSuppressRailClick = isPopularRailDragging.value
  activePointerId = null
  isPopularRailDragging.value = false
  window.setTimeout(() => { shouldSuppressRailClick = false }, 120)
}

function suppressPopularRailClick(event: MouseEvent) {
  if (!shouldSuppressRailClick) return
  event.preventDefault()
  event.stopPropagation()
}
async function loadAttractionCounts(cityList: City[]) {
  const entries = await Promise.all(cityList.map(async (city) => {
    try {
      const cityAttractions = await getAttractions(city.id)
      return [city.id, cityAttractions.length] as const
    } catch {
      return [city.id, 0] as const
    }
  }))
  attractionCounts.value = Object.fromEntries(entries)
}
function resetSearchResults() {
  searchedCities.value = []
  searchedAttractions.value = []
  searchPending.value = false
}
function closeSearch() {
  searchMenuOpen.value = false
}
async function lookupSearch(query = searchQuery.value.trim()) {
  if (!query) {
    resetSearchResults()
    return
  }
  const requestId = ++searchRequestId
  searchPending.value = true
  const [cityResult, attractionResult] = await Promise.allSettled([searchCities(query), searchAttractions(query)])
  if (requestId !== searchRequestId) return
  searchedCities.value = cityResult.status === 'fulfilled' ? cityResult.value.slice(0, 5) : []
  searchedAttractions.value = attractionResult.status === 'fulfilled' ? attractionResult.value.slice(0, 5) : []
  searchPending.value = false
}
function handleSearchInput() {
  searchMenuOpen.value = true
  if (searchTimer) window.clearTimeout(searchTimer)
  const query = searchQuery.value.trim()
  if (!query) {
    resetSearchResults()
    return
  }
  searchTimer = window.setTimeout(() => { void lookupSearch(query) }, 220)
}
function openSearch() {
  if (searchQuery.value.trim()) {
    searchMenuOpen.value = true
    if (!searchedCities.value.length && !searchedAttractions.value.length) void lookupSearch()
  }
}
function goToCity(city: City) {
  closeSearch()
  void router.push(`/cities/${city.slug}`)
}
function goToAttraction(attraction: Attraction) {
  closeSearch()
  void router.push(`/attractions/${attraction.id}`)
}
async function search() {
  const query = searchQuery.value.trim()
  if (!query) return
  if (searchTimer) window.clearTimeout(searchTimer)
  await lookupSearch(query)
  const exactCity = searchedCities.value.find((city) => city.name === query || city.slug.toLowerCase() === query.toLowerCase())
  const exactAttraction = searchedAttractions.value.find((attraction) => attraction.name === query)
  if (exactCity || searchedCities.value[0]) goToCity(exactCity || searchedCities.value[0])
  else if (exactAttraction || searchedAttractions.value[0]) goToAttraction(exactAttraction || searchedAttractions.value[0])
  else searchMenuOpen.value = true
}
onMounted(async () => {
  preloadHeroImages()
  try {
    const cityList = await getCities()
    cities.value = cityList
    const [attractionRankingResult, cityRankingResult] = await Promise.allSettled([getRankings('attraction'), getRankings('city')])
    if (attractionRankingResult.status === 'fulfilled') rankings.value = attractionRankingResult.value
    if (cityRankingResult.status === 'fulfilled') cityRankings.value = cityRankingResult.value
    await loadAttractionCounts(cityList)
    if (cities.value[0]) await selectCity(cities.value[0])
  } catch {
    loadError.value = '城市内容暂时无法加载，请确认本地后端服务已启动。'
  } finally {
    loading.value = false
    await nextTick()
    updatePopularRailState()
    window.addEventListener('resize', updatePopularRailState)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updatePopularRailState)
  if (searchTimer) window.clearTimeout(searchTimer)
})

watch(heroImages, (images) => {
  if (heroImageIndex.value >= images.length) heroImageIndex.value = 0
})
async function selectCity(city: City) {
  if (selectedCity.value?.id === city.id) return
  selectedCity.value = city
  const cityAttractions = await getAttractions(city.id)
  if (selectedCity.value?.id !== city.id) return
  attractions.value = cityAttractions
}
function cityName(cityId?: number) {
  return cities.value.find((city) => city.id === cityId)?.name || ''
}
function rankingBarWidth(score: number) {
  return `${Math.max(8, Math.round((score / rankingScoreMax.value) * 100))}%`
}
function preloadHeroImages() {
  heroImages.value.forEach(({ imageUrl }) => {
    const image = new Image()
    image.src = imageUrl
  })
}
function changeHeroImage(event: PointerEvent) {
  if (event.pointerType !== 'mouse' || heroImages.value.length < 2) return
  const bounds = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const ratio = Math.min(0.9999, Math.max(0, (event.clientX - bounds.left) / bounds.width))
  const nextIndex = Math.floor(ratio * heroImages.value.length)
  if (nextIndex !== heroImageIndex.value) heroImageIndex.value = nextIndex
}
function handleHeroImageError(imageUrl: string) {
  if (!failedHeroImageUrls.value.includes(imageUrl)) failedHeroImageUrls.value = [...failedHeroImageUrls.value, imageUrl]
}
</script>

<template>
  <div v-if="loading" class="page-container loading-state">正在整理城市灵感...</div>
  <div v-else-if="loadError" class="page-container empty-state"><h1>内容暂时无法加载</h1><p>{{ loadError }}</p></div>
  <div v-else class="page-container home-page">
    <section class="home-hero" aria-labelledby="home-title" @pointermove="changeHeroImage">
      <Transition name="hero-image-blur">
        <img v-if="activeHeroImage" :key="activeHeroImage.id" class="home-hero__image" :src="activeHeroImage.imageUrl" :alt="`${activeHeroImage.name}城市景观`" @error="handleHeroImageError(activeHeroImage.imageUrl)" />
        <div v-else class="home-hero__fallback" aria-hidden="true"><MapPin :size="28" /></div>
      </Transition>
      <div class="home-hero__scrim" aria-hidden="true"></div>
      <div class="home-hero__content">
        <span class="home-hero__eyebrow">TRAVEL, BETTER PLANNED</span>
        <h1 id="home-title">下一站，去值得走一走的地方。</h1>
        <p>从一座城市开始，把想去的地方变成走得通、玩得好的行程。</p>
        <div class="home-search-area">
          <form class="home-search" @submit.prevent="search">
            <Search :size="18" aria-hidden="true" />
            <input v-model="searchQuery" placeholder="搜索城市或景点" aria-label="搜索城市或景点" @input="handleSearchInput" @focus="openSearch" @keydown.esc.prevent="closeSearch" />
            <button type="submit" aria-label="搜索城市或景点" title="搜索"><Search :size="17" /></button>
          </form>
          <div v-if="searchMenuOpen && searchQuery.trim()" class="home-search-results" role="listbox" aria-label="搜索结果">
            <div v-if="searchPending" class="home-search-results__status">正在搜索...</div>
            <template v-else-if="searchedCities.length || searchedAttractions.length">
              <button v-for="city in searchedCities" :key="`city-${city.id}`" type="button" class="home-search-result" role="option" @click="goToCity(city)">
                <MapPin :size="17" aria-hidden="true" />
                <span><strong>{{ city.name }}</strong><small>城市 · {{ city.season }}</small></span>
                <ArrowRight :size="16" aria-hidden="true" />
              </button>
              <button v-for="attraction in searchedAttractions" :key="`attraction-${attraction.id}`" type="button" class="home-search-result" role="option" @click="goToAttraction(attraction)">
                <Compass :size="17" aria-hidden="true" />
                <span><strong>{{ attraction.name }}</strong><small>景点 · {{ attraction.area }}</small></span>
                <ArrowRight :size="16" aria-hidden="true" />
              </button>
            </template>
            <div v-else class="home-search-results__status">没有找到相关城市或景点</div>
          </div>
        </div>
      </div>
    </section>

    <section class="planning-entry" aria-label="开始旅行规划">
      <div class="planning-entry__icon" aria-hidden="true"><Sparkles :size="21" /></div>
      <div class="planning-entry__copy">
        <span class="eyebrow">READY WHEN YOU ARE</span>
        <h2>{{ selectedCity ? `从${selectedCity.name}开始，做一份自己的行程。` : '有了目的地，下一步交给行旅。' }}</h2>
        <p>告诉我你的时间、预算和偏好，我会帮你把想去的地方安排得更顺路。</p>
      </div>
      <RouterLink class="primary-button" :to="{ path: '/planner', query: selectedCity ? { city: selectedCity.slug } : {} }">开始规划 <ArrowRight :size="17" /></RouterLink>
    </section>

    <section class="home-section" aria-labelledby="popular-cities-title">
      <div class="section-heading">
        <div>
          <span class="eyebrow">DESTINATIONS</span>
          <h2 id="popular-cities-title">热门城市推荐</h2>
        </div>
        <div class="section-heading__action">
          <span class="section-count">TOP {{ popularCities.length }}</span>
          <RouterLink class="underlined-link" to="/cities">查看全部 <ArrowRight :size="15" /></RouterLink>
        </div>
      </div>
      <div v-if="!popularCities.length" class="small-empty">没有找到匹配的城市</div>
      <div v-else class="popular-city-carousel">
        <div v-if="canScrollPopularPrev || canScrollPopularNext" class="popular-city-carousel__controls" aria-label="热门城市轮播控制">
          <button type="button" title="上一组城市" aria-label="上一组城市" :disabled="!canScrollPopularPrev" @click="scrollPopularCities(-1)">
            <ChevronLeft :size="18" />
          </button>
          <button type="button" title="下一组城市" aria-label="下一组城市" :disabled="!canScrollPopularNext" @click="scrollPopularCities(1)">
            <ChevronRight :size="18" />
          </button>
        </div>
        <div
          ref="popularRail"
          :class="['popular-city-carousel__rail', { 'is-dragging': isPopularRailDragging }]"
          @click.capture="suppressPopularRailClick"
          @pointerdown="startPopularRailDrag"
          @pointermove="dragPopularRail"
          @pointerup="endPopularRailDrag"
          @pointercancel="endPopularRailDrag"
          @scroll.passive="updatePopularRailState"
        >
          <PopularCityCard
            v-for="({ city, rank }, index) in popularCities"
            :key="city.id"
            :city="city"
            :rank="rank"
            :active="selectedCity?.id === city.id"
            :style="{ '--city-index': index }"
            :attraction-count="attractionCounts[city.id] ?? 0"
            @click="selectCity(city)"
            @mouseenter="selectCity(city)"
            @focus="selectCity(city)"
          />
        </div>
        <div v-if="canScrollPopularPrev || canScrollPopularNext" class="popular-city-carousel__progress" aria-hidden="true">
          <span :style="{ transform: `scaleX(${Math.max(popularRailProgress, 0.1)})` }"></span>
        </div>
      </div>
    </section>

    <section class="discovery-layout" aria-label="城市探索内容">
      <section class="home-section destination-explorer" aria-labelledby="explore-title">
        <div class="section-heading destination-explorer__heading">
          <div>
            <span class="eyebrow">{{ selectedCity?.name || 'DESTINATION' }} · EXPLORE</span>
            <h2 id="explore-title">把这一站排进你的旅程</h2>
          </div>
          <RouterLink v-if="selectedCity" class="underlined-link" :to="`/cities/${selectedCity.slug}`">查看城市指南 <ArrowRight :size="15" /></RouterLink>
        </div>

        <div v-if="selectedCity" class="destination-summary">
          <p>{{ selectedCity.description }}</p>
          <div class="destination-facts" aria-label="城市出行信息">
            <span><CalendarDays :size="15" />{{ selectedCity.recommended_days }}</span>
            <span>{{ selectedCity.season }}</span>
            <span>{{ selectedCity.budget }}</span>
          </div>
        </div>

        <div v-if="featuredAttractions.length" class="attraction-showcase">
          <RouterLink v-for="item in featuredAttractions" :key="item.id" class="attraction-tile" :to="`/attractions/${item.id}`">
            <div class="attraction-tile__image">
              <img v-if="item.image_url" :src="item.image_url" :alt="`${item.name}图片`" />
              <div v-else class="attraction-tile__fallback" aria-hidden="true"><MapPin :size="22" /></div>
              <span v-if="item.tags[0]" class="attraction-tile__tag">{{ item.tags[0] }}</span>
            </div>
            <div class="attraction-tile__copy">
              <h3>{{ item.name }}</h3>
              <p>{{ item.description }}</p>
              <div class="attraction-tile__meta"><span>{{ item.opening_hours }}</span><b>{{ item.ticket_price ? `¥${item.ticket_price}` : '免费' }}</b></div>
            </div>
          </RouterLink>
        </div>
        <div v-else class="destination-empty">
          <Compass :size="22" aria-hidden="true" />
          <div><strong>{{ selectedCity?.name || '这座城市' }}的景点正在整理</strong><p>先浏览城市指南，稍后回来查看路线灵感。</p></div>
        </div>
      </section>

      <aside class="home-section trend-panel" aria-labelledby="ranking-title">
        <div class="section-heading trend-panel__heading">
          <div>
            <span class="eyebrow">CURRENT DATA</span>
            <h2 id="ranking-title">大家都在关注</h2>
          </div>
          <TrendingUp :size="20" class="accent-icon" aria-hidden="true" />
        </div>
        <div v-if="topRankings.length" class="trend-list">
          <RouterLink v-for="item in topRankings" :key="item.attraction_id" class="trend-item" :to="item.attraction_id ? `/attractions/${item.attraction_id}` : '/rankings'">
            <span class="trend-item__rank">{{ String(item.rank).padStart(2, '0') }}</span>
            <span class="trend-item__body"><strong>{{ item.name }}</strong><small>{{ cityName(item.city_id) || '热门目的地' }}</small><i><b :style="{ width: rankingBarWidth(item.score) }"></b></i></span>
            <span class="trend-item__score">{{ item.score }}</span>
          </RouterLink>
        </div>
        <div v-else class="trend-empty">热度数据正在汇总</div>
        <RouterLink class="underlined-link" to="/rankings">查看完整热度排行 <ArrowRight :size="15" /></RouterLink>
      </aside>
    </section>

  </div>
</template>

<style scoped>
.home-page { padding-top: 32px; }
.home-hero { position: relative; min-height: 360px; overflow: hidden; border-radius: var(--radius-card); isolation: isolate; background: var(--color-surface-strong); }
.home-hero__image, .home-hero__fallback, .home-hero__scrim { position: absolute; inset: 0; width: 100%; height: 100%; }
.home-hero__image { z-index: 0; display: block; object-fit: cover; }
.home-hero__fallback { z-index: 0; display: grid; place-items: center; color: var(--color-muted); background: var(--color-surface-strong); }
.hero-image-blur-enter-active, .hero-image-blur-leave-active { transition: opacity 420ms ease, filter 420ms ease, transform 420ms ease; }
.hero-image-blur-enter-from, .hero-image-blur-leave-to { opacity: 0; filter: blur(14px); transform: scale(1.035); }
.home-hero__scrim { z-index: 1; background: rgba(0, 0, 0, 0.32); }
.home-hero__content { position: relative; z-index: 2; display: flex; min-height: 360px; max-width: 610px; flex-direction: column; justify-content: center; padding: 48px; color: var(--color-on-dark); }
.home-hero__eyebrow { margin-bottom: 12px; color: var(--color-on-dark); font-size: 11px; font-weight: 700; letter-spacing: 1.6px; }
.home-hero h1 { max-width: 540px; margin: 0 0 12px; color: var(--color-on-dark); font-size: 28px; font-weight: 700; line-height: 1.43; }
.home-hero p { max-width: 460px; margin: 0 0 24px; color: rgba(255, 255, 255, 0.92); font-size: 16px; line-height: 1.5; }
.home-search-area { position: relative; width: min(100%, 420px); }
.home-search { display: flex; width: 100%; min-height: 64px; align-items: center; gap: 10px; padding: 8px 8px 8px 20px; border: 1px solid var(--color-border); border-radius: var(--radius-pill); background: var(--color-canvas); color: var(--color-ink); box-shadow: var(--shadow-hover); }
.home-search input { min-width: 0; flex: 1; padding: 8px 0; border: 0; outline: 0; color: var(--color-ink); background: transparent; font-size: 14px; }
.home-search input::placeholder { color: var(--color-muted); }
.home-search button { display: grid; width: 48px; height: 48px; flex: none; place-items: center; border: 0; border-radius: var(--radius-pill); color: var(--color-on-primary); background: var(--color-primary); }
.home-search button:hover { background: var(--color-primary-active); }
.home-search-results { position: absolute; z-index: 4; top: calc(100% + 8px); right: 0; left: 0; overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-card); color: var(--color-ink); background: var(--color-canvas); box-shadow: var(--shadow-hover); }
.home-search-result { display: grid; width: 100%; grid-template-columns: 20px minmax(0, 1fr) 18px; align-items: center; gap: 10px; padding: 12px 16px; border: 0; border-bottom: 1px solid var(--color-border-soft); color: var(--color-ink); background: transparent; text-align: left; }
.home-search-result:last-child { border-bottom: 0; }
.home-search-result:hover, .home-search-result:focus-visible { background: var(--color-surface-soft); outline: 0; }
.home-search-result > span { display: grid; min-width: 0; gap: 2px; }
.home-search-result strong, .home-search-result small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.home-search-result strong { font-size: 14px; line-height: 1.25; }
.home-search-result small, .home-search-results__status { color: var(--color-muted); font-size: 12px; line-height: 1.4; }
.home-search-results__status { padding: 16px; }
.home-section { padding-top: 64px; }
.section-heading__action { display: flex; align-items: center; gap: 20px; }
.section-heading__action .underlined-link { margin-top: 0; }
.popular-city-carousel { position: relative; }
.popular-city-carousel__controls { display: flex; justify-content: flex-end; gap: 8px; margin: 0 0 12px; }
.popular-city-carousel__controls button { display: grid; width: 40px; height: 40px; place-items: center; padding: 0; border: 1px solid var(--color-border); border-radius: var(--radius-pill); color: var(--color-ink); background: var(--color-canvas); transition: background-color 180ms ease, border-color 180ms ease, opacity 180ms ease; }
.popular-city-carousel__controls button:hover:not(:disabled) { border-color: var(--color-ink); background: var(--color-surface-soft); }
.popular-city-carousel__controls button:disabled { cursor: not-allowed; opacity: 0.35; }
.popular-city-carousel__rail { display: flex; gap: 16px; overflow-x: auto; padding: 2px 2px 10px; overscroll-behavior-x: contain; scroll-behavior: smooth; scroll-snap-type: x mandatory; scrollbar-width: none; -webkit-overflow-scrolling: touch; cursor: grab; }
.popular-city-carousel__rail::-webkit-scrollbar { display: none; }
.popular-city-carousel__rail.is-dragging { scroll-behavior: auto; cursor: grabbing; user-select: none; }
.popular-city-carousel__rail :deep(.popular-city-card) { width: clamp(240px, 23.7%, 292px); flex: 0 0 clamp(240px, 23.7%, 292px); scroll-snap-align: start; animation: city-card-enter 360ms ease both; animation-delay: calc(var(--city-index) * 55ms); }
.popular-city-carousel__rail.is-dragging :deep(.popular-city-card) { pointer-events: none; }
.popular-city-carousel__progress { height: 2px; margin-top: 6px; overflow: hidden; border-radius: var(--radius-pill); background: var(--color-border-soft); }
.popular-city-carousel__progress span { display: block; width: 100%; height: 100%; transform-origin: left; border-radius: inherit; background: var(--color-primary); transition: transform 180ms ease; }
@keyframes city-card-enter { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
.discovery-layout { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(272px, 0.72fr); gap: 48px; }
.destination-explorer, .trend-panel { min-width: 0; }
.destination-explorer__heading { align-items: flex-end; }
.destination-explorer__heading .underlined-link { margin: 0; }
.destination-summary { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 0 0 20px; border-bottom: 1px solid var(--color-border-soft); }
.destination-summary > p { max-width: 580px; margin: 0; color: var(--color-body); }
.destination-facts { display: flex; flex: none; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.destination-facts span { display: inline-flex; min-height: 32px; align-items: center; gap: 6px; padding: 6px 10px; border: 1px solid var(--color-border); border-radius: var(--radius-pill); color: var(--color-body); font-size: 12px; line-height: 1.25; }
.attraction-showcase { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; padding-top: 20px; }
.attraction-tile { overflow: hidden; border: 1px solid var(--color-border-soft); border-radius: var(--radius-card); color: var(--color-ink); background: var(--color-canvas); text-decoration: none; transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease; }
.attraction-tile__image { position: relative; aspect-ratio: 4 / 3; overflow: hidden; background: var(--color-surface-soft); }
.attraction-tile__image img, .attraction-tile__fallback { width: 100%; height: 100%; }
.attraction-tile__image img { display: block; object-fit: cover; transition: transform 280ms ease; }
.attraction-tile__fallback { display: grid; place-items: center; color: var(--color-muted); }
.attraction-tile__tag { position: absolute; top: 10px; left: 10px; padding: 4px 9px; border-radius: var(--radius-pill); color: var(--color-ink); background: rgba(255, 255, 255, 0.94); font-size: 11px; font-weight: 600; line-height: 1.18; }
.attraction-tile__copy { padding: 14px 16px 16px; }
.attraction-tile__copy h3 { margin: 0 0 6px; }
.attraction-tile__copy p { display: -webkit-box; min-height: 40px; margin: 0 0 12px; overflow: hidden; color: var(--color-muted); font-size: 13px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.attraction-tile__meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--color-muted); font-size: 12px; }
.attraction-tile__meta span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attraction-tile__meta b { flex: none; color: var(--color-ink); font-size: 13px; font-weight: 600; }
.destination-empty { display: flex; align-items: center; gap: 14px; min-height: 224px; margin-top: 20px; padding: 24px; border: 1px dashed var(--color-border); border-radius: var(--radius-card); color: var(--color-muted); background: var(--color-surface-soft); }
.destination-empty strong { display: block; color: var(--color-ink); font-size: 14px; }
.destination-empty p { margin: 4px 0 0; font-size: 13px; }
.trend-panel { padding-left: 32px; border-left: 1px solid var(--color-border-soft); }
.trend-panel__heading { margin-bottom: 12px; }
.trend-list { border-top: 1px solid var(--color-border-soft); }
.trend-item { display: grid; grid-template-columns: 30px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 14px 0; border-bottom: 1px solid var(--color-border-soft); color: var(--color-ink); text-decoration: none; transition: background-color 180ms ease; }
.trend-item__rank { color: var(--color-muted); font-size: 12px; font-weight: 600; }
.trend-item__body { display: grid; min-width: 0; gap: 3px; }
.trend-item__body strong { overflow: hidden; font-size: 14px; font-weight: 600; line-height: 1.25; text-overflow: ellipsis; white-space: nowrap; }
.trend-item__body small { color: var(--color-muted); font-size: 11px; line-height: 1.2; }
.trend-item__body i { display: block; width: 100%; height: 3px; margin-top: 4px; overflow: hidden; border-radius: var(--radius-pill); background: var(--color-surface-strong); }
.trend-item__body i b { display: block; height: 100%; border-radius: inherit; background: var(--color-primary); }
.trend-item__score { color: var(--color-muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.trend-empty { padding: 24px 0; border-top: 1px solid var(--color-border-soft); border-bottom: 1px solid var(--color-border-soft); color: var(--color-muted); font-size: 14px; }
.trend-panel .underlined-link { width: max-content; }
.planning-entry { display: grid; grid-template-columns: 48px minmax(0, 1fr) auto; align-items: center; gap: 20px; margin-top: 32px; padding: 28px 0; border-top: 1px solid var(--color-border-soft); border-bottom: 1px solid var(--color-border-soft); }
.planning-entry__icon { display: grid; width: 48px; height: 48px; place-items: center; border-radius: var(--radius-pill); color: var(--color-primary); background: var(--color-surface-soft); }
.planning-entry__copy .eyebrow { margin-bottom: 6px; }
.planning-entry h2 { margin: 0 0 6px; }
.planning-entry p { max-width: 620px; margin: 0; }
@media (hover: hover) and (pointer: fine) { .attraction-tile:hover { border-color: var(--color-border); transform: translateY(-3px); box-shadow: var(--shadow-hover); } .attraction-tile:hover .attraction-tile__image img { transform: scale(1.04); } .trend-item:hover { background: var(--color-surface-soft); } }
@media (max-width: 1128px) { .popular-city-carousel__rail :deep(.popular-city-card) { width: clamp(250px, 31.6%, 330px); flex-basis: clamp(250px, 31.6%, 330px); } .discovery-layout { grid-template-columns: minmax(0, 1.45fr) minmax(240px, 0.75fr); gap: 32px; } .trend-panel { padding-left: 24px; } .destination-summary { align-items: flex-start; flex-direction: column; } .destination-facts { justify-content: flex-start; } }
@media (max-width: 744px) { .home-page { padding-top: 16px; } .home-hero, .home-hero__content { min-height: 320px; } .home-hero__content { padding: 28px 24px; } .home-hero h1 { font-size: 24px; } .home-hero p { font-size: 14px; } .home-section { padding-top: 48px; } .section-heading, .section-heading__action { align-items: flex-start; flex-direction: column; gap: 8px; } .destination-explorer__heading .underlined-link { margin-top: 4px; } .popular-city-carousel__controls { display: none; } .popular-city-carousel__rail { margin-right: -24px; padding: 2px 24px 12px 2px; touch-action: pan-x pan-y; scroll-padding-inline: 2px; } .popular-city-carousel__rail :deep(.popular-city-card) { width: min(78vw, 320px); flex-basis: min(78vw, 320px); scroll-snap-stop: always; } .popular-city-carousel__progress { margin-right: 24px; } .discovery-layout { grid-template-columns: 1fr; gap: 0; } .attraction-showcase { grid-template-columns: 1fr; } .trend-panel { padding-left: 0; border-left: 0; } .planning-entry { grid-template-columns: 48px minmax(0, 1fr); align-items: start; margin-top: 48px; } .planning-entry .primary-button { grid-column: 1 / -1; width: 100%; } }
@media (prefers-reduced-motion: reduce) { .popular-city-carousel__rail { scroll-behavior: auto; } .popular-city-carousel__rail :deep(.popular-city-card) { animation: none; } .popular-city-carousel__progress span, .hero-image-blur-enter-active, .hero-image-blur-leave-active { transition: none; } }
</style>
