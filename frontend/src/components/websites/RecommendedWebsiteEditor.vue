<script setup lang="ts">
import { nextTick, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { RecommendedWebsite, RecommendedWebsiteInput } from '@/services/site/recommendedWebsiteApi'

const props = defineProps<{ website: RecommendedWebsite | null; busy: boolean; error: string }>()
const emit = defineEmits<{ save: [input: RecommendedWebsiteInput]; cancel: [] }>()
const { t } = useI18n()
const titleInput = ref<HTMLInputElement | null>(null)
const form = reactive<RecommendedWebsiteInput>({ title: '', url: '', description: '', category: '', sort_order: 0 })
watch(() => props.website, async website => {
  Object.assign(form, website
    ? { title: website.title, url: website.url, description: website.description, category: website.category, sort_order: website.sort_order }
    : { title: '', url: '', description: '', category: '', sort_order: 0 })
  await nextTick()
  titleInput.value?.focus()
}, { immediate: true })
</script>

<template>
  <form class="website-editor" :aria-label="t(website ? 'recommendedWebsites.edit' : 'recommendedWebsites.add')" @submit.prevent="emit('save', { ...form })">
    <h2>{{ t(website ? 'recommendedWebsites.edit' : 'recommendedWebsites.add') }}</h2>
    <p class="website-editor__note">{{ t('recommendedWebsites.publishNote') }}</p>
    <div class="website-editor__fields">
      <label>{{ t('recommendedWebsites.name') }}<input ref="titleInput" v-model.trim="form.title" class="input" required maxlength="120" /></label>
      <label>{{ t('recommendedWebsites.url') }}<input v-model.trim="form.url" class="input" type="url" placeholder="https://example.com" required maxlength="2048" /></label>
      <label class="website-editor__reason">{{ t('recommendedWebsites.reason') }}<textarea v-model.trim="form.description" class="input" rows="3" maxlength="500" /></label>
      <label>{{ t('recommendedWebsites.category') }}<input v-model.trim="form.category" class="input" maxlength="64" /></label>
      <label>{{ t('recommendedWebsites.order') }}<input v-model.number="form.sort_order" class="input" type="number" min="-10000" max="10000" step="1" /></label>
    </div>
    <p v-if="error" class="website-editor__error" role="alert">{{ error }}</p>
    <div class="website-editor__actions">
      <button type="submit" class="btn-primary" :disabled="busy">{{ t(busy ? 'recommendedWebsites.saving' : 'recommendedWebsites.save') }}</button>
      <button type="button" class="btn-secondary" :disabled="busy" @click="emit('cancel')">{{ t('recommendedWebsites.cancel') }}</button>
    </div>
  </form>
</template>

<style scoped>
.website-editor { padding: 20px; border: 1px solid var(--rule-strong); border-radius: var(--module-radius); background: var(--paper-raised); }
.website-editor h2 { margin: 0; color: var(--ink); font-size: 18px; font-weight: 700; }
.website-editor__note { margin: 8px 0 16px; color: var(--ink-secondary); font-size: 13px; }
.website-editor__fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.website-editor label { display: grid; gap: 8px; color: var(--ink-secondary); font-size: 13px; font-weight: 600; }
.website-editor .input { min-width: 0; width: 100%; font-size: 14px; }
.website-editor__reason { grid-column: 1 / -1; }
.website-editor textarea { resize: vertical; }
.website-editor__actions { display: flex; gap: 12px; margin-top: 20px; }
.website-editor__error { margin-top: 16px; color: var(--color-danger, #be123c); }
@media (max-width: 639px) { .website-editor__fields { grid-template-columns: minmax(0, 1fr); } .website-editor .input { font-size: 16px; } }
</style>
