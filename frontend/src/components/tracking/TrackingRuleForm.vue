<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { SUBSCRIPTION_SOURCES } from '@/features/subscriptions/subscriptionsModel'
import { emptyRule, ruleInput } from '@/features/tracking/trackingModel'
import type { TrackingRule, TrackingRuleInput } from '@/features/tracking/trackingModel'

const props = defineProps<{ rule?: TrackingRule; busy: boolean }>()
const emit = defineEmits<{ save: [input: TrackingRuleInput]; cancel: [] }>()
const { t } = useI18n()
const draft = ref(emptyRule())
const excludes = ref('')
const queryField = ref<HTMLInputElement>()
watch(
  () => props.rule,
  (row) => {
    draft.value = row ? ruleInput(row) : emptyRule()
    excludes.value = draft.value.excludes.join(', ')
  },
  { immediate: true },
)
onMounted(() => queryField.value?.focus())
function submit() {
  const terms = excludes.value
    .split(/[,，]/)
    .map((term) => term.trim())
    .filter(Boolean)
  emit('save', { ...draft.value, excludes: [...new Set(terms)] })
}
</script>

<template>
  <form class="tracking-rule-form" @submit.prevent="submit">
    <h3 class="font-bold">{{ t(rule ? 'tracking.editRule' : 'tracking.addRule') }}</h3>
    <fieldset :disabled="busy" class="tracking-form-grid">
      <div class="tracking-field">
        <label for="tracking-kind">{{ t('tracking.kind') }}</label>
        <select id="tracking-kind" v-model="draft.kind" class="tracking-input">
          <option value="keyword">{{ t('tracking.keyword') }}</option>
          <option value="project">{{ t('tracking.project') }}</option>
        </select>
      </div>
      <div class="tracking-field">
        <label for="tracking-query">{{
          t(draft.kind === 'project' ? 'tracking.repository' : 'tracking.keywords')
        }}</label>
        <input
          id="tracking-query"
          ref="queryField"
          v-model="draft.query"
          class="tracking-input"
          required
          maxlength="120"
          :placeholder="draft.kind === 'project' ? 'ollama/ollama' : 'RAG'"
          aria-describedby="tracking-query-hint"
        />
      </div>
      <p id="tracking-query-hint" class="tracking-hint sm:col-span-2">
        {{ t(draft.kind === 'project' ? 'tracking.projectHint' : 'tracking.keywordHint') }}
      </p>
      <div v-if="draft.kind === 'keyword'" class="tracking-field">
        <label for="tracking-source">{{ t('tracking.source') }}</label>
        <select id="tracking-source" v-model="draft.source" class="tracking-input">
          <option v-for="source in SUBSCRIPTION_SOURCES" :key="source" :value="source">
            {{ t('subscriptions.sources.' + source) }}
          </option>
        </select>
      </div>
      <div v-else class="tracking-field">
        <label for="tracking-threshold">{{ t('tracking.threshold') }}</label>
        <input
          id="tracking-threshold"
          v-model.number="draft.star_threshold"
          class="tracking-input"
          type="number"
          min="1"
          max="100000"
          required
        />
      </div>
      <div class="tracking-field">
        <label for="tracking-excludes">{{ t('tracking.excludes') }}</label>
        <input
          id="tracking-excludes"
          v-model="excludes"
          class="tracking-input"
          maxlength="410"
          :placeholder="t('tracking.excludesPlaceholder')"
          aria-describedby="tracking-excludes-hint"
        />
        <p id="tracking-excludes-hint" class="tracking-hint">{{ t('tracking.excludesHint') }}</p>
      </div>
      <div class="flex flex-wrap gap-2 sm:col-span-2">
        <button type="submit" class="tracking-button tracking-button-primary" :disabled="!draft.query.trim()">
          {{ t(busy ? 'common.processing' : 'common.save') }}
        </button>
        <button type="button" class="tracking-button" @click="emit('cancel')">{{ t('common.cancel') }}</button>
      </div>
    </fieldset>
  </form>
</template>
