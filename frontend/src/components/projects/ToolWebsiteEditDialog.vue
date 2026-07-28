<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { GitHubProjectItem, ProjectTaxonomyItem, ToolWebsiteUpdatePayload } from '../../services/projects/projectApi'
import { projectName } from '../../features/projects/projectPresentation'

const { t } = useI18n()

const props = defineProps<{
  open: boolean
  active: boolean
  target: GitHubProjectItem | null
  taxonomy: ProjectTaxonomyItem[]
  taxonomyLoading: boolean
  busy: boolean
  error: string
}>()

const emit = defineEmits<{
  close: []
  submit: [websiteId: string | number, payload: ToolWebsiteUpdatePayload]
}>()

const title = ref('')
const description = ref('')
const category = ref('other')
const subcategory = ref('other_uncategorized')
const tags = ref('')
const imageUrl = ref('')
const localError = ref('')
const selectedCategory = computed(() => props.taxonomy.find((item) => item.slug === category.value))
const subcategoryOptions = computed(() => selectedCategory.value?.children ?? [])
const displayedError = computed(() => localError.value || props.error)

const initializeForm = () => {
  const target = props.target
  if (!target) return
  title.value = target.title || projectName(target)
  description.value = target.description_zh || target.description || ''
  category.value = target.category_slug || 'other'
  subcategory.value = target.subcategory_slug || ''
  tags.value = (target.tags ?? []).join(', ')
  imageUrl.value = target.image_url || ''
  localError.value = ''
}

const close = () => {
  if (props.busy) return
  emit('close')
}

const submit = () => {
  const websiteId = props.target?.website_id
  if (!websiteId) return
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
  localError.value = ''
  emit('submit', websiteId, {
    title: cleanTitle,
    description: cleanDescription,
    description_zh: cleanDescription,
    category_slug: category.value,
    subcategory_slug: subcategory.value,
    image_url: imageUrl.value.trim(),
    tags: tags.value.split(/[，,]/).map((item) => item.trim()).filter(Boolean),
  })
}

watch([() => props.open, () => props.target], ([open]) => {
  if (open) initializeForm()
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
          <button type="button" class="tool-modal__close" :disabled="busy" :aria-label="t('projects.dialog.closeEdit')" @click="close">×</button>
          <p class="projects-kicker">EDIT WEB TOOL</p>
          <h2>{{ t('projects.dialog.editTitle') }}</h2>
          <p class="tool-modal__hint">{{ t('projects.dialog.editHint') }}</p>

          <div class="tool-modal__manual-grid">
            <label class="tool-modal__field">
              <span>{{ t('projects.dialog.name') }}</span>
              <input v-model="title" type="text" :placeholder="t('projects.dialog.namePlaceholder')" :disabled="busy" autofocus />
            </label>
            <label class="tool-modal__field tool-modal__field--wide">
              <span>{{ t('projects.dialog.description') }}</span>
              <textarea v-model="description" rows="3" :placeholder="t('projects.dialog.descriptionPlaceholder')" :disabled="busy" />
            </label>
            <label class="tool-modal__field">
              <span>{{ t('projects.dialog.primaryCategory') }}</span>
              <select v-model="category" :disabled="busy || taxonomyLoading">
                <option v-for="item in taxonomy" :key="item.slug" :value="item.slug">{{ item.name }}</option>
              </select>
            </label>
            <label class="tool-modal__field">
              <span>{{ t('projects.dialog.subcategory') }}</span>
              <select v-model="subcategory" :disabled="busy || taxonomyLoading">
                <option v-for="item in subcategoryOptions" :key="item.slug" :value="item.slug">{{ item.name }}</option>
              </select>
            </label>
            <label class="tool-modal__field tool-modal__field--wide">
              <span>{{ t('projects.dialog.tags') }}</span>
              <input v-model="tags" type="text" :placeholder="t('projects.dialog.tagsPlaceholder')" :disabled="busy" />
            </label>
            <label class="tool-modal__field tool-modal__field--wide">
              <span>{{ t('projects.dialog.iconUrl') }}</span>
              <input v-model="imageUrl" type="text" inputmode="url" placeholder="https://example.com/favicon.ico" :disabled="busy" />
            </label>
            <p v-if="target?.url" class="tool-modal__readonly">{{ t('projects.dialog.originalUrl', { url: target.url }) }}</p>
          </div>

          <p v-if="displayedError" class="tool-modal__error">{{ displayedError }}</p>
          <div class="tool-modal__actions">
            <button type="button" class="btn-secondary" :disabled="busy" @click="close">{{ t('common.cancel') }}</button>
            <button type="submit" class="projects-add-submit" :disabled="busy">{{ t(busy ? 'projects.dialog.saving' : 'projects.dialog.saveChanges') }}</button>
          </div>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped src="./toolWebsiteDialog.css"></style>
