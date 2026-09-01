<script setup lang="ts">
import { ArrowLeft, MapPinned } from 'lucide-vue-next'
import type { City } from '../api'
import CityCard from '../components/CityCard.vue'

type MockCity = City & { attractionCount: number }

const mockCities: MockCity[] = [
  {
    id: 101,
    slug: 'beijing',
    name: '北京',
    description: '古都人文与现代城市交织。',
    season: '春秋最佳',
    budget: '¥300-600/天',
    recommended_days: '3-5天',
    image_url: 'https://images.unsplash.com/photo-1508804185872-d7badad00f7d?auto=format&fit=crop&w=900&q=80',
    support_level: 'full',
    planning_enabled: true,
    attractionCount: 18,
  },
  {
    id: 102,
    slug: 'shanghai',
    name: '上海',
    description: '沿江风景、建筑、人文展览和夜间生活。',
    season: '春秋舒适',
    budget: '¥400-800/天',
    recommended_days: '2-4天',
    image_url: 'https://images.unsplash.com/photo-1538428494232-9c0d8a3ab403?auto=format&fit=crop&w=900&q=80',
    support_level: 'full',
    planning_enabled: true,
    attractionCount: 22,
  },
  {
    id: 103,
    slug: 'chengdu',
    name: '成都',
    description: '美食、茶馆、街巷和自然风光。',
    season: '春秋宜人',
    budget: '¥300-600/天',
    recommended_days: '3-5天',
    image_url: 'https://images.unsplash.com/photo-1548919973-5cef591cdbc9?auto=format&fit=crop&w=900&q=80',
    support_level: 'full',
    planning_enabled: true,
    attractionCount: 16,
  },
  {
    id: 104,
    slug: 'tokyo',
    name: '东京',
    description: '高密度街区、当代文化和城市美食。',
    season: '春秋最佳',
    budget: '¥700-1200/天',
    recommended_days: '4-6天',
    image_url: 'https://images.unsplash.com/photo-1540959733332-eab4deabeeaf?auto=format&fit=crop&w=900&q=80',
    support_level: 'preview',
    planning_enabled: false,
    attractionCount: 25,
  },
  {
    id: 105,
    slug: 'kyoto',
    name: '京都',
    description: '寺院、庭园与慢节奏的古城漫游。',
    season: '春秋最佳',
    budget: '¥600-1000/天',
    recommended_days: '3-4天',
    image_url: 'https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?auto=format&fit=crop&w=900&q=80',
    support_level: 'preview',
    planning_enabled: false,
    attractionCount: 14,
  },
  {
    id: 106,
    slug: 'seoul',
    name: '首尔',
    description: '传统街区、流行文化与咖啡店漫游。',
    season: '春秋舒适',
    budget: '¥500-900/天',
    recommended_days: '3-5天',
    image_url: 'https://images.unsplash.com/photo-1538485399081-7c8975b23f02?auto=format&fit=crop&w=900&q=80',
    support_level: 'preview',
    planning_enabled: false,
    attractionCount: 19,
  },
  {
    id: 107,
    slug: 'paris',
    name: '巴黎',
    description: '艺术、建筑和街角生活组成的城市漫步。',
    season: '春夏秋皆宜',
    budget: '¥1000-1800/天',
    recommended_days: '4-6天',
    image_url: 'https://images.unsplash.com/photo-1502602898657-3e91760cbb34?auto=format&fit=crop&w=900&q=80',
    support_level: 'preview',
    planning_enabled: false,
    attractionCount: 21,
  },
  {
    id: 108,
    slug: 'lisbon',
    name: '里斯本',
    description: '彩色街巷、海风和适合慢慢探索的坡城。',
    season: '春夏秋皆宜',
    budget: '¥700-1200/天',
    recommended_days: '3-5天',
    image_url: 'https://images.unsplash.com/photo-1555881400-74d7acaacd8b?auto=format&fit=crop&w=900&q=80',
    support_level: 'preview',
    planning_enabled: false,
    attractionCount: 13,
  },
  {
    id: 109,
    slug: 'singapore',
    name: '新加坡',
    description: '热带城市、滨海景观和多元饮食文化。',
    season: '全年适宜',
    budget: '¥800-1400/天',
    recommended_days: '3-4天',
    image_url: 'https://images.unsplash.com/photo-1525625293386-3f8f99389edd?auto=format&fit=crop&w=900&q=80',
    support_level: 'preview',
    planning_enabled: false,
    attractionCount: 17,
  },
]
</script>

<template>
  <div class="page-container city-list-page">
    <RouterLink class="back-link" to="/"><ArrowLeft :size="16" />返回发现</RouterLink>
    <header class="city-list-header">
      <div>
        <span class="eyebrow">DESTINATIONS</span>
        <h1>城市灵感</h1>
        <p>从熟悉的目的地开始，寻找下一段值得走走的路线。</p>
      </div>
      <div class="city-list-count"><MapPinned :size="18" /><strong>{{ mockCities.length }}</strong><span>个城市</span></div>
    </header>

    <TransitionGroup name="city-list" tag="section" class="city-list-grid" aria-label="城市列表" appear>
      <CityCard v-for="city in mockCities" :key="city.id" :name="city.name" :image-url="city.image_url" :attraction-count="city.attractionCount" :href="`/cities/${city.slug}`" />
    </TransitionGroup>
  </div>
</template>

<style scoped>
.city-list-page {
  max-width: 1200px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--primary);
  font-size: 13px;
  margin-bottom: 26px;
}

.city-list-header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 28px;
  border-bottom: 1px solid var(--border);
}

.city-list-header h1 {
  margin-bottom: 10px;
}

.city-list-header p {
  margin-bottom: 0;
}

.city-list-count {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: none;
  color: var(--secondary);
  font-size: 13px;
}

.city-list-count svg {
  color: var(--primary);
}

.city-list-count strong {
  color: var(--text);
  font-size: 22px;
  font-weight: 600;
}

.city-list-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  padding-top: 32px;
}

.city-list-enter-active {
  transition: opacity 360ms ease, transform 360ms ease;
}

.city-list-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

@media (max-width: 1023px) {
  .city-list-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .city-list-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .city-list-grid {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .city-list-enter-active {
    transition: none;
  }

  .city-list-enter-from {
    opacity: 1;
    transform: none;
  }
}
</style>
