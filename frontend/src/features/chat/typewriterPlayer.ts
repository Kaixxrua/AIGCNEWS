/**
 * 打字机播放引擎：把流式增量按固定帧率排入队列逐帧吐出，
 * 并维护思维链计时。与 Pinia 状态解耦——调用方通过回调订阅输出帧，
 * 计时器归属引擎内部，便于独立测试与复用。
 */
export interface TypewriterMessageSnapshot {
  thinking: string
  content: string
}

export interface TypewriterFramePatch {
  thinking?: string
  thinkingPreview?: string
  content?: string
  hasThinking?: boolean
  isThinking?: boolean
  isStreaming?: boolean
  thinkingDurationSec?: number
}

export interface TypewriterPlayerOptions {
  /** 读取目标消息当前快照；消息不存在时返回 undefined，本帧跳过。 */
  readSnapshot: () => TypewriterMessageSnapshot | undefined
  /** 输出一帧补丁（由调用方写入自身状态）。 */
  emitFrame: (patch: TypewriterFramePatch) => void
  /** 输入已结束且积压队列在帧循环中排空时触发一次。 */
  onDrained: () => void
  frameMs?: number
  contentCharsPerFrame?: number
  thinkingCharsPerFrame?: number
  now?: () => number
  /** 注入调度器便于测试；返回取消函数。默认 setInterval。 */
  schedule?: (tick: () => void, frameMs: number) => () => void
}

const DEFAULT_FRAME_MS = 16
const DEFAULT_CONTENT_CHARS_PER_FRAME = 3
const DEFAULT_THINKING_CHARS_PER_FRAME = 12
const THINKING_PREVIEW_LENGTH = 80

const defaultSchedule = (tick: () => void, frameMs: number): (() => void) => {
  const timer = setInterval(tick, frameMs)
  return () => clearInterval(timer)
}

export function buildThinkingPreview(thinking: string): string {
  return `${thinking.slice(0, THINKING_PREVIEW_LENGTH)}${thinking.length > THINKING_PREVIEW_LENGTH ? '…' : ''}`
}

export class TypewriterPlayer {
  private readonly readSnapshot: () => TypewriterMessageSnapshot | undefined
  private readonly emitFrame: (patch: TypewriterFramePatch) => void
  private readonly onDrained: () => void
  private readonly frameMs: number
  private readonly contentCharsPerFrame: number
  private readonly thinkingCharsPerFrame: number
  private readonly now: () => number
  private readonly schedule: (tick: () => void, frameMs: number) => () => void

  private readonly contentQueue: string[] = []
  private readonly thinkingQueue: string[] = []
  private cancelTimer: (() => void) | null = null
  private inputFinished = false
  private stopped = false

  // 思维链计时：记录首次收到 thinking/content 事件的时间
  private readonly thinkingStartMs: number
  private thinkingEndMs = 0
  private contentStarted = false

  constructor(options: TypewriterPlayerOptions) {
    this.readSnapshot = options.readSnapshot
    this.emitFrame = options.emitFrame
    this.onDrained = options.onDrained
    this.frameMs = options.frameMs ?? DEFAULT_FRAME_MS
    this.contentCharsPerFrame = options.contentCharsPerFrame ?? DEFAULT_CONTENT_CHARS_PER_FRAME
    this.thinkingCharsPerFrame = options.thinkingCharsPerFrame ?? DEFAULT_THINKING_CHARS_PER_FRAME
    this.now = options.now ?? (() => Date.now())
    this.schedule = options.schedule ?? defaultSchedule
    this.thinkingStartMs = this.now()
  }

  /** 思维链增量入队并确保帧循环运行。 */
  enqueueThinking(chunk: string): void {
    for (const ch of chunk) this.thinkingQueue.push(ch)
    this.ensureTimer()
  }

  /** 正文增量入队（可携带夹带的思维链片段）；首个正文事件锁定思维链结束时间。 */
  enqueueContent(chunk: string, thinkingChunk = ''): void {
    for (const ch of thinkingChunk) this.thinkingQueue.push(ch)
    if (!this.thinkingEndMs) this.thinkingEndMs = this.now()
    for (const ch of chunk) this.contentQueue.push(ch)
    this.ensureTimer()
  }

  /**
   * 标记输入结束。返回 true 表示队列已空（计时器已停，调用方直接收尾）；
   * 返回 false 表示仍有积压，排空时通过 onDrained 通知。
   */
  finishInput(): boolean {
    this.inputFinished = true
    if (this.thinkingQueue.length === 0 && this.contentQueue.length === 0) {
      this.clearTimer()
      return true
    }
    return false
  }

  /** 中止播放：停止计时器并丢弃后续帧。 */
  stop(): void {
    this.stopped = true
    this.clearTimer()
  }

  /** 思维链已耗时（秒）：思维链结束时间（未结束时取当前时间）减去起始时间。 */
  thinkingDurationSec(): number {
    const endMs = this.thinkingEndMs || this.now()
    return Math.round((endMs - this.thinkingStartMs) / 1000)
  }

  private ensureTimer(): void {
    if (this.cancelTimer !== null || this.stopped) return
    this.cancelTimer = this.schedule(() => this.tick(), this.frameMs)
  }

  private clearTimer(): void {
    if (this.cancelTimer === null) return
    this.cancelTimer()
    this.cancelTimer = null
  }

  private tick(): void {
    if (this.stopped) {
      this.clearTimer()
      return
    }
    const snapshot = this.readSnapshot()
    if (!snapshot) return

    let updated = false
    if (this.thinkingQueue.length > 0) {
      const chars = this.thinkingQueue.splice(0, this.thinkingCharsPerFrame).join('')
      const thinking = snapshot.thinking + chars
      this.emitFrame({
        thinking,
        thinkingPreview: buildThinkingPreview(thinking),
        hasThinking: true,
        isThinking: true,
        isStreaming: true,
      })
      updated = true
    } else if (this.contentQueue.length > 0) {
      const chars = this.contentQueue.splice(0, this.contentCharsPerFrame).join('')
      // 首次渲染 content 时，结束思维链计时
      if (!this.contentStarted) {
        this.contentStarted = true
        this.thinkingEndMs = this.thinkingEndMs || this.now()
        this.emitFrame({
          content: snapshot.content + chars,
          isThinking: false,
          isStreaming: true,
          thinkingDurationSec: Math.round((this.thinkingEndMs - this.thinkingStartMs) / 1000),
        })
      } else {
        this.emitFrame({
          content: snapshot.content + chars,
          isThinking: false,
          isStreaming: true,
        })
      }
      updated = true
    }

    if (!updated && this.inputFinished && this.thinkingQueue.length === 0 && this.contentQueue.length === 0) {
      this.clearTimer()
      this.onDrained()
    }
  }
}
