import { api } from '@/services/http/apiClient'

export interface AttachmentMeta {
  id: string
  type: 'image' | 'pdf'
  status: 'uploading' | 'processing' | 'ready' | 'error' | 'expired'
  filename: string
  mime_type: string
  size_bytes: number
  page_count: number
  text_preview: string
  error_msg: string
}

export async function uploadImageAttachment(
  imageBase64: string,
  mimeType = 'image/jpeg',
  filename = '',
): Promise<AttachmentMeta> {
  const res = await api.post('/chat/attachments/image', {
    image_base64: imageBase64,
    mime_type: mimeType,
    filename,
  })
  return res.data
}

export async function uploadPdfAttachment(file: File): Promise<AttachmentMeta> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await api.post('/chat/attachments/pdf', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000,
  })
  return res.data
}

export async function getAttachmentStatus(attachmentId: string): Promise<AttachmentMeta> {
  const res = await api.get(`/chat/attachments/${attachmentId}`)
  return res.data
}
