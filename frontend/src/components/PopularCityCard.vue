<script setup lang="ts">
import { ref } from 'vue'
import { MapPin } from 'lucide-vue-next'
import type { City } from '../api'

defineProps<{
  city: City
  attractionCount: number
  rank?: number
  active?: boolean
}>()

const imageFailed = ref(false)
</script>

<template>
  <button type="button" :class="['popular-city-card', { active }]" :aria-label="`选择${city.name}，查看该城市的路线灵感`" :aria-pressed="active">
    <div class="popular-city-card__image">
      <img v-if="city.image_url && !imageFailed" :src="city.image_url" :alt="`${city.name}城市景观`" :draggable="false" @error="imageFailed = true" />
      <div v-else class="popular-city-card__fallback" aria-hidden="true">
        <MapPin :size="22" />
        <span>图片待核验</span>
      </div>
      <span v-if="rank" class="popular-city-card__rank">TOP {{ String(rank).padStart(2, '0') }}</span>
    </div>
    <div class="popular-city-card__meta">
      <h3>{{ city.name }}</h3>
      <span class="popular-city-card__badge">{{ attractionCount }} 个景点</span>
    </div>
  </button>
</template>

<style scoped>
.popular-city-card {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  overflow: hidden;
  color: var(--color-ink);
  background: var(--color-surface);
  border-radius: var(--radius-card);
  cursor: pointer;
  text-align: left;
  text-decoration: none;
  transition: transform 180ms ease, box-shadow 180ms ease;
}

.popular-city-card.active {
  box-shadow: inset 0 0 0 2px var(--color-primary);
}

.popular-city-card__image {
  position: relative;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: var(--color-surface-soft);
}

.popular-city-card__image img,
.popular-city-card__fallback {
  display: block;
  width: 100%;
  height: 100%;
}

.popular-city-card__image img {
  object-fit: cover;
  transition: transform 280ms ease;
}

.popular-city-card__rank {
  position: absolute;
  top: 12px;
  left: 12px;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  color: var(--color-ink);
  background: var(--color-canvas);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.18;
}

.popular-city-card__fallback {
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 8px;
  color: var(--color-muted);
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
  color: var(--color-ink);
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
  color: var(--color-ink);
  background: var(--color-surface-soft);
  border-radius: var(--radius-pill);
  font-family: 'Airbnb Cereal VF', Circular, -apple-system, system-ui, Roboto, 'Helvetica Neue', sans-serif;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.18;
  white-space: nowrap;
}

.popular-city-card:focus-visible {
  outline: 2px solid var(--color-ink);
  outline-offset: 4px;
}

@media (hover: hover) and (pointer: fine) {
  .popular-city-card:hover {
    transform: translateY(-3px);
    box-shadow: var(--shadow-hover);
  }

  .popular-city-card.active:hover {
    box-shadow: inset 0 0 0 2px var(--color-primary), var(--shadow-hover);
  }

  .popular-city-card:hover .popular-city-card__image img {
    transform: scale(1.04);
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
