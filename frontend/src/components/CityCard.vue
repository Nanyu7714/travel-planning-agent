<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { MapPin } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  name: string
  imageUrl: string
  attractionCount: number
  href?: string
}>(), {
  href: '',
})

const imageFailed = ref(false)
const cardElement = computed(() => props.href ? RouterLink : 'article')
const cardAttrs = computed(() => props.href ? { to: props.href } : {})

watch(() => props.imageUrl, () => {
  imageFailed.value = false
})
</script>

<template>
  <component
    :is="cardElement"
    v-bind="cardAttrs"
    class="city-card"
    :aria-label="`查看${name}城市详情`"
  >
    <div class="city-card__image">
      <img v-if="imageUrl && !imageFailed" :src="imageUrl" :alt="`${name}城市景观`" @error="imageFailed = true" />
      <div v-else class="city-card__fallback" aria-hidden="true">
        <MapPin :size="22" />
        <span>图片待核验</span>
      </div>
    </div>
    <div class="city-card__meta">
      <h3>{{ name }}</h3>
      <span class="city-card__badge">{{ attractionCount }} 个景点</span>
    </div>
  </component>
</template>

<style scoped>
.city-card {
  display: block;
  width: 100%;
  overflow: hidden;
  color: var(--color-ink);
  background: var(--color-surface);
  border-radius: var(--radius-card);
  text-decoration: none;
  transition: transform 180ms ease, box-shadow 180ms ease;
}

.city-card__image {
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: var(--color-surface-soft);
}

.city-card__image img,
.city-card__fallback {
  display: block;
  width: 100%;
  height: 100%;
}

.city-card__image img {
  object-fit: cover;
}

.city-card__fallback {
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 8px;
  color: var(--color-muted);
  font-size: 11px;
}

.city-card__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 64px;
  padding: 16px;
}

.city-card h3 {
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

.city-card__badge {
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

.city-card:focus-visible {
  outline: 2px solid var(--color-ink);
  outline-offset: 4px;
}

@media (hover: hover) and (pointer: fine) {
  .city-card:hover {
    transform: translateY(-3px);
    box-shadow: var(--shadow-hover);
  }

  .city-card:active {
    transform: translateY(-1px) scale(0.99);
  }
}

@media (prefers-reduced-motion: reduce) {
  .city-card {
    transition: none;
  }

  .city-card:hover {
    transform: none;
  }
}
</style>
