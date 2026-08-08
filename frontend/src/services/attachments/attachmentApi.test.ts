import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('../http/apiClient', () => ({ api: transport }))

import { uploadImageAttachment } from './attachmentApi'

describe('Attachment API transport contract', () => {
  beforeEach(() => {
    transport.post.mockReset()
  })

  it('posts image attachments with the base64 payload shape', async () => {
    transport.post.mockResolvedValueOnce({ data: { id: 'attachment' } })
    await uploadImageAttachment('base64-data', 'image/png', 'image.png')
    expect(transport.post).toHaveBeenLastCalledWith('/chat/attachments/image', {
      image_base64: 'base64-data',
      mime_type: 'image/png',
      filename: 'image.png',
    })
  })
})
