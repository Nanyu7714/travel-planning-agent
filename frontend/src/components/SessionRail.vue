<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Archive, ArchiveRestore, Bot, ChevronLeft, ChevronRight, EllipsisVertical, Pencil, Pin, PinOff, Sparkles, Trash2 } from 'lucide-vue-next'

export type ChatSession = {
  id: number
  title: string
  is_pinned: boolean
  archived_at: string | null
  created_at: string
  updated_at: string | null
}

defineProps<{
  sessions: ChatSession[]
  activeSessionId: number | null
  archivedView: boolean
}>()

const emit = defineEmits<{
  select: [session: ChatSession]
  create: []
  switchView: []
  rename: [session: ChatSession]
  pin: [session: ChatSession]
  archive: [session: ChatSession]
  delete: [session: ChatSession]
  collapse: [collapsed: boolean]
}>()

const storageKey = 'travel-planner-session-rail-collapsed'
const collapsed = ref(localStorage.getItem(storageKey) === 'true')
const openMenuId = ref<number | null>(null)

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  openMenuId.value = null
  localStorage.setItem(storageKey, String(collapsed.value))
  emit('collapse', collapsed.value)
}

function toggleMenu(sessionId: number) {
  openMenuId.value = openMenuId.value === sessionId ? null : sessionId
}

function run(action: 'rename' | 'pin' | 'archive' | 'delete', session: ChatSession) {
  openMenuId.value = null
  if (action === 'rename') emit('rename', session)
  else if (action === 'pin') emit('pin', session)
  else if (action === 'archive') emit('archive', session)
  else emit('delete', session)
}

function closeMenu() { openMenuId.value = null }

onMounted(() => {
  emit('collapse', collapsed.value)
  document.addEventListener('click', closeMenu)
})
onBeforeUnmount(() => document.removeEventListener('click', closeMenu))
</script>

<template>
  <aside :class="['session-rail', { collapsed }]">
    <div class="rail-heading">
      <span v-if="!collapsed" class="eyebrow">{{ archivedView ? 'ARCHIVED' : 'YOUR TRIPS' }}</span>
      <div v-if="!collapsed" class="rail-actions">
        <button class="icon-button" :aria-label="archivedView ? '查看当前会话' : '查看已归档会话'" :title="archivedView ? '查看当前会话' : '查看已归档会话'" @click="emit('switchView')"><ArchiveRestore v-if="archivedView" :size="17" /><Archive v-else :size="17" /></button>
        <button class="icon-button" aria-label="新建会话" title="新建会话" @click="emit('create')"><Sparkles :size="17" /></button>
      </div>
      <button class="collapse-button" :aria-label="collapsed ? '展开会话列表' : '收起会话列表'" :title="collapsed ? '展开会话列表' : '收起会话列表'" @click="toggleCollapsed"><ChevronRight v-if="collapsed" :size="17" /><ChevronLeft v-else :size="17" /></button>
    </div>

    <div class="session-scroll">
      <div v-for="session in sessions" :key="session.id" class="session-entry">
        <button :class="['session-item', { active: activeSessionId === session.id }]" :title="session.title" @click="emit('select', session)"><Bot :size="16" /><span v-if="!collapsed">{{ session.title }}</span><Pin v-if="session.is_pinned && !collapsed" class="session-pin" :size="13" /></button>
        <button v-if="!collapsed" class="session-menu-trigger" aria-label="管理会话" title="管理会话" @click.stop="toggleMenu(session.id)"><EllipsisVertical :size="16" /></button>
        <div v-if="!collapsed && openMenuId === session.id" class="session-menu" role="menu" @click.stop>
          <button role="menuitem" @click="run('rename', session)"><Pencil :size="14" />重命名</button>
          <button v-if="!archivedView" role="menuitem" @click="run('pin', session)"><PinOff v-if="session.is_pinned" :size="14" /><Pin v-else :size="14" />{{ session.is_pinned ? '取消置顶' : '置顶此对话' }}</button>
          <button role="menuitem" @click="run('archive', session)"><ArchiveRestore v-if="archivedView" :size="14" /><Archive v-else :size="14" />{{ archivedView ? '恢复' : '归档' }}</button>
          <button class="danger" role="menuitem" @click="run('delete', session)"><Trash2 :size="14" />删除此对话</button>
        </div>
      </div>
      <div v-if="!sessions.length && !collapsed" class="session-placeholder"><Archive v-if="archivedView" :size="20" /><Bot v-else :size="20" /><span>{{ archivedView ? '暂无归档会话' : '新的旅行规划' }}</span><small>{{ archivedView ? '归档后的会话会显示在这里' : '从一句想法开始' }}</small></div>
    </div>
  </aside>
</template>

<style scoped>
.session-rail { position: sticky; top: 64px; height: calc(100vh - 64px); min-height: 0; padding: 24px 12px 12px; display: flex; flex-direction: column; overflow: visible; background: var(--bg); transition: padding .18s ease; }
.rail-heading { min-height: 38px; flex: none; align-items: flex-start; gap: 3px; padding: 0 4px 8px; }
.rail-heading .eyebrow { flex: 1; margin-top: 7px; }
.rail-actions { display: flex; gap: 1px; }
.collapse-button { width: 28px; height: 28px; flex: none; display: grid; place-items: center; border: 0; background: transparent; color: var(--secondary); }
.collapse-button:hover { color: var(--primary); background: var(--primary-soft); }
.session-scroll { min-height: 0; flex: 1; overflow-y: auto; overflow-x: visible; padding-right: 4px; scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
.session-scroll::-webkit-scrollbar { width: 5px; }
.session-scroll::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
.session-entry { position: relative; }
.session-entry .session-item { padding-right: 32px; }
.session-pin { margin-left: auto; flex: none; color: var(--primary); }
.session-menu-trigger { position: absolute; z-index: 2; right: 5px; top: 14px; width: 26px; height: 26px; display: grid; place-items: center; border: 0; background: transparent; color: var(--secondary); opacity: 0; }
.session-entry:hover .session-menu-trigger, .session-menu-trigger:focus-visible, .session-item.active + .session-menu-trigger { opacity: 1; }
.session-menu-trigger:hover { color: var(--primary); background: var(--primary-soft); }
.session-menu { position: absolute; z-index: 8; top: 41px; right: 4px; width: 158px; padding: 5px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); box-shadow: 0 8px 24px rgba(31, 45, 48, .14); }
.session-menu button { width: 100%; min-height: 34px; padding: 7px 9px; display: flex; align-items: center; gap: 8px; border: 0; background: transparent; color: var(--text); font-size: 12px; text-align: left; }
.session-menu button:hover, .session-menu button:focus-visible { background: var(--primary-soft); color: var(--primary); }
.session-menu button.danger { color: var(--danger); border-top: 1px solid var(--border); margin-top: 4px; padding-top: 9px; }
.session-rail.collapsed { padding: 24px 7px 12px; }
.collapsed .rail-heading { justify-content: center; padding-inline: 0; }
.collapsed .session-item { min-height: 42px; justify-content: center; padding: 12px 0; border-left: 0; border-bottom: 2px solid transparent; }
.collapsed .session-item.active { border-bottom-color: var(--primary); }
@media (max-width: 1000px) { .session-rail { display: none; } }
</style>
