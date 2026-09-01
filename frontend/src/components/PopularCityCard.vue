<script setup lang="ts">
import { ref } from 'vue'
import { MapPin } from 'lucide-vue-next'
import type { City } from '../api'

defineProps<{
  city: City
  attractionCount: number
}>()

const imageFailed = ref(false)
</script>

<template>
  <RouterLink class="popular-city-card" :to="`/cities/${city.slug}`" :aria-label="`查看${city.name}城市详情`">
    <div class="popular-city-card__image">
      <img v-if="city.image_url && !imageFailed" :src="city.image_url" :alt="`${city.name}城市景观`" @error="imageFailed = true" />
      <div v-else class="popular-city-card__fallback" aria-hidden="true">
        <MapPin :size="22" />
        <span>图片待核验</span>
      </div>
    </div>
    <div class="popular-city-card__meta">
      <h3>{{ city.name }}</h3>
      <span class="popular-city-card__badge">{{ attractionCount }} 个景点</span>
    </div>
  </RouterLink>
</template>

<style scoped>
.popular-city-card {
  --airbnb-canvas: #ffffff;
  --airbnb-ink: #222222;
  --airbnb-surface-soft: #f7f7f7;
  --airbnb-muted: #6a6a6a;
  --airbnb-radius-card: 14px;
  --airbnb-radius-pill: 9999px;
  --airbnb-shadow-hover: rgba(0, 0, 0, 0.02) 0 0 0 1px, rgba(0, 0, 0, 0.04) 0 2px 6px 0, rgba(0, 0, 0, 0.1) 0 4px 8px 0;
  display: block;
  width: 100%;
  overflow: hidden;
  color: var(--airbnb-ink);
  background: var(--airbnb-canvas);
  border-radius: var(--airbnb-radius-card);
  text-decoration: none;
  transition: transform 180ms ease, box-shadow 180ms ease;
}

.popular-city-card__image {
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: var(--airbnb-surface-soft);
}

.popular-city-card__image img,
.popular-city-card__fallback {
  display: block;
  width: 100%;
  height: 100%;
}

.popular-city-card__image img {
  object-fit: cover;
}

.popular-city-card__fallback {
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 8px;
  color: var(--airbnb-muted);
  font-size: 11px;
}

.popular-city-card__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 64px;
  padding: 16px;
}

.popular-city-card h3 {
  min-width: 0;
  margin: 0;
  color: var(--airbnb-ink);
  font-family: 'Airbnb Cereal VF', Circular, -apple-system, system-ui, Roboto, 'Helvetica Neue', sans-serif;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.25;
  letter-spacing: 0;
  overflow-wrap: anywhere;
}

.popular-city-card__badge {
  flex: none;
  padding: 4px 10px;
  color: var(--airbnb-ink);
  background: var(--airbnb-surface-soft);
  border-radius: var(--airbnb-radius-pill);
  font-family: 'Airbnb Cereal VF', Circular, -apple-system, system-ui, Roboto, 'Helvetica Neue', sans-serif;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.18;
  white-space: nowrap;
}

.popular-city-card:focus-visible {
  outline: 2px solid var(--airbnb-ink);
  outline-offset: 4px;
}

@media (hover: hover) and (pointer: fine) {
  .popular-city-card:hover {
    transform: translateY(-4px);
    box-shadow: var(--airbnb-shadow-hover);
  }
}

@media (prefers-reduced-motion: reduce) {
  .popular-city-card {
    transition: none;
  }

  .popular-city-card:hover {
    transform: none;
  }
}
</style>
