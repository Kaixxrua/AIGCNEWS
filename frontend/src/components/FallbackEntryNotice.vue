<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { installFallbackEntryMessages } from '@/i18n/locales/fallbackEntry'
import { buildFallbackEntryUrl, fallbackEntryState } from '@/services/http/fallbackEntry'

installFallbackEntryMessages()

const route = useRoute()
const { t } = useI18n()
const { shouldOffer, dismiss } = fallbackEntryState
const fallbackHref = computed(() => buildFallbackEntryUrl(route.fullPath))
</script>

<template>
  <Teleport to="body">
    <!-- 与 AuthPromptHost 的降级提示同款卡片；放左下角避免与其右下角重叠。 -->
    <div v-if="shouldOffer" class="fixed inset-x-4 bottom-32 z-50 rounded-xl border border-amber-200 bg-white p-4 text-sm text-stone-700 shadow-xl sm:inset-x-auto sm:bottom-4 sm:left-4 sm:max-w-sm" role="status">
      <p>{{ t('fallbackEntry.message') }}</p>
      <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        <a :href="fallbackHref" class="font-medium text-stone-900 underline underline-offset-2">{{ t('fallbackEntry.open') }}</a>
        <button type="button" class="text-stone-500 underline underline-offset-2" @click="dismiss">{{ t('fallbackEntry.dismiss') }}</button>
      </div>
    </div>
  </Teleport>
</template>
