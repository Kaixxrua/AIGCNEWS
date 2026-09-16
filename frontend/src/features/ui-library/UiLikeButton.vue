<script setup lang="ts">
import { computed, ref } from 'vue'
import { Heart } from 'lucide-vue-next'
import { useUiLibraryAccount } from './useUiLibraryAccount'
import type { UiLanguage } from './catalog'
const props = defineProps<{ id: string; lang: UiLanguage }>()
const account = useUiLibraryAccount()
const item = computed(() => account.stats.value[props.id])
const error = ref(false)
async function toggle() {
  error.value = false
  try { await account.like(props.id) } catch { error.value = true }
}
</script>
<template>
  <span class="ui-library__like-wrap">
    <button type="button" class="ui-library__like" :class="{ 'is-liked': item?.liked }" :aria-pressed="Boolean(item?.liked)" :aria-label="lang === 'zh' ? (item?.liked ? '取消喜欢' : '喜欢') : (item?.liked ? 'Unlike' : 'Like')" :disabled="account.liking.value.has(id)" @click="toggle"><Heart :size="15" :fill="item?.liked ? 'currentColor' : 'none'" /><span>{{ item?.likes ?? 0 }}</span></button>
    <span v-if="error" role="status">{{ lang === 'zh' ? '操作失败，请重试' : 'Please retry' }}</span>
  </span>
</template>
