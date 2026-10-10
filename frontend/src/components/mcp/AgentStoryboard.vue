<script setup lang="ts">
import type { Component } from 'vue'

/**
 * 「复制给 Agent」之后的三格分镜：每格一个序号、一枚图标、一句标题和一行小字，格与格之间一支箭头。
 * 只管结构；桌面的手绘框在 comic-pages/agent-setup.css，窄屏的样式在下面。
 */
export interface StoryboardStep {
  id: string
  icon: Component
  title: string
  body: string
}

defineProps<{ steps: readonly StoryboardStep[]; label: string }>()
</script>

<template>
  <ol class="agent-storyboard" :aria-label="label">
    <li v-for="(step, index) in steps" :key="step.id" class="agent-storyboard-step">
      <span class="agent-storyboard-num" aria-hidden="true">{{ index + 1 }}</span>
      <component :is="step.icon" class="agent-storyboard-icon" aria-hidden="true" />
      <strong class="agent-storyboard-title">{{ step.title }}</strong>
      <span class="agent-storyboard-body">{{ step.body }}</span>
    </li>
  </ol>
</template>

<style scoped>
.agent-storyboard {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.agent-storyboard-step {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-rows: auto auto;
  align-items: center;
  column-gap: 8px;
  min-width: 0;
}

.agent-storyboard-num {
  grid-row: span 2;
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border: 2px solid var(--rule-strong);
  border-radius: 50%;
  background: var(--acid);
  color: var(--acid-ink);
  font-size: 13px;
  font-weight: 900;
  line-height: 1;
}

.agent-storyboard-icon { display: none; }

.agent-storyboard-title {
  min-width: 0;
  color: var(--ink);
  font-size: 13.5px;
  font-weight: 800;
  line-height: 19px;
}

.agent-storyboard-body {
  min-width: 0;
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 17px;
}

/* 窄屏：三格叠成一列，序号盘顶着标题，盘与盘之间串一条虚线。 */
@media (max-width: 1023px) {
  .agent-storyboard { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .agent-storyboard-num { align-self: start; }
  .agent-storyboard-step:not(:last-child)::after {
    content: '';
    position: absolute;
    top: 28px;
    bottom: -10px;
    left: 11px;
    border-left: 2px dashed var(--rule-strong);
  }
}
</style>
