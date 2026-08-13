<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import {
  formatDate,
} from '@/features/monitor/monitorViewModel'
import type {
  SiteContactPageConfig,
  SiteContactPageForm,
} from '@/features/monitor/monitorModel'

const props = defineProps<{
  config: SiteContactPageConfig | null
  form: SiteContactPageForm
  loading: boolean
  saving: boolean
}>()

const emit = defineEmits<{
  save: []
}>()

const updateForm = <K extends keyof SiteContactPageForm>(field: K, value: SiteContactPageForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}

/** 服务卡片图标可选项：key 存入 DB，前端 ContactPageView 映射为内联 SVG */
const ICON_OPTIONS = ['default', 'code', 'briefcase', 'chat', 'rocket'] as const

const addServiceCard = () => {
  // eslint-disable-next-line vue/no-mutating-props -- 同上：受控草稿的动态列表增行
  props.form.service_cards.push({ title: '', description: '', icon: 'default' })
}

const removeServiceCard = (index: number) => {
  // eslint-disable-next-line vue/no-mutating-props -- 同上：受控草稿的动态列表删行
  props.form.service_cards.splice(index, 1)
}

const addContactEntry = () => {
  // eslint-disable-next-line vue/no-mutating-props -- 同上：受控草稿的动态列表增行
  props.form.contact_entries.push({ label: '', value: '', href: '', qr_image_url: '' })
}

const removeContactEntry = (index: number) => {
  // eslint-disable-next-line vue/no-mutating-props -- 同上：受控草稿的动态列表删行
  props.form.contact_entries.splice(index, 1)
}
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.1s">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.contactPageConfig.title') }}</h3>
      <span v-if="config?.enabled" class="badge monitor-status-success">{{ t('monitor.contactPageConfig.enabledBadge') }}</span>
      <span v-else class="badge monitor-status-unknown">{{ t('monitor.contactPageConfig.disabledBadge') }}</span>
      <span v-if="config?.updated_at" class="ml-auto text-2xs monitor-caption">{{ t('monitor.updatedAt', { date: formatDate(config.updated_at) }) }}</span>
    </div>

    <p class="mb-3 text-xs monitor-caption">{{ t('monitor.contactPageConfig.hint') }}</p>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-[minmax(140px,0.6fr)_minmax(200px,1fr)_minmax(200px,1fr)] lg:items-end">
      <div class="flex items-end gap-4 pb-2">
        <label class="inline-flex items-center gap-1.5 text-xs monitor-caption">
          <input :checked="form.enabled" type="checkbox" class="rounded border-stone-300 text-stone-700 focus:ring-stone-400" :disabled="loading || saving" @change="updateForm('enabled', ($event.target as HTMLInputElement).checked)" />
          {{ t('monitor.contactPageConfig.enabled') }}
        </label>
      </div>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.contactPageConfig.navLabel') }}</span>
        <input :value="form.nav_label" type="text" maxlength="20" class="input w-full py-2 text-xs" :placeholder="t('monitor.contactPageConfig.navLabelPlaceholder')" autocomplete="off" :disabled="loading || saving" @input="updateForm('nav_label', ($event.target as HTMLInputElement).value)" />
      </label>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.contactPageConfig.pageTitle') }}</span>
        <input :value="form.title" type="text" maxlength="100" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving" @input="updateForm('title', ($event.target as HTMLInputElement).value)" />
      </label>
      <label class="block md:col-span-2 lg:col-span-3">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.contactPageConfig.subtitle') }}</span>
        <input :value="form.subtitle" type="text" maxlength="255" class="input w-full py-2 text-xs" autocomplete="off" :disabled="loading || saving" @input="updateForm('subtitle', ($event.target as HTMLInputElement).value)" />
      </label>
    </div>

    <!-- ═══ 服务卡片（外包服务 / 商务合作等） ═══ -->
    <div class="mt-4">
      <div class="mb-2 flex items-center gap-2">
        <span class="text-xs font-semibold monitor-section-title">{{ t('monitor.contactPageConfig.serviceCards') }}</span>
        <button class="monitor-btn-secondary" :disabled="loading || saving || form.service_cards.length >= 6" @click="addServiceCard">
          + {{ t('monitor.contactPageConfig.addCard') }}
        </button>
      </div>
      <div v-if="form.service_cards.length" class="flex flex-col gap-2">
        <div v-for="(card, index) in form.service_cards" :key="index" class="monitor-check-row flex flex-wrap items-end gap-2 px-3 py-2">
          <label class="block min-w-[140px] flex-1">
            <span class="mb-1 block text-2xs monitor-caption">{{ t('monitor.contactPageConfig.cardTitle') }}</span>
            <input v-model="card.title" type="text" maxlength="50" class="input w-full py-1.5 text-xs" autocomplete="off" :disabled="loading || saving" />
          </label>
          <label class="block min-w-[220px] flex-[2]">
            <span class="mb-1 block text-2xs monitor-caption">{{ t('monitor.contactPageConfig.cardDescription') }}</span>
            <input v-model="card.description" type="text" maxlength="500" class="input w-full py-1.5 text-xs" autocomplete="off" :disabled="loading || saving" />
          </label>
          <label class="block w-[110px]">
            <span class="mb-1 block text-2xs monitor-caption">{{ t('monitor.contactPageConfig.cardIcon') }}</span>
            <select v-model="card.icon" class="input w-full py-1.5 text-xs" :disabled="loading || saving">
              <option v-for="option in ICON_OPTIONS" :key="option" :value="option">{{ t(`monitor.contactPageConfig.icon.${option}`) }}</option>
            </select>
          </label>
          <button class="monitor-btn-secondary" :disabled="loading || saving" :title="t('monitor.contactPageConfig.removeEntry')" @click="removeServiceCard(index)">×</button>
        </div>
      </div>
    </div>

    <!-- ═══ 联系方式（QQ 群 / 邮箱 / 二维码等） ═══ -->
    <div class="mt-4">
      <div class="mb-2 flex items-center gap-2">
        <span class="text-xs font-semibold monitor-section-title">{{ t('monitor.contactPageConfig.contactEntries') }}</span>
        <button class="monitor-btn-secondary" :disabled="loading || saving || form.contact_entries.length >= 8" @click="addContactEntry">
          + {{ t('monitor.contactPageConfig.addEntry') }}
        </button>
      </div>
      <div v-if="form.contact_entries.length" class="flex flex-col gap-2">
        <div v-for="(entry, index) in form.contact_entries" :key="index" class="monitor-check-row flex flex-wrap items-end gap-2 px-3 py-2">
          <label class="block w-[130px]">
            <span class="mb-1 block text-2xs monitor-caption">{{ t('monitor.contactPageConfig.entryLabel') }}</span>
            <input v-model="entry.label" type="text" maxlength="50" class="input w-full py-1.5 text-xs" placeholder="QQ 群" autocomplete="off" :disabled="loading || saving" />
          </label>
          <label class="block min-w-[140px] flex-1">
            <span class="mb-1 block text-2xs monitor-caption">{{ t('monitor.contactPageConfig.entryValue') }}</span>
            <input v-model="entry.value" type="text" maxlength="255" class="input w-full py-1.5 text-xs" autocomplete="off" :disabled="loading || saving" />
          </label>
          <label class="block min-w-[180px] flex-1">
            <span class="mb-1 block text-2xs monitor-caption">{{ t('monitor.contactPageConfig.entryHref') }}</span>
            <input v-model="entry.href" type="text" maxlength="2048" class="input w-full py-1.5 text-xs" placeholder="https:// / mailto:" autocomplete="off" :disabled="loading || saving" />
          </label>
          <label class="block min-w-[180px] flex-1">
            <span class="mb-1 block text-2xs monitor-caption">{{ t('monitor.contactPageConfig.entryQr') }}</span>
            <input v-model="entry.qr_image_url" type="text" maxlength="2048" class="input w-full py-1.5 text-xs" placeholder="https://... 或 /qr.png" autocomplete="off" :disabled="loading || saving" />
          </label>
          <button class="monitor-btn-secondary" :disabled="loading || saving" :title="t('monitor.contactPageConfig.removeEntry')" @click="removeContactEntry(index)">×</button>
        </div>
      </div>
    </div>

    <!-- ═══ Markdown 自由内容 ═══ -->
    <div class="mt-4">
      <span class="mb-1 block text-xs font-semibold monitor-section-title">{{ t('monitor.contactPageConfig.bodyMarkdown') }}</span>
      <textarea
        :value="form.body_markdown"
        rows="10"
        maxlength="20000"
        class="input w-full py-2 text-xs font-mono"
        :disabled="loading || saving"
        @input="updateForm('body_markdown', ($event.target as HTMLTextAreaElement).value)"
      />
      <p class="mt-1 text-2xs monitor-caption">{{ t('monitor.contactPageConfig.bodyMarkdownHint') }}</p>
    </div>

    <div class="mt-4 flex gap-2">
      <button class="monitor-btn-primary" :disabled="saving || loading" @click="emit('save')">
        {{ t(saving ? 'monitor.saving' : 'monitor.saveConfig') }}
      </button>
    </div>
  </div>
</template>
