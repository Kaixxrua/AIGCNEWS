<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  formatDate,
  type TelegramConfig,
  type TelegramConfigForm,
} from '@/features/monitor/monitorViewModel'

const { t } = useI18n()

const props = defineProps<{
  config: TelegramConfig | null
  form: TelegramConfigForm
  loading: boolean
  saving: boolean
  resetting: boolean
  registeringWebhook: boolean
}>()

const emit = defineEmits<{
  save: []
  reset: []
  registerWebhook: []
}>()

const updateForm = <K extends keyof TelegramConfigForm>(field: K, value: TelegramConfigForm[K]) => {
  // eslint-disable-next-line vue/no-mutating-props -- form 为父组件传入的草稿对象，此处为受控表单的有意回写
  props.form[field] = value
}

const sourceBadge = (source: TelegramConfig['source'] | undefined) => {
  if (source === 'database') return { class: 'monitor-status-success', label: t('monitor.telegramPush.sourceDatabase') }
  if (source === 'environment') return { class: 'monitor-status-unknown', label: t('monitor.telegramPush.sourceEnvironment') }
  return { class: 'monitor-status-unknown', label: t('monitor.telegramPush.sourceUnconfigured') }
}
</script>

<template>
  <div class="stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.1s">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <svg class="h-4 w-4 monitor-caption" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.telegramPush.title') }}</h3>
      <span class="badge" :class="sourceBadge(config?.source).class">{{ sourceBadge(config?.source).label }}</span>
      <span class="badge" :class="form.enabled ? 'monitor-status-success' : 'monitor-status-unknown'">
        {{ t(form.enabled ? 'monitor.telegramPush.enabledOn' : 'monitor.telegramPush.enabledOff') }}
      </span>
      <span v-if="config?.updated_at" class="ml-auto text-2xs monitor-caption">{{ t('monitor.updatedAt', { date: formatDate(config.updated_at) }) }}</span>
    </div>

    <label class="mb-3 inline-flex items-center gap-1.5 text-xs monitor-caption">
      <input
        :checked="form.enabled"
        type="checkbox"
        class="rounded border-stone-300 text-stone-700 focus:ring-stone-400"
        :disabled="loading || saving || resetting || registeringWebhook"
        @change="updateForm('enabled', ($event.target as HTMLInputElement).checked)"
      />
      {{ t('monitor.telegramPush.enablePush') }}
      <span class="text-2xs">{{ t('monitor.telegramPush.secretWriteOnly') }}</span>
    </label>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <!-- Bot Token：只写入不回显；已配置时显示脱敏 badge，留空=保留，勾选清除=保存时擦除 -->
      <div>
        <div class="mb-1 flex items-center gap-2">
          <span class="text-xs monitor-caption">{{ t('monitor.telegramPush.botToken') }}</span>
          <span v-if="config?.bot_token_configured" class="badge monitor-status-success">{{ config.bot_token_masked }}</span>
          <label v-if="config?.bot_token_configured" class="inline-flex items-center gap-1 text-2xs monitor-caption">
            <input
              :checked="form.clear_bot_token"
              type="checkbox"
              class="rounded border-stone-300 text-stone-700 focus:ring-stone-400"
              :disabled="loading || saving || resetting || registeringWebhook"
              @change="updateForm('clear_bot_token', ($event.target as HTMLInputElement).checked)"
            />
            {{ t('monitor.telegramPush.clearSecret') }}
          </label>
        </div>
        <input
          :value="form.bot_token"
          type="password"
          class="input w-full py-2 text-xs"
          :placeholder="t('monitor.telegramPush.retainSecret')"
          autocomplete="new-password"
          :disabled="loading || saving || resetting || registeringWebhook"
          @input="updateForm('bot_token', ($event.target as HTMLInputElement).value)"
        />
        <span class="mt-1 block text-2xs monitor-caption">{{ t('monitor.telegramPush.botTokenHint') }}</span>
      </div>
      <label class="block">
        <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.telegramPush.botUsername') }}</span>
        <input
          :value="form.bot_username"
          type="text"
          class="input w-full py-2 text-xs"
          placeholder="aigc_news_bot"
          autocomplete="off"
          :disabled="loading || saving || resetting || registeringWebhook"
          @input="updateForm('bot_username', ($event.target as HTMLInputElement).value)"
        />
        <span class="mt-1 block text-2xs monitor-caption">{{ t('monitor.telegramPush.botUsernameHint') }}</span>
      </label>
      <div>
        <div class="mb-1 flex items-center gap-2">
          <span class="text-xs monitor-caption">{{ t('monitor.telegramPush.webhookSecret') }}</span>
          <span v-if="config?.webhook_secret_configured" class="badge monitor-status-success">{{ config.webhook_secret_masked }}</span>
          <label v-if="config?.webhook_secret_configured" class="inline-flex items-center gap-1 text-2xs monitor-caption">
            <input
              :checked="form.clear_webhook_secret"
              type="checkbox"
              class="rounded border-stone-300 text-stone-700 focus:ring-stone-400"
              :disabled="loading || saving || resetting || registeringWebhook"
              @change="updateForm('clear_webhook_secret', ($event.target as HTMLInputElement).checked)"
            />
            {{ t('monitor.telegramPush.clearSecret') }}
          </label>
        </div>
        <input
          :value="form.webhook_secret"
          type="password"
          class="input w-full py-2 text-xs"
          :placeholder="t('monitor.telegramPush.retainSecret')"
          autocomplete="new-password"
          :disabled="loading || saving || resetting || registeringWebhook"
          @input="updateForm('webhook_secret', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="grid grid-cols-2 gap-3">
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.telegramPush.linkTtl') }}</span>
          <input
            :value="form.link_ttl_seconds"
            type="number"
            min="60"
            max="3600"
            class="input w-full py-2 text-xs"
            autocomplete="off"
            :disabled="loading || saving || resetting || registeringWebhook"
            @input="updateForm('link_ttl_seconds', Number(($event.target as HTMLInputElement).value) || 0)"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs monitor-caption">{{ t('monitor.telegramPush.requestTimeout') }}</span>
          <input
            :value="form.request_timeout_seconds"
            type="number"
            min="1"
            max="30"
            step="0.5"
            class="input w-full py-2 text-xs"
            autocomplete="off"
            :disabled="loading || saving || resetting || registeringWebhook"
            @input="updateForm('request_timeout_seconds', Number(($event.target as HTMLInputElement).value) || 0)"
          />
        </label>
      </div>
    </div>

    <!-- Webhook 状态卡：GET 读路径附带 getWebhookInfo；注册由后端代调 setWebhook -->
    <div class="mt-4 border-t border-stone-200/60 pt-3 dark:border-stone-700/60">
      <div class="mb-2 flex flex-wrap items-center gap-2">
        <h4 class="text-xs font-semibold monitor-caption">{{ t('monitor.telegramPush.webhookTitle') }}</h4>
        <span class="badge" :class="config?.webhook?.url ? 'monitor-status-success' : 'monitor-status-unknown'">
          {{ t(config?.webhook?.url ? 'monitor.telegramPush.webhookRegisteredBadge' : 'monitor.telegramPush.webhookNotRegistered') }}
        </span>
        <button
          class="monitor-btn-secondary ml-auto"
          :disabled="loading || saving || resetting || registeringWebhook"
          @click="emit('registerWebhook')"
        >
          {{ t(registeringWebhook ? 'monitor.telegramPush.webhookRegistering' : 'monitor.telegramPush.webhookRegister') }}
        </button>
      </div>
      <dl v-if="config?.webhook" class="grid grid-cols-1 gap-1 text-2xs monitor-caption md:grid-cols-[auto_1fr] md:gap-x-3">
        <dt class="font-semibold">{{ t('monitor.telegramPush.webhookUrl') }}</dt>
        <dd class="break-all">{{ config.webhook.url || '—' }}</dd>
        <dt class="font-semibold">{{ t('monitor.telegramPush.webhookPending') }}</dt>
        <dd>{{ config.webhook.pending_update_count ?? '—' }}</dd>
        <dt class="font-semibold">{{ t('monitor.telegramPush.webhookLastError') }}</dt>
        <dd class="break-all">{{ config.webhook.last_error_message || '—' }}</dd>
      </dl>
      <p v-else class="text-2xs monitor-caption">{{ t('monitor.telegramPush.webhookStatusUnavailable') }}</p>
    </div>

    <div class="mt-4 flex flex-wrap items-center gap-2">
      <button class="monitor-btn-primary" :disabled="saving || loading || resetting || registeringWebhook" @click="emit('save')">
        {{ t(saving ? 'monitor.saving' : 'monitor.saveConfig') }}
      </button>
      <!-- 删除 DB 覆盖行：整体回落环境变量；无覆盖行时等价于确认当前 env 口径 -->
      <button class="monitor-btn-secondary" :disabled="resetting || loading || saving || registeringWebhook" @click="emit('reset')">
        {{ t(resetting ? 'monitor.telegramPush.resetting' : 'monitor.telegramPush.resetToEnv') }}
      </button>
    </div>

    <div class="mt-3 text-xs monitor-caption monitor-check-row px-3 py-2">
      <span>{{ t('monitor.telegramPush.hint') }}</span>
    </div>
  </div>
</template>
