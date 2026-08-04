<script setup lang="ts">
/**
 * GlobalSearch.vue
 * 顶部全局搜索框（Ctrl/Cmd+K 唤醒，300ms debounce，空输入时展示今日 Top10）
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import GlobalSearchInput from './search/GlobalSearchInput.vue'
import GlobalSearchResults from './search/GlobalSearchResults.vue'
import { useGlobalSearch } from '@/composables/useGlobalSearch'
import { searchPapers, fetchTop10Today } from '@/services/papers/paperApi'

const router = useRouter()
const { t } = useI18n()
const inputRef = ref<InstanceType<typeof GlobalSearchInput> | null>(null)
const {
  query,
  results,
  showDropdown,
  loading,
  focused,
  onFocus,
  onBlur,
  onSelectItem,
} = useGlobalSearch({
  inputRef,
  search: searchPapers,
  fetchTop10: fetchTop10Today,
  push: location => router.push(location),
  openExternal: url => window.open(url, '_blank', 'noopener,noreferrer'),
})
</script>

<template>
  <div class="relative w-full max-w-sm mx-auto" style="z-index: 200">
    <!-- 搜索输入框 -->
    <GlobalSearchInput
      ref="inputRef"
      v-model="query"
      :focused="focused"
      :loading="loading"
      @focus="onFocus"
      @blur="onBlur"
    />

    <!-- 下拉结果列表 -->
    <Transition name="search-drop">
      <GlobalSearchResults
        v-if="showDropdown && results.length > 0"
        :query="query"
        :results="results"
        @select="onSelectItem"
      />
    </Transition>

    <!-- 搜索无结果提示 -->
    <Transition name="search-drop">
      <div
        v-if="showDropdown && !loading && results.length === 0 && query.trim()"
        class="absolute left-0 right-0 top-full mt-1.5 rounded-2xl px-4 py-3 text-xs text-stone-400 shadow-lg"
        style="background: rgb(var(--card-rgb) / 0.97); border: 1px solid rgb(var(--stone-400-rgb) / 0.2);"
      >
        {{ t('search.noResults') }}
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.search-drop-enter-active,
.search-drop-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.search-drop-enter-from,
.search-drop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
