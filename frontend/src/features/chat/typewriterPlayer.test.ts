import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  TypewriterPlayer,
  buildThinkingPreview,
  type TypewriterFramePatch,
  type TypewriterMessageSnapshot,
} from './typewriterPlayer'

function createHarness() {
  const msg = { thinking: '', content: '' }
  const frames: TypewriterFramePatch[] = []
  const drained = vi.fn()
  const player = new TypewriterPlayer({
    readSnapshot: () => msg,
    emitFrame: (patch) => {
      frames.push(patch)
      Object.assign(msg, patch)
    },
    onDrained: drained,
  })
  return { msg, frames, drained, player }
}

describe('typewriter player', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('builds an 80-char thinking preview with an ellipsis only when truncated', () => {
    expect(buildThinkingPreview('x'.repeat(80))).toBe('x'.repeat(80))
    expect(buildThinkingPreview('x'.repeat(81))).toBe(`${'x'.repeat(80)}…`)
    expect(buildThinkingPreview('')).toBe('')
  })

  it('types thinking at 12 chars per frame with streaming flags', async () => {
    const { msg, frames, drained, player } = createHarness()
    player.enqueueThinking('abcdefghijklmn')

    await vi.advanceTimersByTimeAsync(16)
    expect(msg.thinking).toBe('abcdefghijkl')
    expect(frames[0]).toMatchObject({
      thinking: 'abcdefghijkl',
      thinkingPreview: 'abcdefghijkl',
      hasThinking: true,
      isThinking: true,
      isStreaming: true,
    })

    await vi.advanceTimersByTimeAsync(16)
    expect(msg.thinking).toBe('abcdefghijklmn')

    // 队列排空但输入未结束：不触发 onDrained，计时器继续等待后续增量
    await vi.advanceTimersByTimeAsync(64)
    expect(drained).not.toHaveBeenCalled()
  })

  it('streams content only after the thinking queue drains and stamps duration on the first content frame', async () => {
    const { msg, frames, player } = createHarness()
    player.enqueueThinking('ab')
    player.enqueueContent('abcdef')

    await vi.advanceTimersByTimeAsync(16)
    expect(msg.thinking).toBe('ab')
    expect(msg.content).toBe('')

    await vi.advanceTimersByTimeAsync(16)
    expect(msg.content).toBe('abc')
    expect(frames[frames.length - 1]).toMatchObject({ isThinking: false, isStreaming: true, thinkingDurationSec: 0 })

    await vi.advanceTimersByTimeAsync(16)
    expect(msg.content).toBe('abcdef')
    expect(frames[frames.length - 1]).not.toHaveProperty('thinkingDurationSec')
  })

  it('locks the thinking duration at the first content event', async () => {
    const { frames, player } = createHarness()
    await vi.advanceTimersByTimeAsync(2000)

    player.enqueueContent('abc')
    await vi.advanceTimersByTimeAsync(16)

    expect(frames[0]).toMatchObject({ thinkingDurationSec: 2 })
    expect(player.thinkingDurationSec()).toBe(2)
  })

  it('finishInput returns true and stops the timer when queues are already empty', async () => {
    const { frames, drained, player } = createHarness()
    expect(player.finishInput()).toBe(true)

    await vi.advanceTimersByTimeAsync(128)
    expect(drained).not.toHaveBeenCalled()
    expect(frames).toHaveLength(0)
  })

  it('drains pending queues across frames then fires onDrained exactly once', async () => {
    const { drained, player } = createHarness()
    player.enqueueContent('abcdef')
    expect(player.finishInput()).toBe(false)

    await vi.advanceTimersByTimeAsync(16)
    expect(drained).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(16)
    // 最后一帧吐字的当帧不做排空检查，下一帧才收尾
    expect(drained).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(16)
    expect(drained).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(64)
    expect(drained).toHaveBeenCalledTimes(1)
  })

  it('stop discards pending frames and prevents the timer from restarting', async () => {
    const { frames, msg, player } = createHarness()
    player.enqueueContent('abcdef')
    player.stop()

    await vi.advanceTimersByTimeAsync(128)
    expect(frames).toHaveLength(0)
    expect(msg.content).toBe('')

    player.enqueueContent('ghi')
    await vi.advanceTimersByTimeAsync(128)
    expect(frames).toHaveLength(0)
  })

  it('skips frames while the snapshot is missing but keeps the timer alive', async () => {
    const holder: { snapshot: TypewriterMessageSnapshot | undefined } = { snapshot: undefined }
    const frames: TypewriterFramePatch[] = []
    const player = new TypewriterPlayer({
      readSnapshot: () => holder.snapshot,
      emitFrame: (patch) => frames.push(patch),
      onDrained: vi.fn(),
    })

    player.enqueueContent('abc')
    await vi.advanceTimersByTimeAsync(64)
    expect(frames).toHaveLength(0)

    holder.snapshot = { thinking: '', content: '' }
    await vi.advanceTimersByTimeAsync(16)
    expect(frames).toHaveLength(1)
    expect(frames[0]).toMatchObject({ content: 'abc' })
  })
})
