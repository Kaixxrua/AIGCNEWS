import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useChatAttachments } from './useChatAttachments'

const calls = vi.hoisted(() => ({ uploadImage: vi.fn(), add: vi.fn(), toast: vi.fn() }))
vi.mock('@/stores/chatStore', () => ({ useChatStore: () => ({ addPendingAttachment: calls.add }) }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ isLoggedIn: true }) }))
vi.mock('@/composables/useLoginPrompt', () => ({ useLoginPrompt: () => ({ requestLogin: vi.fn() }) }))
vi.mock('@/composables/useToast', () => ({ showToast: calls.toast }))
vi.mock('@/i18n', () => ({ i18n: { global: { t: (key: string) => key } } }))
vi.mock('@/services/attachments/attachmentApi', () => ({ uploadImageAttachment: calls.uploadImage }))

describe('Image-only chat attachments', () => {
  it('rejects a PDF before any upload and clears the file input', async () => {
    const input = { files: [new File(['%PDF-1.7'], 'paper.pdf', { type: 'application/pdf' })], value: 'paper.pdf' }
    const attachments = useChatAttachments(ref('Question'))
    await attachments.handleFileChange({ target: input } as unknown as Event)
    expect(calls.uploadImage).not.toHaveBeenCalled()
    expect(calls.add).not.toHaveBeenCalled()
    expect(calls.toast).toHaveBeenCalledWith('chat.attachmentsUnsupported')
    expect(input.value).toBe('')
    expect(attachments.isUploading.value).toBe(false)
  })
})
