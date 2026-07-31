<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
defineProps<{
  page: number
  totalPages: number
  total: number
  hasPrev: boolean
  hasNext: boolean
  pageJump: string
}>()

const emit = defineEmits<{
  'update:pageJump': [value: string]
  goPage: [page: number]
  jumpToPage: []
}>()
</script>

<template>
  <nav class="projects-pagination glass-card" :aria-label="t('projects.pagination')">
    <p>{{ t('projects.pageSummary', { page, totalPages, total }) }}</p>
    <div class="projects-pagination__controls">
      <button class="btn-secondary projects-pagination__button" :disabled="!hasPrev" @click="emit('goPage', page - 1)">{{ t('projects.previous') }}</button>
      <form class="projects-pagination__jump" :aria-label="t('projects.pageJump')" @submit.prevent="emit('jumpToPage')">
        <span>{{ t('projects.jumpTo') }}</span>
        <input :value="pageJump" type="number" inputmode="numeric" min="1" :max="totalPages" :placeholder="String(page)" :aria-label="t('projects.pageInput')" @input="emit('update:pageJump', ($event.target as HTMLInputElement).value)" />
        <span>{{ t('common.page') }}</span>
        <button class="btn-secondary projects-pagination__button projects-pagination__button--jump" type="submit">{{ t('projects.jump') }}</button>
      </form>
      <button class="btn-secondary projects-pagination__button" :disabled="!hasNext" @click="emit('goPage', page + 1)">{{ t('projects.next') }}</button>
    </div>
  </nav>
</template>

<style scoped>
.projects-pagination { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 18px; padding: 14px 16px; }
.projects-pagination p { color: #78716c; font-size: 13px; font-weight: 700; }
.projects-pagination__controls { display: flex; align-items: center; gap: 8px; }
.projects-pagination__button { min-width: 104px; height: var(--projects-control-height, 44px); box-sizing: border-box; justify-content: center; padding: 0 14px; white-space: nowrap; }
.projects-pagination__button--jump { min-width: 82px; }
.projects-pagination__jump { display: flex; align-items: center; gap: 7px; margin: 0 2px; color: #78716c; font-size: 12px; font-weight: 700; }
.projects-pagination__jump input { width: 58px; height: var(--projects-control-height, 44px); box-sizing: border-box; padding: 0 8px; color: #44403c; font-size: 13px; font-weight: 700; text-align: center; background: var(--projects-paper-light); border: 1px solid #11110f; border-radius: 4px; box-shadow: none; outline: none; transition: border-color 160ms ease, box-shadow 160ms ease, background 160ms ease; }
.projects-pagination__jump input:focus { border-color: #11110f; box-shadow: 0 0 0 3px var(--projects-acid); }
.projects-pagination__jump input::-webkit-inner-spin-button, .projects-pagination__jump input::-webkit-outer-spin-button { margin: 0; appearance: none; }

@media (max-width: 720px) {
  .projects-pagination { align-items: flex-start; flex-direction: column; }
  .projects-pagination__controls { width: 100%; flex-wrap: wrap; }
  .projects-pagination__button { flex: 1 1 128px; min-width: 0; }
  .projects-pagination__jump { flex: 1 1 100%; justify-content: center; order: 3; }
}
</style>
