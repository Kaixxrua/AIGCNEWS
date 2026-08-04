import type { ChatAttachmentRef } from '@/services/chat/chatApi'
import type {
  ChatMessage,
  ConversationScope,
  ConversationSummary,
} from './chatModel'

export interface ConversationListSelector {
  scope?: ConversationScope
  scopeKey?: string
}

export interface ConversationDetail {
  conversation: ConversationSummary
  messages: ChatMessage[]
}

export interface CreateConversationInput {
  scope: ConversationScope
  scopeKey?: string
  title?: string
}

export interface ChatLifecycleApis {
  listConversations(selector: ConversationListSelector): Promise<ConversationSummary[]>
  fetchConversationDetail(conversationId: string): Promise<ConversationDetail>
  createConversation(input: CreateConversationInput): Promise<ConversationSummary>
  ensureConversation(input: CreateConversationInput): Promise<ConversationSummary>
  deleteConversation(conversationId: string): Promise<void>
}

export interface ChatLifecycleState {
  activeConversationId: string | null
  activeScope: ConversationScope
  conversationMap: Record<string, ConversationSummary>
  messageMap: Record<string, ChatMessage[]>
}

export type ChatLifecycleStateListener = (state: ChatLifecycleState) => void

export type AttachmentRestorationPolicy = 'restore-on-failure-and-abort' | 'never'
export type StreamRunTerminalReason = 'done' | 'error' | 'aborted' | 'superseded'

export interface StreamRunContext {
  runId: number
  conversationId: string
  messageId: string
  attachments: readonly ChatAttachmentRef[]
}

export interface StreamRunCallbacks<TEvent = unknown> {
  onEvent(event: TEvent, context: StreamRunContext): void
  onDone(context: StreamRunContext): unknown
  onError(error: unknown, context: StreamRunContext): void
  onAbort?(reason: 'aborted' | 'superseded', context: StreamRunContext): void
  restoreAttachments?(attachments: readonly ChatAttachmentRef[], context: StreamRunContext): void
}

export interface StreamConnection {
  abort(): void
  promise: Promise<void>
}

export interface StreamConnector<TCommand, TEvent = unknown> {
  (
    command: TCommand,
    callbacks: {
      onEvent(event: TEvent): void
      onDone(): void
      onError(error: unknown): void
    },
  ): StreamConnection
}

export interface StartStreamRunInput<TCommand, TEvent = unknown> {
  command: TCommand
  conversationId: string
  messageId: string
  attachments?: ChatAttachmentRef[]
  attachmentRestoration: AttachmentRestorationPolicy
  connect: StreamConnector<TCommand, TEvent>
  callbacks: StreamRunCallbacks<TEvent>
}

export interface StreamRunHandle {
  readonly runId: number
  readonly conversationId: string
  readonly messageId: string
  readonly promise: Promise<void>
  abort(): void
}

interface OwnedRun {
  context: StreamRunContext
  connection: StreamConnection | null
  terminalReason: StreamRunTerminalReason | null
  attachmentRestoration: AttachmentRestorationPolicy
  callbacks: StreamRunCallbacks<unknown>
}

function selectorKey(selector: ConversationListSelector): string {
  return `${selector.scope}:${selector.scopeKey ?? ''}`
}

function belongsToSelector(
  conversation: ConversationSummary,
  selector: ConversationListSelector,
): boolean {
  return conversation.scope === selector.scope
    && (selector.scopeKey === undefined || conversation.scopeKey === selector.scopeKey)
}

function compareGlobalFallback(a: ConversationSummary, b: ConversationSummary): number {
  const aTime = a.updatedAt ?? a.createdAt ?? ''
  const bTime = b.updatedAt ?? b.createdAt ?? ''
  return bTime.localeCompare(aTime) || a.id.localeCompare(b.id)
}

function cloneState(state: ChatLifecycleState): ChatLifecycleState {
  return {
    activeConversationId: state.activeConversationId,
    activeScope: state.activeScope,
    conversationMap: { ...state.conversationMap },
    messageMap: Object.fromEntries(
      Object.entries(state.messageMap).map(([id, messages]) => [id, [...messages]]),
    ),
  }
}

export class ChatLifecycleCoordinator {
  private readonly apis: ChatLifecycleApis
  private state: ChatLifecycleState
  private readonly listeners = new Set<ChatLifecycleStateListener>()
  private readonly tombstones = new Set<string>()
  private readonly listRevisions = new Map<string, number>()
  private generation = 0
  private selectionRevision = 0
  private runSequence = 0
  private activeRun: OwnedRun | null = null
  private disposed = false

  constructor(
    apis: ChatLifecycleApis,
    initialState: Partial<ChatLifecycleState> = {},
  ) {
    this.apis = apis
    this.state = {
      activeConversationId: initialState.activeConversationId ?? null,
      activeScope: initialState.activeScope ?? 'global',
      conversationMap: { ...initialState.conversationMap },
      messageMap: Object.fromEntries(
        Object.entries(initialState.messageMap ?? {}).map(([id, messages]) => [id, [...messages]]),
      ),
    }
  }

  getState(): ChatLifecycleState {
    return cloneState(this.state)
  }

  synchronizeState(state: ChatLifecycleState): void {
    this.assertUsable()
    this.state = cloneState(state)
  }

  subscribe(listener: ChatLifecycleStateListener): () => void {
    this.assertUsable()
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  async replaceConversationList(
    selector: ConversationListSelector,
  ): Promise<ConversationSummary[]> {
    this.assertUsable()
    const generation = this.generation
    const key = selectorKey(selector)
    const revision = (this.listRevisions.get(key) ?? 0) + 1
    this.listRevisions.set(key, revision)
    const conversations = await this.apis.listConversations(selector)
    if (!this.isCurrent(generation) || this.listRevisions.get(key) !== revision) return []

    const replacement = conversations.filter((item) => !this.tombstones.has(item.id))
    const conversationMap = Object.fromEntries(
      Object.entries(this.state.conversationMap).filter(([, item]) => !belongsToSelector(item, selector)),
    )
    for (const conversation of replacement) conversationMap[conversation.id] = conversation
    this.commit({ ...this.state, conversationMap })
    return replacement
  }

  async selectConversation(conversationId: string): Promise<ConversationDetail | null> {
    this.assertUsable()
    const generation = this.generation
    const revision = ++this.selectionRevision
    const detail = await this.apis.fetchConversationDetail(conversationId)
    if (!this.isCurrent(generation) || revision !== this.selectionRevision) return null
    if (this.tombstones.has(conversationId) || this.tombstones.has(detail.conversation.id)) return null

    this.commit({
      ...this.state,
      activeConversationId: detail.conversation.id,
      activeScope: detail.conversation.scope,
      conversationMap: {
        ...this.state.conversationMap,
        [detail.conversation.id]: detail.conversation,
      },
      messageMap: {
        ...this.state.messageMap,
        [detail.conversation.id]: [...detail.messages],
      },
    })
    return detail
  }

  async createAndSelect(input: CreateConversationInput): Promise<ConversationSummary | null> {
    return this.resolveAndSelect(() => this.apis.createConversation(input), true)
  }

  async ensureAndSelect(input: CreateConversationInput): Promise<ConversationSummary | null> {
    return this.resolveAndSelect(() => this.apis.ensureConversation(input), false)
  }

  async deleteConversation(conversationId: string): Promise<void> {
    this.assertUsable()
    if (this.tombstones.has(conversationId)) return
    const generation = this.generation
    const selectionRevision = ++this.selectionRevision
    const removedConversation = this.state.conversationMap[conversationId]
    const removedMessages = this.state.messageMap[conversationId]
    const previousActiveId = this.state.activeConversationId
    const previousActiveScope = this.state.activeScope
    this.tombstones.add(conversationId)

    const { [conversationId]: _conversation, ...conversationMap } = this.state.conversationMap
    const { [conversationId]: _messages, ...messageMap } = this.state.messageMap
    const deletingActive = previousActiveId === conversationId
    const fallback = deletingActive
      ? Object.values(conversationMap).filter((item) => item.scope === 'global').sort(compareGlobalFallback)[0]
      : undefined
    this.commit({
      activeConversationId: deletingActive ? fallback?.id ?? null : previousActiveId,
      activeScope: deletingActive ? fallback?.scope ?? 'global' : previousActiveScope,
      conversationMap,
      messageMap,
    })

    try {
      await this.apis.deleteConversation(conversationId)
    } catch (error) {
      if (this.isCurrent(generation)) {
        this.tombstones.delete(conversationId)
        const rollbackState: ChatLifecycleState = {
          ...this.state,
          conversationMap: removedConversation
            ? { ...this.state.conversationMap, [conversationId]: removedConversation }
            : this.state.conversationMap,
          messageMap: removedMessages
            ? { ...this.state.messageMap, [conversationId]: [...removedMessages] }
            : this.state.messageMap,
        }
        if (this.selectionRevision === selectionRevision) {
          rollbackState.activeConversationId = previousActiveId
          rollbackState.activeScope = previousActiveScope
        }
        this.commit(rollbackState)
      }
      throw error
    }
  }

  startStreamRun<TCommand, TEvent = unknown>(
    input: StartStreamRunInput<TCommand, TEvent>,
  ): StreamRunHandle {
    this.assertUsable()
    this.terminateRun(this.activeRun, 'superseded')

    const generation = this.generation
    const context: StreamRunContext = Object.freeze({
      runId: ++this.runSequence,
      conversationId: input.conversationId,
      messageId: input.messageId,
      attachments: Object.freeze([...(input.attachments ?? [])]),
    })
    const run: OwnedRun = {
      context,
      connection: null,
      terminalReason: null,
      attachmentRestoration: input.attachmentRestoration,
      callbacks: input.callbacks as StreamRunCallbacks<unknown>,
    }
    this.activeRun = run

    const isOwner = () => this.isCurrent(generation)
      && this.activeRun === run
      && run.terminalReason === null
    const connection = input.connect(input.command, {
      onEvent: (event) => {
        if (isOwner()) input.callbacks.onEvent(event, context)
      },
      onDone: () => {
        if (!isOwner()) return
        if (input.callbacks.onDone(context) === false) return
        run.terminalReason = 'done'
        this.activeRun = null
      },
      onError: (error) => {
        if (!isOwner()) return
        run.terminalReason = 'error'
        this.activeRun = null
        this.restoreAttachments(run)
        input.callbacks.onError(error, context)
      },
    })
    run.connection = connection
    void connection.promise.catch((error: unknown) => {
      if (!isOwner()) return
      run.terminalReason = 'error'
      this.activeRun = null
      this.restoreAttachments(run)
      input.callbacks.onError(error, context)
    })

    return {
      runId: context.runId,
      conversationId: context.conversationId,
      messageId: context.messageId,
      promise: connection.promise,
      abort: () => this.terminateRun(run, 'aborted'),
    }
  }

  abortActiveRun(): void {
    this.terminateRun(this.activeRun, 'aborted')
  }

  ownsStreamRun(runId: number): boolean {
    return this.activeRun?.context.runId === runId && this.activeRun.terminalReason === null
  }

  dispose(): void {
    if (this.disposed) return
    this.terminateRun(this.activeRun, 'aborted')
    this.disposed = true
    this.generation += 1
    this.selectionRevision += 1
    this.listRevisions.clear()
    this.listeners.clear()
  }

  private async resolveAndSelect(
    resolve: () => Promise<ConversationSummary>,
    initializeMessages: boolean,
  ): Promise<ConversationSummary | null> {
    this.assertUsable()
    const generation = this.generation
    const revision = ++this.selectionRevision
    const conversation = await resolve()
    if (!this.isCurrent(generation) || this.tombstones.has(conversation.id)) return null

    const nextState: ChatLifecycleState = {
      ...this.state,
      conversationMap: { ...this.state.conversationMap, [conversation.id]: conversation },
      messageMap: initializeMessages
        ? { ...this.state.messageMap, [conversation.id]: [] }
        : this.state.messageMap,
    }
    if (revision === this.selectionRevision) {
      nextState.activeConversationId = conversation.id
      nextState.activeScope = conversation.scope
    }
    this.commit(nextState)
    return conversation
  }

  private terminateRun(run: OwnedRun | null, reason: 'aborted' | 'superseded'): void {
    if (!run || run.terminalReason !== null) return
    run.terminalReason = reason
    if (this.activeRun === run) this.activeRun = null
    run.connection?.abort()
    this.restoreAttachments(run)
    run.callbacks.onAbort?.(reason, run.context)
  }

  private restoreAttachments(run: OwnedRun): void {
    if (run.attachmentRestoration === 'restore-on-failure-and-abort' && run.context.attachments.length > 0) {
      run.callbacks.restoreAttachments?.(run.context.attachments, run.context)
    }
  }

  private commit(state: ChatLifecycleState): void {
    if (this.disposed) return
    this.state = state
    const snapshot = this.getState()
    for (const listener of this.listeners) listener(snapshot)
  }

  private isCurrent(generation: number): boolean {
    return !this.disposed && generation === this.generation
  }

  private assertUsable(): void {
    if (this.disposed) throw new Error('ChatLifecycleCoordinator has been disposed')
  }
}
