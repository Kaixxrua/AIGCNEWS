import { describe, expect, it } from 'vitest'
import chatStoreSource from './chatStore.ts?raw'
import chatStreamBoundarySource from '../features/chat/chatStreamBoundary.ts?raw'

function sourceBetween(source: string, start: string, end: string): string {
  const startIndex = source.indexOf(start)
  const endIndex = source.indexOf(end, startIndex + start.length)
  expect(startIndex, `missing source boundary: ${start}`).toBeGreaterThanOrEqual(0)
  expect(endIndex, `missing source boundary: ${end}`).toBeGreaterThan(startIndex)
  return source.slice(startIndex, endIndex)
}

function expectInOrder(source: string, fragments: string[]) {
  let cursor = -1
  for (const fragment of fragments) {
    const next = source.indexOf(fragment, cursor + 1)
    expect(next, `expected after offset ${cursor}: ${fragment}`).toBeGreaterThan(cursor)
    cursor = next
  }
}

describe('chat concurrency extraction contracts', () => {
  it('delegates optimistic deletion and deterministic global fallback to the lifecycle coordinator', () => {
    const action = sourceBetween(
      chatStoreSource,
      'async deleteActiveConversation()',
      'addPendingAttachment(',
    )

    expectInOrder(action, [
      'await coordinator.deleteConversation(convId)',
      "await coordinator.replaceConversationList({ scope: 'global' })",
      "const aTime = a.updatedAt ?? a.createdAt ?? ''",
      "return bTime.localeCompare(aTime) || a.id.localeCompare(b.id)",
      'await coordinator.selectConversation(fallback.id)',
    ])
    expect(action).toContain("await coordinator.createAndSelect({ scope: 'global' })")
    expect(action).not.toContain('catch')
  })

  it('keeps abort ownership and attachment consumption at explicit store seams', () => {
    const abortAction = sourceBetween(chatStoreSource, 'abortGeneration()', 'async deleteMessage(')
    expect(abortAction).toContain('coordinatorFor(this as ChatStoreContext).abortActiveRun()')

    const sendAction = sourceBetween(chatStoreSource, 'async sendMessage(', 'async _streamToAssistant(')
    expectInOrder(sendAction, [
      'const attachments = [...this.pendingAttachments]',
      'this.clearPendingAttachments()',
      'attachments,',
      'await this._streamToAssistant({',
      'attachments,',
    ])
  })

  it('keeps global and paper conversation state isolated at the public action boundary', () => {
    const paperFetch = sourceBetween(
      chatStoreSource,
      'async fetchPaperConversation(',
      'async loadPaperConversations(',
    )
    expect(paperFetch).not.toContain('this.activeConversationId =')
    expect(paperFetch).not.toContain('this.activeScope =')

    const sendAction = sourceBetween(chatStoreSource, 'async sendMessage(', 'async _streamToAssistant(')
    expect(sendAction).toContain('conversation = this.conversationMap[paperConversationId] ?? null')
    expect(sendAction).toContain("conversation = await this.ensureGlobalConversation(trimmed || '新对话')")
    expect(sendAction).not.toContain('this.activeConversationId =')

    const streamAction = sourceBetween(chatStoreSource, 'async _streamToAssistant(', '\n    },\n  },')
    expect(streamAction).toContain("scope: this.conversationMap[params.conversationId]?.scope ?? 'global'")
  })

  it('keeps stream callback ownership on captured conversation and assistant IDs', () => {
    const streamAction = sourceBetween(chatStoreSource, 'async _streamToAssistant(', '\n    },\n  },')

    expect(streamAction).toContain('coordinator.startStreamRun({')
    expect(streamAction).toContain('onEvent: (payload: unknown) => {')
    expect(streamAction).toContain('onDone: () => {')
    expect(streamAction).toContain('onError: (error: unknown) => {')
    expect(streamAction).toContain('onAbort: (_reason, context) => {')
    expect(streamAction).toContain('this.patchMessage(params.conversationId, params.assistantTempId, {')
    expect(streamAction).toContain('this.patchMessage(context.conversationId, context.messageId, {')

    // The extraction boundary must continue forwarding ownership callbacks unchanged.
    expect(chatStreamBoundarySource).toContain("callbacks: Omit<SseConnectParams, 'url' | 'body'>")
    expect(chatStreamBoundarySource).toContain('return useEventSource().connect({ ...request, ...callbacks })')
  })
})
