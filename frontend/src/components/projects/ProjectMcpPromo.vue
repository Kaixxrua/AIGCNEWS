<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import McpPromptExampleList from '@/components/mcp/McpPromptExampleList.vue'
import { MCP_PROMO_EXAMPLE_IDS, mcpExamplesByIds } from '@/features/mcp/mcpExamplePrompts'

// 项目库的「想用自然语言找项目？」推广块。舒适版面和手机平板上是页头下面可展开的横幅；榜单版面（panel）是搜索框右端按钮
// 点开的一块，没有标题条，开合、焦点和 Esc 由页面管。× 在横幅上是本次隐藏，在榜单上是收回按钮，也由页面决定，这里只报事件。
// 宽度、配色和手机上整块隐藏写在页面上：要压过页面给 .glass-card 的边框底色，得和那条规则在同一份样式表里排在它后面。
defineProps<{ panel: boolean; canDemo: boolean }>()
const emit = defineEmits<{ demo: [query: string]; close: []; dismissWeek: [] }>()
const { t } = useI18n()
const examples = mcpExamplesByIds(MCP_PROMO_EXAMPLE_IDS)
</script>

<template>
  <component
    :is="panel ? 'section' : 'details'"
    :id="panel ? 'projects-ask-panel' : undefined"
    class="projects-mcp-promo glass-card"
    :class="{ 'projects-mcp-promo--panel': panel }"
    :tabindex="panel ? -1 : undefined"
    :aria-label="panel ? t('projects.mcpPromo.title') : undefined"
  >
    <summary v-if="!panel" class="projects-mcp-promo__summary">
      <span class="projects-mcp-promo__title">{{ t('projects.mcpPromo.title') }}</span>
      <span class="projects-mcp-promo__expand">{{ t('projects.mcpPromo.expand') }}</span>
      <svg class="projects-mcp-promo__chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
    </summary>
    <div class="projects-mcp-promo__content">
      <div class="projects-mcp-promo__controls">
        <button type="button" class="projects-mcp-promo__dismiss-week" @click="emit('dismissWeek')">
          {{ t('projects.mcpPromo.dismissWeek') }}
        </button>
        <button type="button" class="projects-mcp-promo__dismiss" :aria-label="t('common.close')" @click="emit('close')">×</button>
      </div>
      <div class="projects-mcp-promo__copy">
        <p class="projects-kicker">{{ t('projects.mcpPromo.kicker') }}</p>
        <h2 id="mcp-promo-title">{{ t('projects.mcpPromo.title') }}</h2>
        <p>{{ t('projects.mcpPromo.pitch') }}</p>
        <p class="projects-mcp-promo__try">{{ t('projects.mcpPromo.tryLabel') }}</p>
        <McpPromptExampleList
          :examples="examples"
          :mode="canDemo ? 'demo-copy' : 'copy-only'"
          layout="chips"
          @demo="emit('demo', $event)"
        />
      </div>
      <RouterLink to="/mcp" class="projects-mcp-promo__action">
        {{ t('projects.mcpPromo.cta') }}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M5 12h14" />
          <path d="m14 7 5 5-5 5" />
        </svg>
      </RouterLink>
    </div>
  </component>
</template>

<style scoped>
.projects-mcp-promo__summary { display: flex; align-items: center; gap: 12px; min-height: 44px; padding: 8px 12px; cursor: pointer; list-style: none; }
.projects-mcp-promo__summary::-webkit-details-marker { display: none; }
.projects-mcp-promo__title { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 700; }
.projects-mcp-promo__title::before { content: '✦'; color: var(--tone-lime); font-size: 18px; }
.projects-mcp-promo__expand { margin-left: auto; color: var(--ink-secondary); font-size: 12px; }
.projects-mcp-promo__chevron { width: 26px; height: 26px; flex: 0 0 26px; padding: 5px; border: 1px solid var(--projects-accent); border-radius: 4px; color: var(--projects-on-acid); background: var(--projects-acid); }
.projects-mcp-promo[open] .projects-mcp-promo__chevron { transform: rotate(180deg); }
.projects-mcp-promo__content { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 8px 16px; padding: 12px 16px 16px; border-top: 1px solid var(--rule); }
.projects-mcp-promo__controls { display: flex; grid-column: 2; grid-row: 1; justify-content: flex-end; gap: 8px; }
.projects-mcp-promo__dismiss, .projects-mcp-promo__dismiss-week { min-height: 36px; padding: 4px 8px; border: 1px solid var(--rule); border-radius: var(--control-radius); font-size: 12px; }
.projects-mcp-promo__dismiss { min-width: 36px; }
.projects-mcp-promo__copy { min-width: 0; grid-column: 1; grid-row: 1; }
.projects-mcp-promo__copy h2 { display: none; }
.projects-mcp-promo__copy > p { color: var(--ink-secondary); font-size: 14px; line-height: 1.7; margin: 0 0 8px; }
.projects-mcp-promo__copy .projects-kicker { display: none; }
.projects-mcp-promo__action { display: inline-flex; grid-column: 1 / -1; align-items: center; justify-self: start; gap: 8px; min-height: 40px; color: var(--ink); font-size: 13px; font-weight: 650; text-decoration: underline; text-underline-offset: 4px; }
.projects-mcp-promo__action svg { width: 16px; height: 16px; }
.projects-mcp-promo__action:hover { color: var(--ink-secondary); }
/* 榜单版面点开的那一块没有标题条，焦点进来时不画框（键盘进来才画）。 */
.projects-mcp-promo--panel .projects-mcp-promo__content { border-top: 0; }
.projects-mcp-promo--panel:focus { outline: none; }
.projects-mcp-promo--panel:focus-visible { outline: 2px solid var(--projects-accent); outline-offset: 2px; }

@media (max-width: 720px) {
  .projects-mcp-promo__expand { display: none; }
  .projects-mcp-promo__chevron { margin-left: auto; }

  .projects-mcp-promo__action {
    width: 100%;
  }

  .projects-mcp-promo__content {
    grid-template-columns: 1fr;
  }

  .projects-mcp-promo__controls,
  .projects-mcp-promo__copy,
  .projects-mcp-promo__action {
    grid-column: 1;
    grid-row: auto;
  }
}
</style>
