import { ref, type Ref } from 'vue'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useAuthStore } from '@/stores/authStore'
import { useChatStore } from '@/stores/chatStore'
import { showToast } from '@/composables/useToast'
import { i18n } from '@/i18n'
import {
  getAttachmentStatus,
  uploadImageAttachment,
  uploadPdfAttachment,
  type AttachmentMeta,
} from '@/services/attachments/attachmentApi'

export const useChatAttachments = (inputText: Ref<string>) => {
  const store = useChatStore()
  const authStore = useAuthStore()
  const { requestLogin } = useLoginPrompt()
  const isUploading = ref(false)
  const attachmentMetas = ref<AttachmentMeta[]>([])

  const removeAttachment = (attachmentId: string) => {
    store.removePendingAttachment(attachmentId)
    attachmentMetas.value = attachmentMetas.value.filter((item) => item.id !== attachmentId)
  }

  const refreshAttachmentStatus = async (attachmentId: string) => {
    try {
      const latest = await getAttachmentStatus(attachmentId)
      attachmentMetas.value = attachmentMetas.value.map((item) => item.id === attachmentId ? latest : item)
    } catch (error) {
      console.error('[Attachment status error]', error)
    }
  }

  const handleFileChange = async (event: Event) => {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    if (!file) return

    if (!authStore.isLoggedIn) {
      authStore.savePendingMessage(inputText.value.trim())
      requestLogin('/chat')
      input.value = ''
      return
    }

    isUploading.value = true
    try {
      let meta: AttachmentMeta
      if (file.type.startsWith('image/')) {
        const fileReader = new FileReader()
        const dataUrl = await new Promise<string>((resolve, reject) => {
          fileReader.onload = () => resolve(String(fileReader.result ?? ''))
          fileReader.onerror = reject
          fileReader.readAsDataURL(file)
        })
        meta = await uploadImageAttachment(dataUrl, file.type, file.name)
      } else if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
        meta = await uploadPdfAttachment(file)
      } else {
        showToast(i18n.global.t('chat.attachmentsUnsupported'))
        input.value = ''
        return
      }

      store.addPendingAttachment(meta.id)
      attachmentMetas.value = [...attachmentMetas.value, meta]

      if (meta.status === 'processing') {
        window.setTimeout(() => {
          void refreshAttachmentStatus(meta.id)
        }, 1500)
      }
    } catch (error) {
      console.error('[Attachment upload error]', error)
      showToast(i18n.global.t('chat.attachmentUploadFailed'))
    } finally {
      isUploading.value = false
      input.value = ''
    }
  }

  const clearAttachmentMetas = () => {
    attachmentMetas.value = []
  }

  return {
    isUploading,
    attachmentMetas,
    removeAttachment,
    handleFileChange,
    clearAttachmentMetas,
  }
}
