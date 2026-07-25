<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { GitHubProjectItem, ProjectTaxonomyItem, ToolWebsiteUpdatePayload } from '../../services/projects/projectApi'
import { projectName } from '../../features/projects/projectPresentation'

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
    localError.value = '请输入工具名称。'
    return
  }
  if (!cleanDescription) {
    localError.value = '请输入中文说明。'
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
          <button type="button" class="tool-modal__close" :disabled="busy" aria-label="关闭编辑网页收藏弹窗" @click="close">×</button>
          <p class="projects-kicker">EDIT WEB TOOL</p>
          <h2>编辑网页收藏</h2>
          <p class="tool-modal__hint">这些修改只会影响你的个人网页收藏卡片，不会修改其他用户看到的同一网站信息。</p>

          <div class="tool-modal__manual-grid">
            <label class="tool-modal__field">
              <span>工具名称</span>
              <input v-model="title" type="text" placeholder="例如：Linux.do" :disabled="busy" autofocus />
            </label>
            <label class="tool-modal__field tool-modal__field--wide">
              <span>中文说明</span>
              <textarea v-model="description" rows="3" placeholder="一句话说明这个网站能解决什么问题、适合什么场景。" :disabled="busy" />
            </label>
            <label class="tool-modal__field">
              <span>一级分类</span>
              <select v-model="category" :disabled="busy || taxonomyLoading">
                <option v-for="item in taxonomy" :key="item.slug" :value="item.slug">{{ item.name }}</option>
              </select>
            </label>
            <label class="tool-modal__field">
              <span>二级分类</span>
              <select v-model="subcategory" :disabled="busy || taxonomyLoading">
                <option v-for="item in subcategoryOptions" :key="item.slug" :value="item.slug">{{ item.name }}</option>
              </select>
            </label>
            <label class="tool-modal__field tool-modal__field--wide">
              <span>标签（用逗号分隔）</span>
              <input v-model="tags" type="text" placeholder="社区, 教程, 效率工具" :disabled="busy" />
            </label>
            <label class="tool-modal__field tool-modal__field--wide">
              <span>图标 URL（可选）</span>
              <input v-model="imageUrl" type="text" inputmode="url" placeholder="https://example.com/favicon.ico" :disabled="busy" />
            </label>
            <p v-if="target?.url" class="tool-modal__readonly">原始链接：{{ target.url }}</p>
          </div>

          <p v-if="displayedError" class="tool-modal__error">{{ displayedError }}</p>
          <div class="tool-modal__actions">
            <button type="button" class="btn-secondary" :disabled="busy" @click="close">取消</button>
            <button type="submit" class="projects-add-submit" :disabled="busy">{{ busy ? '保存中…' : '保存修改' }}</button>
          </div>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped src="./toolWebsiteDialog.css"></style>
