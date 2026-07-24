import { ref, useTemplateRef, type Ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'
import { useChatStore } from '../stores/chatStore'
import {
  getAttachmentStatus,
  uploadImageAttachment,
  uploadPdfAttachment,
  type AttachmentMeta,
} from '../services/api'

export const useChatAttachments = (inputText: Ref<string>) => {
  const store = useChatStore()
  const authStore = useAuthStore()
  const router = useRouter()
  const isUploading = ref(false)
  const fileInputRef = useTemplateRef<HTMLInputElement>('fileInputRef')
  const attachmentMetas = ref<AttachmentMeta[]>([])

  const openFilePicker = () => {
    fileInputRef.value?.click()
  }

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
      router.push({ path: '/login', query: { redirect: '/chat' } })
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
        alert('仅支持图片或 PDF 文件')
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
      alert('附件上传失败，请稍后重试')
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
    fileInputRef,
    attachmentMetas,
    openFilePicker,
    removeAttachment,
    handleFileChange,
    clearAttachmentMetas,
  }
}
