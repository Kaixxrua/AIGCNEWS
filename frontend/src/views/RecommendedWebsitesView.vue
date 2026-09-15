<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import WebsiteCollectionTabs from '@/components/websites/WebsiteCollectionTabs.vue'
import RecommendedWebsiteEditor from '@/components/websites/RecommendedWebsiteEditor.vue'
import { useRecommendedWebsites } from '@/composables/useRecommendedWebsites'
import { useAuthStore } from '@/stores/authStore'
import type { RecommendedWebsite, RecommendedWebsiteInput } from '@/services/site/recommendedWebsiteApi'

const { t } = useI18n()
const auth = useAuthStore()
const { websites, loading, saving, deletingId, error, editError, load, save, remove, dispose } = useRecommendedWebsites({ isAdmin: () => auth.isAdmin, t })
const query = ref('')
const category = ref('')
const editorOpen = ref(false)
const editing = ref<RecommendedWebsite | null>(null)
const addButton = ref<HTMLButtonElement | null>(null)
let editorTrigger: HTMLElement | null = null
let activated = false
const categories = computed(() => [...new Set(websites.value.map(site => site.category).filter(Boolean))].sort())
const filtered = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  return websites.value.filter(site => (!category.value || site.category === category.value)
    && (!term || [site.title, site.url, site.description, site.category].some(value => value.toLocaleLowerCase().includes(term))))
})
const domain = (site: RecommendedWebsite) => new URL(site.url).hostname
const openEditor = (website: RecommendedWebsite | null, event: MouseEvent) => {
  editing.value = website
  editorTrigger = event.currentTarget as HTMLElement
  editError.value = ''
  editorOpen.value = true
}
const closeEditor = async () => {
  editorOpen.value = false
  editing.value = null
  await nextTick()
  if (editorTrigger?.isConnected) editorTrigger.focus()
  else addButton.value?.focus()
}
const saveWebsite = async (input: RecommendedWebsiteInput) => {
  if (await save(editing.value?.id ?? null, input)) {
    query.value = ''
    category.value = ''
    await closeEditor()
  }
}
const removeWebsite = async (website: RecommendedWebsite) => {
  if (!window.confirm(t('recommendedWebsites.confirmDelete', { name: website.title }))) return
  if (await remove(website.id)) {
    if (editing.value?.id === website.id) await closeEditor()
    if (!categories.value.includes(category.value)) category.value = ''
    addButton.value?.focus()
  }
}
watch(() => auth.isAdmin, admin => { if (!admin) { editorOpen.value = false; editing.value = null; editError.value = '' } })
onMounted(load)
onActivated(() => { if (activated) void load(); activated = true })
onBeforeUnmount(dispose)
</script>

<template>
  <div class="recommended-websites-page">
    <div class="website-content">
      <header class="website-header">
        <div><h1>{{ t('recommendedWebsites.title') }}</h1><p>{{ t('recommendedWebsites.subtitle') }}</p></div>
        <button v-if="auth.isAdmin" ref="addButton" type="button" class="btn-primary" :disabled="saving || deletingId !== null" @click="openEditor(null, $event)">＋ {{ t('recommendedWebsites.add') }}</button>
      </header>
      <WebsiteCollectionTabs active="recommended" />
      <RecommendedWebsiteEditor v-if="auth.isAdmin && editorOpen" :website="editing" :busy="saving" :error="editError" @save="saveWebsite" @cancel="closeEditor" />
      <div v-if="websites.length" class="website-toolbar">
        <input v-model="query" class="input" type="search" :aria-label="t('recommendedWebsites.search')" :placeholder="t('recommendedWebsites.search')" />
        <select v-if="categories.length" v-model="category" class="input" :aria-label="t('recommendedWebsites.category')">
          <option value="">{{ t('recommendedWebsites.allCategories') }}</option>
          <option v-for="item in categories" :key="item" :value="item">{{ item }}</option>
        </select>
        <span aria-live="polite">{{ t('recommendedWebsites.count', { count: filtered.length }) }}</span>
      </div>
      <div v-if="error" class="website-state website-state--error" role="alert"><p>{{ error }}</p><button type="button" class="btn-secondary" @click="load">{{ t('recommendedWebsites.retry') }}</button></div>
      <div v-else-if="loading && !websites.length" class="website-loading" role="status" :aria-label="t('recommendedWebsites.loading')"><div v-for="index in 3" :key="index" /></div>
      <section v-else-if="!websites.length" class="website-state" role="status">
        <h2>{{ t('recommendedWebsites.emptyTitle') }}</h2>
        <p>{{ t(auth.isAdmin ? 'recommendedWebsites.emptyAdmin' : 'recommendedWebsites.emptyBody') }}</p>
      </section>
      <section v-else-if="!filtered.length" class="website-state" role="status"><p>{{ t('recommendedWebsites.noResults') }}</p><button type="button" class="btn-secondary" @click="query = ''; category = ''">{{ t('recommendedWebsites.clearFilters') }}</button></section>
      <ul v-else class="website-directory">
        <li v-for="website in filtered" :key="website.id" class="website-card">
          <div class="website-card__heading"><span class="website-monogram" aria-hidden="true">{{ website.title.slice(0, 1) }}</span><div><h2><a :href="website.url" target="_blank" rel="noopener noreferrer">{{ website.title }} <span aria-hidden="true">↗</span></a></h2><p>{{ domain(website) }}</p></div></div>
          <p v-if="website.description" class="website-card__reason">{{ website.description }}</p>
          <footer><span v-if="website.category" class="website-category">{{ website.category }}</span><div v-if="auth.isAdmin" class="website-card__actions"><button type="button" :disabled="saving || deletingId !== null" @click="openEditor(website, $event)">{{ t('recommendedWebsites.edit') }}</button><button type="button" :disabled="saving || deletingId !== null" @click="removeWebsite(website)">{{ t(deletingId === website.id ? 'recommendedWebsites.removing' : 'recommendedWebsites.remove') }}</button></div></footer>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.recommended-websites-page { height: 100%; min-height: 0; overflow: auto; padding: 24px; color: var(--ink); background: var(--projects-paper); }
.website-content { display: grid; align-content: start; gap: 20px; max-width: 1440px; margin: 0 auto; }
.website-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.website-header h1 { margin: 0; padding-left: 16px; border-left: 8px solid var(--projects-acid); font-size: var(--text-page); font-weight: 800; letter-spacing: -.03em; }
.website-header p { margin: 8px 0 0; color: var(--ink-secondary); font-size: 14px; }
.website-header .btn-primary { flex-shrink: 0; }
.website-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.website-toolbar input { flex: 1; min-width: 180px; }
.website-toolbar select { width: auto; max-width: 220px; }
.website-toolbar > span { font-size: 12px; color: var(--ink-secondary); white-space: nowrap; }
.website-directory, .website-loading { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: 16px; margin: 0; padding: 0; list-style: none; }
.website-card { padding: 20px; min-width: 0; border: 1px solid var(--rule); border-radius: var(--module-radius); background: var(--paper-raised); }
.website-card__heading { display: flex; align-items: center; gap: 12px; min-width: 0; }
.website-card__heading > div { min-width: 0; }
.website-monogram { display: grid; place-items: center; flex: 0 0 40px; height: 40px; border: 1px solid var(--rule); border-radius: var(--control-radius); background: var(--paper-muted); font-size: 20px; font-weight: 700; }
.website-card h2 { margin: 0; font-size: 17px; font-weight: 700; overflow-wrap: anywhere; }
.website-card h2 a:hover { text-decoration: underline; text-underline-offset: 4px; }
.website-card h2 span { font-size: 14px; color: var(--ink-muted); }
.website-card__heading p { margin: 4px 0 0; font-size: 12px; color: var(--ink-secondary); overflow-wrap: anywhere; }
.website-card__reason { margin: 16px 0 0; color: var(--ink-secondary); font-size: 14px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.website-card footer { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
.website-card footer:empty { display: none; }
.website-category { border: 1px solid var(--rule); border-radius: 4px; padding: 3px 8px; color: var(--ink-secondary); font-size: 12px; }
.website-card__actions { display: flex; gap: 16px; margin-left: auto; font-size: 12px; }
.website-card__actions button { text-decoration: underline; text-underline-offset: 4px; }
.website-state { padding: 32px 24px; border: 1px dashed var(--rule-strong); border-radius: var(--module-radius); }
.website-state h2 { margin: 0; font-size: 18px; font-weight: 700; }
.website-state p { margin: 8px 0 0; color: var(--ink-secondary); font-size: 14px; }
.website-state .btn-secondary { margin-top: 16px; }
.website-state--error { border-color: var(--color-danger, #be123c); }
.website-loading > div { height: 140px; border-radius: var(--module-radius); background: var(--paper-muted); animation: website-pulse 1.2s ease-in-out infinite alternate; }
@keyframes website-pulse { to { opacity: .5; } }
@media (max-width: 639px) { .recommended-websites-page { padding: 16px; } .website-header { flex-wrap: wrap; } .website-toolbar .input { font-size: 16px; } }
@media (prefers-reduced-motion: reduce) { .website-loading > div { animation: none; } }
</style>
