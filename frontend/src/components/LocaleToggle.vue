<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { setAppLocale, type AppLocale } from '../i18n'

const { locale, t } = useI18n()

const changeLocale = (event: Event) => {
  setAppLocale((event.target as HTMLSelectElement).value as AppLocale)
}
</script>

<template>
  <label class="locale-toggle">
    <span class="sr-only">{{ t('common.language') }}</span>
    <select
      class="locale-select"
      :value="locale"
      :aria-label="t('common.language')"
      @change="changeLocale"
    >
      <option value="zh-CN">{{ t('common.chinese') }}</option>
      <option value="en-US">{{ t('common.english') }}</option>
    </select>
  </label>
</template>

<style scoped>
.locale-toggle { display: inline-flex; flex: 0 0 auto; }
.locale-select {
  height: 30px;
  max-width: 92px;
  padding: 0 24px 0 9px;
  border: 1px solid var(--rule-strong);
  border-radius: 6px;
  color: var(--ink-muted);
  background: var(--paper-raised);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.locale-select:hover, .locale-select:focus-visible { color: var(--ink); background: var(--acid-soft); }
.locale-select:focus-visible { outline: 2px solid var(--acid); outline-offset: 2px; }
</style>
