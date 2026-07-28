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
  it('keeps conversation deletion server-first and post-delete selection global-only', () => {
    const action = sourceBetween(
      chatStoreSource,
      'async deleteActiveConversation()',
      'addPendingAttachment(',
    )

    // Characterize the safe ordering without blessing the current swallowed-error path.
    expectInOrder(action, [
      'await apiDeleteConversation(convId)',
      'const { [convId]: _removedConv',
      "await this.loadConversations('global')",
      ".filter((c) => c.scope === 'global')",
      ".sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? ''))",
      'await this.openConversation(firstConv.id)',
    ])
    expect(action).toContain("await this.createNewConversation('global')")
  })

  it('keeps abort ownership and attachment consumption at explicit store seams', () => {
    const abortAction = sourceBetween(chatStoreSource, 'abortGeneration()', 'async deleteMessage(')
    expectInOrder(abortAction, [
      '_activeConnection.controller.abort()',
      '_activeConnection = null',
      'this.isStreaming = false',
      "this.streamPhase = 'idle'",
      'item.isStreaming ? { ...item, isStreaming: false, isThinking: false } : item',
    ])

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

    expect(streamAction).toContain('onMessage: (payload: unknown) => {')
    expect(streamAction).toContain('onDone: () => {')
    expect(streamAction).toContain('onError: (error: unknown) => {')
    expect(streamAction).toContain('this.patchMessage(params.conversationId, params.assistantTempId, {')
    expect(streamAction).toContain('_activeConnection = connection')

    // The extraction boundary must continue forwarding ownership callbacks unchanged.
    expect(chatStreamBoundarySource).toContain("callbacks: Omit<SseConnectParams, 'url' | 'body'>")
    expect(chatStreamBoundarySource).toContain('return useEventSource().connect({ ...request, ...callbacks })')
  })
})
