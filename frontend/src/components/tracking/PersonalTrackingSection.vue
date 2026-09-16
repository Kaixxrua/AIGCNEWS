<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Radar, Plus, RefreshCw } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useTrackingUnreadStore } from '@/stores/trackingUnreadStore'
import { usePersonalTracking } from '@/composables/usePersonalTracking'
import type { PushChannel } from '@/features/subscriptions/subscriptionsModel'
import type { TrackingRule, TrackingRuleInput } from '@/features/tracking/trackingModel'
import TrackingRuleForm from './TrackingRuleForm.vue'
import TrackingDeliveryForm from './TrackingDeliveryForm.vue'
import TrackingResults from './TrackingResults.vue'
import TrackingDigestHistory from './TrackingDigestHistory.vue'
import TrackingDeleteConfirmation from './TrackingDeleteConfirmation.vue'

defineProps<{ channels: PushChannel[] }>()
const { t } = useI18n()
const auth = useAuthStore()
const unread = useTrackingUnreadStore()
const ctl = usePersonalTracking()
const { data, loading, busy, error, notice, preview, previewTitle, atLimit } = ctl
const formOpen = ref(false)
const editing = ref<TrackingRule>()
const deleting = ref<TrackingRule>()
const addButton = ref<HTMLButtonElement>()
watch(
  () => auth.token,
  () => {
    formOpen.value = false
    deleting.value = undefined
    void ctl.load(true)
  },
)
onMounted(() => {
  void ctl.load()
})
function openForm(rule?: TrackingRule) {
  editing.value = rule
  formOpen.value = true
}
async function closeForm() {
  formOpen.value = false
  await nextTick()
  addButton.value?.focus()
}
async function saveRule(input: TrackingRuleInput) {
  if (await ctl.saveRule(input, editing.value?.id)) await closeForm()
}
async function removeRule() {
  if (deleting.value && (await ctl.remove(deleting.value.id))) await closeDelete()
}
async function closeDelete() {
  deleting.value = undefined
  await nextTick()
  addButton.value?.focus()
}
</script>

<template>
  <section id="personal-tracking" class="tracking-section glass-card shrink-0" aria-labelledby="tracking-title">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id="tracking-title" class="flex items-center gap-2 text-lg font-bold">
          <Radar class="h-5 w-5" />{{ t('tracking.title') }}
        </h2>
        <p class="tracking-hint mt-1">{{ t('tracking.description') }}</p>
      </div>
      <button type="button" class="tracking-button" :disabled="loading || busy" @click="ctl.load()">
        <RefreshCw class="h-3.5 w-3.5" aria-hidden="true" />{{ t('common.refresh') }}
      </button>
    </header>
    <p v-if="error" role="alert" class="tracking-error">{{ t('tracking.errors.' + error) }}</p>
    <p v-if="notice" role="status" class="tracking-hint">{{ t('tracking.saved') }}</p>
    <p v-if="loading && !data" role="status" aria-busy="true" class="tracking-loading">
      {{ t('common.loading') }}
    </p>
    <template v-if="data">
      <div class="tracking-toolbar">
        <div class="flex flex-wrap items-center gap-2">
          <span class="tracking-quota">{{ t('tracking.quota', { used: data.rules.length, limit: data.limit }) }}</span>
          <RouterLink v-if="data.limit === 1" to="/membership" class="text-sm font-bold underline underline-offset-4">{{
            t('tracking.upgrade')
          }}</RouterLink>
        </div>
        <button
          ref="addButton"
          type="button"
          class="tracking-button tracking-button-primary"
          :disabled="busy || atLimit"
          @click="openForm()"
        >
          <Plus class="h-4 w-4" aria-hidden="true" />{{ t('tracking.addRule') }}
        </button>
      </div>
      <p v-if="atLimit" class="tracking-hint">{{ t('tracking.limitHint') }}</p>
      <p v-if="!data.rules.length" class="tracking-empty">{{ t('tracking.emptyRules') }}</p>
      <ul v-else class="tracking-rules">
        <li v-for="rule in data.rules" :key="rule.id">
          <div class="min-w-0">
            <p class="font-bold break-words">{{ rule.query }}</p>
            <p class="tracking-hint mt-1">
              {{ t('tracking.' + rule.kind) }} · {{ t('subscriptions.sources.' + rule.source) }}
              <span v-if="rule.kind === 'project'"> · +{{ rule.star_threshold }} Stars</span>
              ·
              {{
                t(
                  rule.active
                    ? 'tracking.active'
                    : rule.enabled && data.settings.enabled
                      ? 'tracking.overLimit'
                      : 'tracking.paused',
                )
              }}
            </p>
            <p v-if="rule.excludes.length" class="tracking-hint mt-1">
              {{ t('tracking.excluding', { terms: rule.excludes.join(' / ') }) }}
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              class="tracking-button"
              type="button"
              :disabled="busy || !rule.active"
              @click="ctl.showPreview(rule)"
            >
              {{ t('tracking.preview') }}
            </button>
            <button class="tracking-button" type="button" :disabled="busy" @click="openForm(rule)">
              {{ t('common.edit') }}
            </button>
            <button class="tracking-button" type="button" :disabled="busy" @click="ctl.toggle(rule)">
              {{ t(rule.enabled ? 'tracking.pause' : 'tracking.resume') }}
            </button>
            <button class="tracking-button" type="button" :disabled="busy" @click="deleting = rule">
              {{ t('common.delete') }}
            </button>
          </div>
        </li>
      </ul>
      <TrackingDeleteConfirmation
        v-if="deleting"
        :rule="deleting"
        :busy="busy"
        @confirm="removeRule"
        @cancel="closeDelete"
      />
      <TrackingRuleForm
        v-if="formOpen"
        :key="editing?.id ?? 'new'"
        :rule="editing"
        :busy="busy"
        @save="saveRule"
        @cancel="closeForm"
      />
      <div v-if="preview" class="tracking-preview" aria-live="polite">
        <h3 class="font-bold">{{ t('tracking.previewTitle', { query: previewTitle }) }}</h3>
        <p class="tracking-hint mt-1">{{ t('tracking.previewHint') }}</p>
        <TrackingResults :items="preview.items" :truncated="preview.truncated" preview />
      </div>
      <div class="tracking-bottom">
        <TrackingDeliveryForm :settings="data.settings" :channels="channels" :busy="busy" @save="ctl.saveSettings" />
        <TrackingDigestHistory :digests="data.digests" @viewed="unread.markRead" />
      </div>
    </template>
  </section>
</template>

<style src="./tracking.css"></style>
