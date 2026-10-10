<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { splitCommandPreview } from '@/features/mcp/commandPreview'
import { vMorph } from '@/motion/morph'
import { vSwap } from '@/motion/swap'
import RollText from '@/motion/RollText.vue'

/**
 * 终端样式的预览：命令、配置或提示词原样排出，Token 处是一块占位——还没准备好时写「你的 Token」，准备好后写「Token 已填入」；
 * 真实 Token 只在复制出去的内容里，页面上不出现。换安装方式时，新命令沿切换方向滑入，终端高度平滑过渡。
 * 下面是各宽度通用的样子；桌面漫画页在 comic-pages/agent-setup.css 里换成手绘框。
 */
const props = defineProps<{
  /** 用占位串代替 Token 生成的文本。 */
  command: string
  /** 带 Token 的真实内容已经准备好、可以复制。 */
  filled: boolean
  /** 换了一条命令（安装方式变了）时随之变化。 */
  swapKey: string
  /** 1：往右边的标签切，新命令从右边滑入；-1：往左。 */
  direction: number
}>()

const { t } = useI18n()
const segments = computed(() => splitCommandPreview(props.command))
const slotLabel = computed(() => t(props.filled ? 'mcp.desk.tokenFilled' : 'mcp.desk.tokenSlot'))
</script>

<template>
  <div v-morph="swapKey" class="command-preview">
    <pre v-swap="{ key: swapKey, x: direction * 16, y: 0 }" class="command-preview-term"><code><template v-for="(segment, index) in segments" :key="index"><span v-if="segment.kind === 'token'" class="command-slot" :class="{ 'command-slot--filled': filled }"><RollText :value="slotLabel" /></span><template v-else>{{ segment.text }}</template></template></code></pre>
  </div>
</template>

<style scoped>
.command-preview {
  min-width: 0;
  border: 2px solid var(--rule-strong);
  border-radius: 5px;
  background: #10151c;
  box-shadow: 3px 3px 0 var(--comic-shadow);
}

.command-preview-term {
  margin: 0;
  padding: 12px 14px 13px;
  color: #e6edf3;
  background: transparent;
  font-family: 'JetBrains Mono', 'Fira Code', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 20px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.command-slot {
  display: inline-block;
  margin: 0 1px;
  padding: 0 7px;
  border: 1.5px dashed var(--acid);
  border-radius: 4px;
  color: var(--acid);
  font-family: inherit;
  font-size: 12px;
  font-weight: 800;
  line-height: 17px;
  white-space: nowrap;
  vertical-align: 1px;
  transition: background-color .2s linear, color .2s linear;
}

.command-slot--filled { border-style: solid; background: var(--acid); color: #10151c; }

@media (prefers-reduced-motion: reduce) {
  .command-slot { transition: none; }
}
</style>
