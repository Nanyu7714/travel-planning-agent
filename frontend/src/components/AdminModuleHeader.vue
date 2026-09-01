<script setup lang="ts">
import { ArrowLeft } from 'lucide-vue-next'
defineProps<{ eyebrow: string; title: string; description: string }>()
</script>

<template>
  <div class="admin-module-header">
    <RouterLink to="/admin" class="back-button" aria-label="返回管理后台" title="返回管理后台"><ArrowLeft :size="18" /></RouterLink>
    <div><span class="eyebrow">{{ eyebrow }}</span><h1>{{ title }}</h1><p>{{ description }}</p></div>
  </div>
</template>

<style scoped>
.admin-module-header { display: flex; align-items: flex-start; gap: 18px; padding-bottom: 25px; border-bottom: 1px solid var(--border); }
.back-button { width: 34px; height: 34px; flex: none; display: grid; place-items: center; border: 1px solid var(--border); background: var(--surface); color: var(--secondary); }
.back-button:hover { color: var(--primary); border-color: var(--primary); }
.admin-module-header h1 { margin-bottom: 7px; font-size: 27px; }
.admin-module-header p { margin: 0; }
</style>
