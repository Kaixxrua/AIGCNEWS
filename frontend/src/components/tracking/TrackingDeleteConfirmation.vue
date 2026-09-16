<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TrackingRule } from '@/features/tracking/trackingModel'

defineProps<{ rule: TrackingRule; busy: boolean }>()
defineEmits<{ confirm: []; cancel: [] }>()
const { t } = useI18n()
const cancelButton = ref<HTMLButtonElement>()
onMounted(() => cancelButton.value?.focus())
</script>

<template>
  <div
    role="alertdialog"
    aria-modal="false"
    aria-labelledby="tracking-delete-prompt"
    class="tracking-preview"
    @keydown.esc="$emit('cancel')"
  >
    <p id="tracking-delete-prompt" class="font-bold">{{ t('tracking.deleteConfirm', { query: rule.query }) }}</p>
    <div class="mt-3 flex flex-wrap gap-2">
      <button class="tracking-button tracking-button-primary" type="button" :disabled="busy" @click="$emit('confirm')">
        {{ t('common.confirm') }}
      </button>
      <button ref="cancelButton" class="tracking-button" type="button" :disabled="busy" @click="$emit('cancel')">
        {{ t('common.cancel') }}
      </button>
    </div>
  </div>
</template>
