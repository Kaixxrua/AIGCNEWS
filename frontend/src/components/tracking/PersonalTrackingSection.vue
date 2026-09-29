<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { BellRing, CalendarClock, Check, Crown, Plus, Radar, RefreshCw, Zap } from 'lucide-vue-next'
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
const isMember = computed(() => (data.value?.limit ?? 1) > 1)
const activeRules = computed(() => data.value?.rules.filter((rule) => rule.active).length ?? 0)
const latestMatches = computed(() => data.value?.digests[0]?.items.length ?? 0)
const nextRun = computed(() => {
  if (!data.value?.settings.enabled) return t('tracking.statusPaused')
  return `${String(data.value.settings.delivery_hour).padStart(2, '0')}:00`
})
const quotaPercent = computed(() => {
  if (!data.value) return 0
  return Math.min(100, Math.round((data.value.rules.length / data.value.limit) * 100))
})
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
  <section id="personal-tracking" class="tracking-section shrink-0" aria-labelledby="tracking-title">
    <p v-if="error" role="alert" class="tracking-error">{{ t('tracking.errors.' + error) }}</p>
    <p v-if="notice" role="status" class="tracking-hint">{{ t('tracking.saved') }}</p>
    <p v-if="loading && !data" role="status" aria-busy="true" class="tracking-loading">
      {{ t('common.loading') }}
    </p>
    <template v-if="data">
      <section class="tracking-hero" :class="{ 'tracking-hero--member': isMember }">
        <div class="tracking-radar" aria-hidden="true"><span></span><span></span><span></span><i></i></div>
        <div class="tracking-hero__content">
          <div class="flex flex-wrap items-center gap-2">
            <span class="tracking-plan"
              ><Crown v-if="isMember" class="h-3.5 w-3.5" />{{
                t(isMember ? 'tracking.vipPlan' : 'tracking.freePlan')
              }}</span
            >
            <span class="tracking-live"
              ><i></i>{{ t(data.settings.enabled ? 'tracking.running' : 'tracking.statusPaused') }}</span
            >
          </div>
          <h2 id="tracking-title" class="mt-4 text-2xl font-black tracking-[-0.035em] sm:text-3xl">
            {{ t(isMember ? 'tracking.vipHeadline' : 'tracking.freeHeadline') }}
          </h2>
          <p class="mt-2 max-w-xl text-sm leading-relaxed text-ink-secondary">
            {{ t(isMember ? 'tracking.vipDescription' : 'tracking.freeDescription') }}
          </p>
          <div class="mt-5 flex flex-wrap gap-2">
            <button
              ref="addButton"
              type="button"
              class="tracking-button tracking-button-primary"
              :disabled="busy || atLimit"
              @click="openForm()"
            >
              <Plus class="h-4 w-4" aria-hidden="true" />{{ t('tracking.addRule') }}
            </button>
            <RouterLink v-if="!isMember" to="/membership" class="tracking-button tracking-upgrade">
              <Zap class="h-4 w-4" />{{ t('tracking.upgradeAction') }}
            </RouterLink>
          </div>
        </div>
        <div class="tracking-stats">
          <div>
            <span>{{ activeRules }}</span
            ><small>{{ t('tracking.activeRules') }}</small>
          </div>
          <div>
            <span>{{ latestMatches }}</span
            ><small>{{ t('tracking.latestMatches') }}</small>
          </div>
          <div>
            <span>{{ nextRun }}</span
            ><small>{{ t('tracking.nextDigest') }}</small>
          </div>
        </div>
      </section>

      <div class="tracking-grid">
        <section class="tracking-panel tracking-rules-panel" aria-labelledby="tracking-rules-title">
          <header class="tracking-panel__header">
            <div>
              <p class="tracking-kicker">{{ t('tracking.rulesKicker') }}</p>
              <h3 id="tracking-rules-title">{{ t('tracking.rulesTitle') }}</h3>
            </div>
            <button
              type="button"
              class="tracking-icon-button"
              :aria-label="t('common.refresh')"
              :disabled="loading || busy"
              @click="ctl.load()"
            >
              <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
            </button>
          </header>
          <div class="tracking-usage">
            <div class="flex items-center justify-between gap-3">
              <span>{{ t('tracking.quota', { used: data.rules.length, limit: data.limit }) }}</span
              ><strong>{{ quotaPercent }}%</strong>
            </div>
            <div class="tracking-usage__bar"><i :style="{ width: quotaPercent + '%' }"></i></div>
          </div>
          <p v-if="atLimit" class="tracking-limit">
            {{ t('tracking.limitHint')
            }}<RouterLink v-if="!isMember" to="/membership">{{ t('tracking.upgrade') }}</RouterLink>
          </p>
          <div v-if="!data.rules.length" class="tracking-empty">
            <Radar class="h-7 w-7" /><strong>{{ t('tracking.emptyTitle') }}</strong
            ><span>{{ t('tracking.emptyRules') }}</span>
          </div>
          <ul v-else class="tracking-rules">
            <li v-for="rule in data.rules" :key="rule.id">
              <div class="tracking-rule-main min-w-0">
                <span class="tracking-rule-icon"><Radar class="h-4 w-4" /></span>
                <div class="min-w-0">
                  <p class="font-extrabold break-words">{{ rule.query }}</p>
                  <!-- 桌面漫画版把每一项画成小标签、隐藏间隔点；窄屏仍是一行「关键词 · 来源 · 状态」。 -->
                  <p class="tracking-hint tracking-rule-meta mt-1">
                    <span>{{ t('tracking.' + rule.kind) }}</span><span class="tracking-rule-sep"> · </span
                    ><span>{{ t('subscriptions.sources.' + rule.source) }}</span
                    ><template v-if="rule.kind === 'project'"
                      ><span class="tracking-rule-sep"> · </span><span>+{{ rule.star_threshold }} Stars</span></template
                    ><span class="tracking-rule-sep"> · </span
                    ><span class="tracking-rule-status" :class="{ 'is-active': rule.active }">{{
                      t(
                        rule.active
                          ? 'tracking.active'
                          : rule.enabled && data.settings.enabled
                            ? 'tracking.overLimit'
                            : 'tracking.paused',
                      )
                    }}</span>
                  </p>
                  <p v-if="rule.excludes.length" class="tracking-hint tracking-rule-excludes mt-1">
                    {{ t('tracking.excluding', { terms: rule.excludes.join(' / ') }) }}
                  </p>
                </div>
              </div>
              <div class="tracking-rule-actions flex flex-wrap gap-2">
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
        </section>

        <aside class="tracking-panel tracking-plan-panel" :class="{ 'tracking-plan-panel--member': isMember }">
          <p class="tracking-kicker">{{ t('tracking.planKicker') }}</p>
          <h3>{{ t(isMember ? 'tracking.vipBenefitsTitle' : 'tracking.unlockTitle') }}</h3>
          <p class="tracking-hint mt-2">{{ t(isMember ? 'tracking.vipBenefitsHint' : 'tracking.unlockHint') }}</p>
          <ul class="tracking-benefits">
            <li><Check />{{ t('tracking.benefitRules') }}</li>
            <li><Check />{{ t('tracking.benefitPreserve') }}</li>
            <li><Check />{{ t('tracking.benefitQuota') }}</li>
          </ul>
          <RouterLink v-if="!isMember" to="/membership" class="tracking-button tracking-button-primary w-full"
            ><Crown class="h-4 w-4" />{{ t('tracking.viewVip') }}</RouterLink
          >
          <div v-else class="tracking-member-active"><Check class="h-4 w-4" />{{ t('tracking.vipActive') }}</div>
        </aside>
      </div>

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
        <section class="tracking-panel tracking-digest-panel">
          <p class="tracking-kicker"><BellRing class="h-3.5 w-3.5" />{{ t('tracking.resultsKicker') }}</p>
          <TrackingDigestHistory :digests="data.digests" @viewed="unread.markRead" />
        </section>
        <section class="tracking-panel tracking-delivery-panel">
          <p class="tracking-kicker"><CalendarClock class="h-3.5 w-3.5" />{{ t('tracking.deliveryKicker') }}</p>
          <TrackingDeliveryForm :settings="data.settings" :channels="channels" :busy="busy" @save="ctl.saveSettings" />
        </section>
      </div>
    </template>
  </section>
</template>

<style src="./tracking.css"></style>
