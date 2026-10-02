<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { splitCommandPreview } from '@/features/mcp/commandPreview'
import { vMorph } from '@/motion/morph'
import { vSwap } from '@/motion/swap'
import RollText from '@/motion/RollText.vue'

/**
 * 接入命令的终端预览：命令模板原样排出，Token 处是一块占位——还没生成时写「你的 Token」，生成后写「Token 已填入」；
 * 真实 Token 只在复制出去的命令里，页面上不出现。换客户端、终端或安装方式时，新命令沿切换方向滑入，终端高度平滑过渡。
 */
const props = defineProps<{
  /** 用占位串代替 Token 生成的命令模板。 */
  command: string
  /** 带 Token 的真实命令已经生成、可以复制。 */
  filled: boolean
  /** 换了一条命令（客户端、终端或安装方式变了）时随之变化。 */
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
    <pre v-swap="{ key: swapKey, x: direction * 16, y: 0 }" class="command-preview-term"><code><template v-for="(segment, index) in segments" :key="index"><span v-if="segment.kind === 'token'" class="command-slot" :class="{ 'command-slot--filled': filled }"><RollText :value="slotLabel" /></span><span v-else-if="segment.kind === 'encoded'" class="command-slot command-slot--encoded">{{ t('mcp.desk.encodedSlot') }}</span><template v-else>{{ segment.text }}</template></template></code></pre>
  </div>
</template>
