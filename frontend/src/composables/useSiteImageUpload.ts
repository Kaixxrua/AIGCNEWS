import { ref } from 'vue'
import { showToast } from '@/composables/useToast'
import { i18n } from '@/i18n'
import { monitorApi } from '@/services/monitor/monitorApi'

const ALLOWED_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])
const MAX_IMAGE_BYTES = 10 * 1024 * 1024

/**
 * 站点公开素材上传（联系合作页二维码 / Markdown 正文插图）。
 * 客户端先做类型与大小预检（与后端 attachment_policy 同口径），
 * 成功返回站内 /api/media/site/... 相对路径；失败 toast，不抛错。
 */
export const useSiteImageUpload = () => {
  const uploading = ref(false)

  const uploadImage = async (file: File): Promise<string | null> => {
    if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
      showToast(i18n.global.t('monitor.contactPageConfig.unsupportedImageType'))
      return null
    }
    if (file.size > MAX_IMAGE_BYTES) {
      showToast(i18n.global.t('monitor.contactPageConfig.imageTooLarge'))
      return null
    }
    uploading.value = true
    try {
      const result = await monitorApi.uploadSiteImage(file)
      return result.url
    } catch (error) {
      console.error('[Site image upload error]', error)
      showToast(i18n.global.t('monitor.contactPageConfig.uploadFailed'))
      return null
    } finally {
      uploading.value = false
    }
  }

  return { uploading, uploadImage }
}
