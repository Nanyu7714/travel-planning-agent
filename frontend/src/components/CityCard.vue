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
const pointerStyle = ref<Record<string, string>>({
  '--card-rotate-x': '0deg',
  '--card-rotate-y': '0deg',
})
const cardElement = computed(() => props.href ? RouterLink : 'article')
const cardAttrs = computed(() => props.href ? { to: props.href } : {})

function handlePointerMove(event: PointerEvent) {
  if (event.pointerType !== 'mouse') return
  const element = event.currentTarget as HTMLElement
  const rect = element.getBoundingClientRect()
  const x = (event.clientX - rect.left) / rect.width - 0.5
  const y = (event.clientY - rect.top) / rect.height - 0.5
  pointerStyle.value = {
    '--card-rotate-x': `${Math.max(-4, Math.min(4, y * -8))}deg`,
    '--card-rotate-y': `${Math.max(-4, Math.min(4, x * 8))}deg`,
  }
}

function resetPointer() {
  pointerStyle.value = {
    '--card-rotate-x': '0deg',
    '--card-rotate-y': '0deg',
  }
}

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
    :style="pointerStyle"
    @pointermove="handlePointerMove"
    @pointerleave="resetPointer"
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
  --airbnb-canvas: #ffffff;
  --airbnb-ink: #222222;
  --airbnb-surface-soft: #f7f7f7;
  --airbnb-muted: #6a6a6a;
  --airbnb-radius-card: 14px;
  --airbnb-radius-pill: 9999px;
  --card-rotate-x: 0deg;
  --card-rotate-y: 0deg;
  --airbnb-shadow-hover: rgba(0, 0, 0, 0.02) 0 0 0 1px, rgba(0, 0, 0, 0.04) 0 2px 6px 0, rgba(0, 0, 0, 0.1) 0 4px 8px 0;
  display: block;
  width: 100%;
  overflow: hidden;
  color: var(--airbnb-ink);
  background: var(--airbnb-canvas);
  border-radius: var(--airbnb-radius-card);
  text-decoration: none;
  transform: perspective(900px) rotateX(var(--card-rotate-x)) rotateY(var(--card-rotate-y));
  transition: transform 220ms ease, box-shadow 180ms ease;
  will-change: transform;
}

.city-card__image {
  aspect-ratio: 4 / 3;
  overflow: hidden;
  background: var(--airbnb-surface-soft);
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
  color: var(--airbnb-muted);
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
  color: var(--airbnb-ink);
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
  color: var(--airbnb-ink);
  background: var(--airbnb-surface-soft);
  border-radius: var(--airbnb-radius-pill);
  font-family: 'Airbnb Cereal VF', Circular, -apple-system, system-ui, Roboto, 'Helvetica Neue', sans-serif;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.18;
  white-space: nowrap;
}

.city-card:focus-visible {
  outline: 2px solid var(--airbnb-ink);
  outline-offset: 4px;
}

@media (hover: hover) and (pointer: fine) {
  .city-card:hover {
    transform: perspective(900px) rotateX(var(--card-rotate-x)) rotateY(var(--card-rotate-y)) translateY(-4px);
    box-shadow: var(--airbnb-shadow-hover);
  }

  .city-card:active {
    transform: perspective(900px) rotateX(0deg) rotateY(0deg) translateY(-1px) scale(0.99);
  }
}

@media (prefers-reduced-motion: reduce) {
  .city-card {
    transition: none;
    will-change: auto;
  }

  .city-card:hover {
    transform: none;
  }
}
</style>
