<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { PushChannel } from '@/features/subscriptions/subscriptionsModel'
import type { TrackingSettings } from '@/features/tracking/trackingModel'

const props = defineProps<{ settings: TrackingSettings; channels: PushChannel[]; busy: boolean }>()
const emit = defineEmits<{ save: [settings: TrackingSettings] }>()
const { t } = useI18n()
const draft = ref({ ...props.settings })
watch(
  () => props.settings,
  (settings) => {
    draft.value = { ...settings }
  },
)
const available = computed(() => props.channels.filter((channel) => channel.verified && channel.status === 'active'))
const missingChannel = computed(
  () => draft.value.channel_id !== null && !available.value.some((channel) => channel.id === draft.value.channel_id),
)
</script>

<template>
  <form class="tracking-delivery" @submit.prevent="emit('save', draft)">
    <h3 class="font-bold">{{ t('tracking.deliveryTitle') }}</h3>
    <p class="tracking-hint">{{ t('tracking.deliveryHint') }}</p>
    <fieldset :disabled="busy" class="tracking-form-grid">
      <div class="tracking-field">
        <label for="tracking-hour">{{ t('tracking.deliveryTime') }}</label>
        <select id="tracking-hour" v-model.number="draft.delivery_hour" class="tracking-input">
          <option v-for="hour in 24" :key="hour" :value="hour - 1">{{ String(hour - 1).padStart(2, '0') }}:00</option>
        </select>
      </div>
      <div class="tracking-field">
        <label for="tracking-channel">{{ t('tracking.deliveryChannel') }}</label>
        <select id="tracking-channel" v-model="draft.channel_id" class="tracking-input">
          <option :value="null">{{ t('tracking.inAppOnly') }}</option>
          <option v-if="missingChannel" :value="draft.channel_id" disabled>{{ t('tracking.channelMissing') }}</option>
          <option v-for="channel in available" :key="channel.id" :value="channel.id">
            {{ channel.channel_type }} · {{ channel.target }}
          </option>
        </select>
      </div>
      <p v-if="!available.length" class="tracking-hint sm:col-span-2">{{ t('tracking.noChannels') }}</p>
      <div class="flex flex-wrap items-center justify-between gap-3 sm:col-span-2">
        <label class="inline-flex items-center gap-2 text-sm">
          <input v-model="draft.enabled" type="checkbox" class="accent-ink" />
          {{ t('tracking.enabled') }}
        </label>
        <button class="tracking-button" type="submit" :disabled="missingChannel">
          {{ t('tracking.saveDelivery') }}
        </button>
      </div>
    </fieldset>
  </form>
</template>
