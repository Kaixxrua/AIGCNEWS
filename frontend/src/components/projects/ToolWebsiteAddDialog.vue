<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ManualToolWebsitePayload, ProjectTaxonomyItem } from '../../services/api'

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
    localError.value = '请输入工具网页链接。'
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
    localError.value = '请输入工具名称。'
    return
  }
  if (!cleanDescription) {
    localError.value = '请输入中文说明。'
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
          <button type="button" class="tool-modal__close" :disabled="busy" aria-label="关闭添加网页收藏弹窗" @click="close">×</button>
          <p class="projects-kicker">ADD WEB TOOL</p>
          <h2>{{ isMyCollection ? '添加到我的收藏' : '收藏一个网页' }}</h2>
          <p class="tool-modal__hint">
            {{ isMyCollection ? '普通用户添加的网站只进入你的个人收藏夹；自动模式会抓取 metadata 并 AI 富化。' : '自动模式会抓取网页 metadata 并 AI 富化；如果网站拦截爬取或网络不可达，可切换手动模式填写说明。' }}
          </p>

          <div class="tool-modal__tabs" aria-label="添加方式">
            <button type="button" :class="mode === 'auto' ? 'tool-modal__tab--active' : ''" :disabled="busy" @click="mode = 'auto'">自动抓取</button>
            <button type="button" :class="mode === 'manual' ? 'tool-modal__tab--active' : ''" :disabled="busy" @click="mode = 'manual'">手动添加</button>
          </div>

          <label class="tool-modal__field">
            <span>工具链接</span>
            <input v-model="url" type="text" inputmode="url" placeholder="https://example.com 或 example.com" autocomplete="url" :disabled="busy" autofocus />
          </label>

          <div v-if="mode === 'manual'" class="tool-modal__manual-grid">
            <label class="tool-modal__field">
              <span>工具名称</span>
              <input v-model="title" type="text" placeholder="例如：Linux.do" :disabled="busy" />
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
          </div>

          <p v-if="displayedError" class="tool-modal__error">{{ displayedError }}</p>
          <div class="tool-modal__actions">
            <button type="button" class="btn-secondary" :disabled="busy" @click="close">取消</button>
            <button type="submit" class="projects-add-submit" :disabled="busy">
              {{ busy ? (mode === 'manual' ? '保存中…' : '抓取并富化中…') : (mode === 'manual' ? '手动保存' : '添加并 AI 富化') }}
            </button>
          </div>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped src="./toolWebsiteDialog.css"></style>
