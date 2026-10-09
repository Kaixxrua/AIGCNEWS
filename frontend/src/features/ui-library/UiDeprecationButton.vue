<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAuthStore } from '@/stores/authStore'
import { api } from '@/services/http/apiClient'
import type { UiLanguage } from './catalog'

const props = defineProps<{ id: string; deprecated?: boolean; lang: UiLanguage }>()
const emit = defineEmits<{ changed: [deprecated: boolean] }>()
const auth = useAuthStore()
const busy = ref(false)
const failed = ref(false)
const label = computed(() => props.lang === 'zh'
  ? props.deprecated ? '已废弃 · 恢复' : '废弃'
  : props.deprecated ? 'Deprecated · Restore' : 'Deprecate')

async function toggle() {
  if (busy.value || !auth.isAdmin) return
  busy.value = true
  failed.value = false
  try {
    const { data } = await api.put<{ deprecated: boolean }>(`/ops/ui-library/${encodeURIComponent(props.id)}/visibility`, { deprecated: !props.deprecated })
    if (auth.isAdmin) emit('changed', data.deprecated)
  } catch {
    failed.value = true
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="auth.isAdmin" class="ui-deprecation">
    <button type="button" :disabled="busy" :aria-pressed="Boolean(deprecated)" :title="lang === 'zh' ? '废弃的素材对用户隐藏，可随时恢复' : 'Deprecated materials are hidden from users and can be restored'" @click.stop="toggle">{{ label }}</button>
    <span v-if="failed" role="alert">{{ lang === 'zh' ? '操作失败，请重试' : 'Failed. Please retry.' }}</span>
  </div>
</template>

<style scoped>
.ui-deprecation { position: absolute; top: 8px; left: 8px; z-index: 6; display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.ui-deprecation button { border: 1px solid var(--rule-strong); border-radius: 4px; background: var(--paper-raised); color: var(--ink); padding: 3px 7px; font-size: 12px; line-height: 1.4; cursor: pointer; }
.ui-deprecation button[aria-pressed=true] { background: var(--acid-soft); }
.ui-deprecation button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.ui-deprecation button:disabled { opacity: .6; cursor: wait; }
.ui-deprecation span { max-width: 150px; background: var(--paper-raised); color: var(--ink); font-size: 12px; }
</style>
