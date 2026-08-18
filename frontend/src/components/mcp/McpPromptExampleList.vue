<script setup lang="ts">
/**
 * McpPromptExampleList — MCP 示例提示词列表（三处引导位复用）
 *
 * mode='demo-copy'（项目页）：有 demoQuery 的条目本体是演示按钮（emit demo），
 * 旁边独立的复制按钮；无 demoQuery 的条目仅复制。
 * mode='copy-only'（/mcp 页）：整条仅复制，showToolTag 时标注对应公开工具。
 * 组件只带结构样式，视觉由各宿主页 :deep() 注入。
 */
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useClipboard } from '@/composables/useClipboard'
import type { McpExamplePrompt } from '@/features/mcp/mcpExamplePrompts'

const props = withDefaults(defineProps<{
  examples: readonly McpExamplePrompt[]
  mode: 'demo-copy' | 'copy-only'
  layout?: 'chips' | 'cards'
  showToolTag?: boolean
}>(), { layout: 'chips', showToolTag: false })

const emit = defineEmits<{ demo: [query: string] }>()

const { t } = useI18n()
const { copy } = useClipboard()
const copiedId = ref('')
let copiedTimer: number | undefined

const promptText = (example: McpExamplePrompt) => t(example.promptKey)

const copyPrompt = async (example: McpExamplePrompt) => {
  try {
    await copy(promptText(example))
  } catch {
    return
  }
  copiedId.value = example.id
  if (copiedTimer) window.clearTimeout(copiedTimer)
  copiedTimer = window.setTimeout(() => { copiedId.value = '' }, 1600)
}

const runDemo = (example: McpExamplePrompt) => {
  if (props.mode !== 'demo-copy' || !example.demoQuery) return
  emit('demo', example.demoQuery)
}

onBeforeUnmount(() => { if (copiedTimer) window.clearTimeout(copiedTimer) })
</script>

<template>
  <ul class="mcp-prompt-list" :class="`mcp-prompt-list--${layout}`">
    <li v-for="example in examples" :key="example.id" class="mcp-prompt-item">
      <template v-if="mode === 'demo-copy'">
        <button
          v-if="example.demoQuery"
          type="button"
          class="mcp-prompt-demo"
          :aria-label="t('mcpExamples.demoAria', { query: example.demoQuery })"
          @click="runDemo(example)"
        >
          <span class="mcp-prompt-text">{{ promptText(example) }}</span>
        </button>
        <span v-else class="mcp-prompt-text mcp-prompt-text--static">{{ promptText(example) }}</span>
        <button
          type="button"
          class="mcp-prompt-copy"
          :aria-label="t('mcpExamples.copyAria')"
          @click="copyPrompt(example)"
        >
          <svg v-if="copiedId !== example.id" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="9" y="9" width="12" height="12" rx="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
          <template v-else>✓ {{ t('mcp.copied') }}</template>
        </button>
      </template>
      <template v-else>
        <span class="mcp-prompt-text">{{ promptText(example) }}</span>
        <span
          v-if="showToolTag && example.toolTag"
          class="mcp-prompt-tool"
          :aria-label="t('mcpExamples.toolTagLabel', { tool: example.toolTag })"
        >{{ example.toolTag }}</span>
        <button
          type="button"
          class="mcp-prompt-copy"
          @click="copyPrompt(example)"
        >{{ copiedId === example.id ? t('mcp.copied') : t('mcpExamples.copy') }}</button>
      </template>
    </li>
  </ul>
</template>

<style scoped>
.mcp-prompt-list {
  display: flex;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.mcp-prompt-list--chips {
  flex-wrap: wrap;
  align-items: center;
}

.mcp-prompt-list--cards {
  flex-direction: column;
}

.mcp-prompt-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mcp-prompt-list--cards .mcp-prompt-item {
  justify-content: space-between;
  gap: 10px;
}

.mcp-prompt-copy svg {
  width: 13px;
  height: 13px;
}

@media (prefers-reduced-motion: reduce) {
  .mcp-prompt-list *, .mcp-prompt-list *::before, .mcp-prompt-list *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>
