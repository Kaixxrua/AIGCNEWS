import { describe, expect, it, vi } from 'vitest'
import type { ChatAttachmentRef } from '../../services/chat/chatApi'
import type { ChatMessage, ConversationSummary } from './chatModel'
import {
  ChatLifecycleCoordinator,
  type ChatLifecycleApis,
  type StreamConnection,
} from './chatLifecycleCoordinator'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function conversation(
  id: string,
  scope: 'global' | 'paper' = 'global',
  overrides: Partial<ConversationSummary> = {},
): ConversationSummary {
  return {
    id,
    title: id,
    scope,
    lastMessagePreview: '',
    messageCount: 0,
    ...overrides,
  }
}

function message(id: string, conversationId: string): ChatMessage {
  return {
    id,
    conversationId,
    role: 'user',
    content: id,
    thinking: '',
    thinkingPreview: '',
    hasThinking: false,
    isThinking: false,
    thinkingDurationSec: 0,
    isStreaming: false,
    sources: [],
    attachments: [],
  }
}

function apis(overrides: Partial<ChatLifecycleApis> = {}): ChatLifecycleApis {
  return {
    listConversations: vi.fn().mockResolvedValue([]),
    fetchConversationDetail: vi.fn(),
    createConversation: vi.fn(),
    deleteConversation: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('ChatLifecycleCoordinator conversation lifecycle', () => {
  it('applies only the latest selection detail response', async () => {
    const first = deferred<{ conversation: ConversationSummary; messages: ChatMessage[] }>()
    const second = deferred<{ conversation: ConversationSummary; messages: ChatMessage[] }>()
    const coordinator = new ChatLifecycleCoordinator(apis({
      fetchConversationDetail: vi.fn()
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise),
    }))

    const selectingFirst = coordinator.selectConversation('first')
    const selectingSecond = coordinator.selectConversation('second')
    second.resolve({ conversation: conversation('second'), messages: [message('m2', 'second')] })
    await selectingSecond
    first.resolve({ conversation: conversation('first'), messages: [message('m1', 'first')] })

    expect(await selectingFirst).toBeNull()
    expect(coordinator.getState().activeConversationId).toBe('second')
    expect(coordinator.getState().messageMap).toEqual({ second: [message('m2', 'second')] })
  })

  it('keeps a late create result without letting it steal a newer selection', async () => {
    const created = deferred<ConversationSummary>()
    const detail = deferred<{ conversation: ConversationSummary; messages: ChatMessage[] }>()
    const coordinator = new ChatLifecycleCoordinator(apis({
      createConversation: vi.fn().mockReturnValue(created.promise),
      fetchConversationDetail: vi.fn().mockReturnValue(detail.promise),
    }))

    const creating = coordinator.createAndSelect({ scope: 'global' })
    const selecting = coordinator.selectConversation('newer')
    detail.resolve({ conversation: conversation('newer'), messages: [] })
    await selecting
    created.resolve(conversation('created'))
    await creating

    expect(coordinator.getState().activeConversationId).toBe('newer')
    expect(Object.keys(coordinator.getState().conversationMap).sort()).toEqual(['created', 'newer'])
  })

  it('replaces only the requested scope and suppresses stale list responses', async () => {
    const stale = deferred<ConversationSummary[]>()
    const latest = deferred<ConversationSummary[]>()
    const list = vi.fn()
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(latest.promise)
    const coordinator = new ChatLifecycleCoordinator(apis({ listConversations: list }), {
      conversationMap: {
        oldGlobal: conversation('oldGlobal'),
        paperA: conversation('paperA', 'paper', { scopeKey: 'a' }),
        paperB: conversation('paperB', 'paper', { scopeKey: 'b' }),
      },
    })

    const staleLoad = coordinator.replaceConversationList({ scope: 'paper', scopeKey: 'a' })
    const latestLoad = coordinator.replaceConversationList({ scope: 'paper', scopeKey: 'a' })
    latest.resolve([conversation('newPaperA', 'paper', { scopeKey: 'a' })])
    await latestLoad
    stale.resolve([conversation('stalePaperA', 'paper', { scopeKey: 'a' })])
    expect(await staleLoad).toEqual([])

    expect(Object.keys(coordinator.getState().conversationMap).sort()).toEqual([
      'newPaperA',
      'oldGlobal',
      'paperB',
    ])
  })

  it('optimistically deletes, chooses a deterministic global fallback, and tombstones late data', async () => {
    const deletion = deferred<void>()
    const listed = deferred<ConversationSummary[]>()
    const coordinator = new ChatLifecycleCoordinator(apis({
      deleteConversation: vi.fn().mockReturnValue(deletion.promise),
      listConversations: vi.fn().mockReturnValue(listed.promise),
    }), {
      activeConversationId: 'target',
      activeScope: 'global',
      conversationMap: {
        target: conversation('target', 'global', { updatedAt: '2026-03-01' }),
        z: conversation('z', 'global', { updatedAt: '2026-02-01' }),
        a: conversation('a', 'global', { updatedAt: '2026-02-01' }),
        paper: conversation('paper', 'paper', { updatedAt: '2026-04-01' }),
      },
      messageMap: { target: [message('m', 'target')] },
    })

    const deleting = coordinator.deleteConversation('target')
    expect(coordinator.getState().activeConversationId).toBe('a')
    expect(coordinator.getState().conversationMap.target).toBeUndefined()

    const loading = coordinator.replaceConversationList({ scope: 'global' })
    listed.resolve([conversation('target'), conversation('fresh')])
    await loading
    expect(coordinator.getState().conversationMap.target).toBeUndefined()
    deletion.resolve()
    await deleting
  })

  it('restores the exact deleted entries on failure without overriding a newer selection', async () => {
    const deletion = deferred<void>()
    const selected = conversation('selected', 'paper')
    const original = conversation('target', 'global', { title: 'exact', updatedAt: '2026-01-01' })
    const originalMessages = [message('original', 'target')]
    const coordinator = new ChatLifecycleCoordinator(apis({
      deleteConversation: vi.fn().mockReturnValue(deletion.promise),
      fetchConversationDetail: vi.fn().mockResolvedValue({ conversation: selected, messages: [] }),
    }), {
      activeConversationId: 'target',
      conversationMap: { target: original, fallback: conversation('fallback') },
      messageMap: { target: originalMessages },
    })

    const deleting = coordinator.deleteConversation('target')
    await coordinator.selectConversation('selected')
    const failure = new Error('delete failed')
    deletion.reject(failure)
    await expect(deleting).rejects.toBe(failure)

    const state = coordinator.getState()
    expect(state.conversationMap.target).toEqual(original)
    expect(state.messageMap.target).toEqual(originalMessages)
    expect(state.activeConversationId).toBe('selected')
    expect(state.activeScope).toBe('paper')
  })

  it('invalidates pending work and rejects new work after dispose', async () => {
    const detail = deferred<{ conversation: ConversationSummary; messages: ChatMessage[] }>()
    const coordinator = new ChatLifecycleCoordinator(apis({
      fetchConversationDetail: vi.fn().mockReturnValue(detail.promise),
    }))
    const selecting = coordinator.selectConversation('late')

    coordinator.dispose()
    detail.resolve({ conversation: conversation('late'), messages: [] })

    expect(await selecting).toBeNull()
    expect(coordinator.getState().activeConversationId).toBeNull()
    await expect(coordinator.selectConversation('nope')).rejects.toThrow('disposed')
  })
})

describe('ChatLifecycleCoordinator stream ownership', () => {
  function streamHarness() {
    const callbacks: Array<{
      onEvent(event: string): void
      onDone(): void
      onError(error: unknown): void
    }> = []
    const connections: Array<StreamConnection & { abort: ReturnType<typeof vi.fn> }> = []
    const connect = vi.fn((_command: string, nextCallbacks: typeof callbacks[number]) => {
      const connection = { abort: vi.fn(), promise: new Promise<void>(() => undefined) }
      callbacks.push(nextCallbacks)
      connections.push(connection)
      return connection
    })
    return { connect, callbacks, connections }
  }

  it('supersedes and aborts the previous run while ignoring all stale callbacks', () => {
    const harness = streamHarness()
    const events: string[] = []
    const terminals: string[] = []
    const coordinator = new ChatLifecycleCoordinator(apis())
    const first = coordinator.startStreamRun({
      command: 'first',
      conversationId: 'conversation-1',
      messageId: 'message-1',
      attachmentRestoration: 'never',
      connect: harness.connect,
      callbacks: {
        onEvent: (event, context) => events.push(`${context.conversationId}:${context.messageId}:${event}`),
        onDone: () => terminals.push('first-done'),
        onError: () => terminals.push('first-error'),
        onAbort: (reason) => terminals.push(`first-${reason}`),
      },
    })
    const second = coordinator.startStreamRun({
      command: 'second',
      conversationId: 'conversation-2',
      messageId: 'message-2',
      attachmentRestoration: 'never',
      connect: harness.connect,
      callbacks: {
        onEvent: (event, context) => events.push(`${context.conversationId}:${context.messageId}:${event}`),
        onDone: () => terminals.push('second-done'),
        onError: () => terminals.push('second-error'),
      },
    })

    expect(first.conversationId).toBe('conversation-1')
    expect(first.messageId).toBe('message-1')
    expect(second.runId).toBeGreaterThan(first.runId)
    expect(harness.connections[0]?.abort).toHaveBeenCalledOnce()
    harness.callbacks[0]?.onEvent('stale')
    harness.callbacks[0]?.onDone()
    harness.callbacks[0]?.onError(new Error('stale'))
    harness.callbacks[1]?.onEvent('owned')
    harness.callbacks[1]?.onDone()
    harness.callbacks[1]?.onError(new Error('after done'))

    expect(events).toEqual(['conversation-2:message-2:owned'])
    expect(terminals).toEqual(['first-superseded', 'second-done'])
  })

  it('treats abort as terminal and applies the explicit restoration policy once', () => {
    const harness = streamHarness()
    const attachment: ChatAttachmentRef = {
      id: 'attachment',
      name: 'paper.pdf',
      mimeType: 'application/pdf',
      modality: 'pdf',
      parseStatus: 'ready',
    }
    const restored: string[][] = []
    const terminals: string[] = []
    const coordinator = new ChatLifecycleCoordinator(apis())
    const run = coordinator.startStreamRun({
      command: 'run',
      conversationId: 'conversation',
      messageId: 'message',
      attachments: [attachment],
      attachmentRestoration: 'restore-on-failure-and-abort',
      connect: harness.connect,
      callbacks: {
        onEvent: () => undefined,
        onDone: () => terminals.push('done'),
        onError: () => terminals.push('error'),
        onAbort: (reason) => terminals.push(reason),
        restoreAttachments: (attachments) => restored.push(attachments.map((item) => item.id)),
      },
    })

    run.abort()
    run.abort()
    harness.callbacks[0]?.onDone()
    harness.callbacks[0]?.onError(new Error('late'))

    expect(harness.connections[0]?.abort).toHaveBeenCalledOnce()
    expect(restored).toEqual([['attachment']])
    expect(terminals).toEqual(['aborted'])
  })

  it('restores attachments on owned failure but never after successful completion', () => {
    const harness = streamHarness()
    const attachment = {
      id: 'image',
      name: 'image.png',
      mimeType: 'image/png',
      modality: 'image' as const,
      parseStatus: 'ready' as const,
    }
    const restored = vi.fn()
    const errors = vi.fn()
    const coordinator = new ChatLifecycleCoordinator(apis())
    coordinator.startStreamRun({
      command: 'failure',
      conversationId: 'conversation',
      messageId: 'failed-message',
      attachments: [attachment],
      attachmentRestoration: 'restore-on-failure-and-abort',
      connect: harness.connect,
      callbacks: {
        onEvent: () => undefined,
        onDone: () => undefined,
        onError: errors,
        restoreAttachments: restored,
      },
    })
    harness.callbacks[0]?.onError(new Error('failed'))
    expect(errors).toHaveBeenCalledOnce()
    expect(restored).toHaveBeenCalledOnce()

    coordinator.startStreamRun({
      command: 'success',
      conversationId: 'conversation',
      messageId: 'successful-message',
      attachments: [attachment],
      attachmentRestoration: 'restore-on-failure-and-abort',
      connect: harness.connect,
      callbacks: {
        onEvent: () => undefined,
        onDone: () => undefined,
        onError: () => undefined,
        restoreAttachments: restored,
      },
    })
    harness.callbacks[1]?.onDone()
    expect(restored).toHaveBeenCalledOnce()
  })

  it('aborts and invalidates the owning run when disposed', () => {
    const harness = streamHarness()
    const events = vi.fn()
    const coordinator = new ChatLifecycleCoordinator(apis())
    coordinator.startStreamRun({
      command: 'run',
      conversationId: 'conversation',
      messageId: 'message',
      attachmentRestoration: 'never',
      connect: harness.connect,
      callbacks: {
        onEvent: events,
        onDone: () => undefined,
        onError: () => undefined,
      },
    })

    coordinator.dispose()
    harness.callbacks[0]?.onEvent('late')

    expect(harness.connections[0]?.abort).toHaveBeenCalledOnce()
    expect(events).not.toHaveBeenCalled()
  })
})
