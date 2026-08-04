<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { AppLocale } from '@/i18n'
import { localizedCategoryName } from '@/features/projects/projectPresentation'
import type { ManualToolWebsitePayload, ProjectTaxonomyItem } from '@/services/projects/projectApi'

const { locale, t } = useI18n()
const taxonomyLabel = (item: ProjectTaxonomyItem | ProjectTaxonomyItem['children'][number]) => localizedCategoryName(item, locale.value as AppLocale)

const props = defineProps<{
  open: boolean
  active: boolean
  isMyCollection: boolean
  taxonomy: ProjectTaxonomyItem[]
  taxonomyLoading: boolean
  busy: boolean
  error: string
}>()

const emit = defineEmits<{
  close: []
  submitAuto: [url: string]
  submitManual: [payload: ManualToolWebsitePayload]
}>()

const mode = ref<'auto' | 'manual'>('auto')
const url = ref('')
const title = ref('')
const description = ref('')
const category = ref('other')
const subcategory = ref('other_uncategorized')
const tags = ref('')
const localError = ref('')
const selectedCategory = computed(() => props.taxonomy.find((item) => item.slug === category.value))
const subcategoryOptions = computed(() => selectedCategory.value?.children ?? [])
const displayedError = computed(() => localError.value || props.error)

const resetForm = () => {
  mode.value = 'auto'
  url.value = ''
  title.value = ''
  description.value = ''
  tags.value = ''
  localError.value = ''
  const firstCategory = props.taxonomy.find((item) => item.slug === 'other') ?? props.taxonomy[0]
  category.value = firstCategory?.slug ?? 'other'
  subcategory.value = firstCategory?.children[0]?.slug ?? 'other_uncategorized'
}

const close = () => {
  if (props.busy) return
  emit('close')
}

const submit = () => {
  const cleanUrl = url.value.trim()
  if (!cleanUrl) {
    localError.value = t('projects.dialog.urlRequired')
    return
  }
  localError.value = ''
  if (mode.value === 'auto') {
    emit('submitAuto', cleanUrl)
    return
  }
  const cleanTitle = title.value.trim()
  const cleanDescription = description.value.trim()
  if (!cleanTitle) {
    localError.value = t('projects.dialog.nameRequired')
    return
  }
  if (!cleanDescription) {
    localError.value = t('projects.dialog.descriptionRequired')
    return
  }
  emit('submitManual', {
    url: cleanUrl,
    title: cleanTitle,
    description_zh: cleanDescription,
    category_slug: category.value,
    subcategory_slug: subcategory.value,
    tags: tags.value.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
  })
}

watch(() => props.open, (open) => {
  if (open) resetForm()
})

watch([category, () => props.taxonomy], () => {
  const firstSubcategory = subcategoryOptions.value[0]
  if (!subcategoryOptions.value.some((item) => item.slug === subcategory.value)) {
    subcategory.value = firstSubcategory?.slug ?? ''
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="tool-modal">
      <div v-if="active && open" class="tool-modal" role="presentation" @click.self="close">
        <form class="tool-modal__panel" @submit.prevent="submit">
          <button type="button" class="tool-modal__close" :disabled="busy" :aria-label="t('projects.dialog.closeAdd')" @click="close">×</button>
          <p class="projects-kicker">ADD WEB TOOL</p>
          <h2>{{ t(isMyCollection ? 'projects.dialog.addMine' : 'projects.dialog.addWebsite') }}</h2>
          <p class="tool-modal__hint">
            {{ t(isMyCollection ? 'projects.dialog.mineHint' : 'projects.dialog.autoHint') }}
          </p>

          <div class="tool-modal__tabs" :aria-label="t('projects.dialog.addMethod')">
            <button type="button" :class="mode === 'auto' ? 'tool-modal__tab--active' : ''" :disabled="busy" @click="mode = 'auto'">{{ t('projects.dialog.auto') }}</button>
            <button type="button" :class="mode === 'manual' ? 'tool-modal__tab--active' : ''" :disabled="busy" @click="mode = 'manual'">{{ t('projects.dialog.manual') }}</button>
          </div>

          <label class="tool-modal__field">
            <span>{{ t('projects.dialog.url') }}</span>
            <input v-model="url" type="text" inputmode="url" :placeholder="t('projects.dialog.urlPlaceholder')" autocomplete="url" :disabled="busy" autofocus />
          </label>

          <div v-if="mode === 'manual'" class="tool-modal__manual-grid">
            <label class="tool-modal__field">
              <span>{{ t('projects.dialog.name') }}</span>
              <input v-model="title" type="text" :placeholder="t('projects.dialog.namePlaceholder')" :disabled="busy" />
            </label>
            <label class="tool-modal__field tool-modal__field--wide">
              <span>{{ t('projects.dialog.description') }}</span>
              <textarea v-model="description" rows="3" :placeholder="t('projects.dialog.descriptionPlaceholder')" :disabled="busy" />
            </label>
            <label class="tool-modal__field">
              <span>{{ t('projects.dialog.primaryCategory') }}</span>
              <select v-model="category" :disabled="busy || taxonomyLoading">
                <option v-for="item in taxonomy" :key="item.slug" :value="item.slug">{{ taxonomyLabel(item) }}</option>
              </select>
            </label>
            <label class="tool-modal__field">
              <span>{{ t('projects.dialog.subcategory') }}</span>
              <select v-model="subcategory" :disabled="busy || taxonomyLoading">
                <option v-for="item in subcategoryOptions" :key="item.slug" :value="item.slug">{{ taxonomyLabel(item) }}</option>
              </select>
            </label>
            <label class="tool-modal__field tool-modal__field--wide">
              <span>{{ t('projects.dialog.tags') }}</span>
              <input v-model="tags" type="text" :placeholder="t('projects.dialog.tagsPlaceholder')" :disabled="busy" />
            </label>
          </div>

          <p v-if="displayedError" class="tool-modal__error">{{ displayedError }}</p>
          <div class="tool-modal__actions">
            <button type="button" class="btn-secondary" :disabled="busy" @click="close">{{ t('common.cancel') }}</button>
            <button type="submit" class="projects-add-submit" :disabled="busy">
              {{ busy ? t(mode === 'manual' ? 'projects.dialog.saving' : 'projects.dialog.enriching') : t(mode === 'manual' ? 'projects.dialog.manualSave' : 'projects.dialog.addEnrich') }}
            </button>
          </div>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped src="./toolWebsiteDialog.css"></style>
