<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import { getErrorDetail } from '@/features/auth/authViewModel'
import UserAvatar from './UserAvatar.vue'
import AuthFeedback from './AuthFeedback.vue'

const { t } = useI18n()
const auth = useAuthStore()
const input = ref<HTMLInputElement | null>(null)
const selected = ref<File | null>(null)
const preview = ref('')
const uploading = ref(false)
const error = ref('')
const success = ref('')
const name = computed(() => auth.user?.username?.trim() || auth.user?.email || '')
const clearSelection = () => {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
  selected.value = null
  if (input.value) input.value.value = ''
}
onBeforeUnmount(clearSelection)

const selectFile = (event: Event) => {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  clearSelection()
  error.value = ''; success.value = ''
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    error.value = t('auth.avatarInvalidType'); return
  }
  if (!file.size || file.size > 2 * 1024 * 1024) {
    error.value = t('auth.avatarTooLarge'); return
  }
  selected.value = file
  preview.value = URL.createObjectURL(file)
}
const save = async () => {
  if (!selected.value || uploading.value) return
  uploading.value = true
  error.value = ''; success.value = ''
  try {
    await auth.updateAvatar(selected.value)
    clearSelection()
    success.value = t('auth.avatarSaved')
  } catch (reason: unknown) {
    error.value = getErrorDetail(reason, t('auth.avatarFailed'))
  } finally { uploading.value = false }
}
</script>

<template>
  <section aria-labelledby="account-avatar-title" class="avatar-upload" :aria-busy="uploading">
    <UserAvatar :src="preview || auth.user?.avatar_url" :name="name" :seed="auth.user?.user_id" class="avatar-upload__preview" />
    <div class="avatar-upload__content">
      <h4 id="account-avatar-title">{{ t('auth.avatar') }}</h4>
      <p class="monitor-caption">{{ t('auth.avatarHint') }}</p>
      <input id="account-avatar-file" ref="input" type="file" accept="image/png,image/jpeg,image/webp" class="sr-only" :aria-label="t('auth.uploadAvatar')" :disabled="uploading" @change="selectFile" />
      <div class="avatar-upload__actions">
        <button type="button" class="btn-secondary" :disabled="uploading" @click="input?.click()">{{ t('auth.uploadAvatar') }}</button>
        <template v-if="selected">
          <button type="button" class="btn-primary" :disabled="uploading" @click="save">{{ uploading ? t('auth.avatarUploading') : t('auth.avatarSave') }}</button>
          <button type="button" class="btn-secondary" :disabled="uploading" @click="clearSelection">{{ t('common.cancel') }}</button>
        </template>
      </div>
      <AuthFeedback :message="error" type="error" />
      <AuthFeedback :message="success" type="success" />
    </div>
  </section>
</template>

<style scoped>
.avatar-upload { display: flex; align-items: flex-start; gap: 16px; padding-bottom: 20px; border-bottom: 1px solid var(--rule); }
.avatar-upload__preview { width: 64px; height: 64px; font-size: 28px; }
.avatar-upload__content { flex: 1; min-width: 0; }
.avatar-upload h4 { font-size: 13px; font-weight: 700; color: var(--ink); }
.avatar-upload p { margin-top: 4px; font-size: 12px; }
.avatar-upload__actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.avatar-upload__actions button { font-size: 12px; }
</style>
