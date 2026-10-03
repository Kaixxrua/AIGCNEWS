import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fold, unfold } from './fold'
import { installFakeAnimations, type FakeAnimations } from './testing'

let fakes: FakeAnimations

// 纵向排布、行距 12px 的列表：标题一行，下面是可折叠的面板。
const mountList = (direction = 'column') => {
  document.body.innerHTML = `<div style="display: flex; flex-direction: ${direction}; row-gap: 12px">`
    + '<p id="title" style="height: 20px"></p>'
    + '<section id="panel" style="height: 80px; padding-top: 6px; padding-bottom: 6px; margin-top: 4px"></section>'
    + '</div>'
  return { title: document.getElementById('title')!, panel: document.getElementById('panel')! }
}

describe('fold / unfold', () => {
  beforeEach(() => {
    fakes = installFakeAnimations()
  })

  afterEach(() => {
    fakes.restore()
    document.body.innerHTML = ''
  })

  it('展开：高度、内外边距从 0 过渡到内容实际尺寸，连同它上方的行距一起让出来', () => {
    const { panel } = mountList()
    const done = vi.fn()
    unfold(panel, done)
    const [animation] = fakes.on(panel, 'fold')
    expect(animation?.frame(0)).toMatchObject({ height: '0px', paddingTop: '0px', paddingBottom: '0px', marginTop: '-12px', opacity: '0', clipPath: 'inset(0)' })
    expect(animation?.frame(1)).toMatchObject({ height: '80px', paddingTop: '6px', paddingBottom: '6px', marginTop: '4px', clipPath: 'inset(0)' })
    expect(animation?.options).toMatchObject({ duration: 300, fill: 'none' })
    animation!.finish()
    expect(done).toHaveBeenCalledOnce()
  })

  it('收起：停在 0 高度直到交还，交还后撤掉动画', () => {
    const { panel } = mountList()
    const done = vi.fn()
    fold(panel, done)
    const [animation] = fakes.on(panel, 'fold')
    expect(animation?.frame(1)).toMatchObject({ height: '0px', marginTop: '-12px', opacity: '0' })
    expect(animation?.options).toMatchObject({ duration: 240, fill: 'forwards' })
    animation!.finish()
    expect(done).toHaveBeenCalledOnce()
    expect(animation?.playState).toBe('idle')
  })

  it('排在最前时吃掉后面的行距；横向排布时不吃行距，只收自己的外边距', () => {
    const { title } = mountList()
    fold(title, vi.fn())
    expect(fakes.on(title, 'fold')[0]?.frame(1)).toMatchObject({ marginTop: '0px', marginBottom: '-12px' })

    const { panel } = mountList('row')
    fold(panel, vi.fn())
    expect(fakes.on(panel, 'fold')[0]?.frame(1)).toMatchObject({ marginTop: '0px' })
  })

  it('中途反向时停掉进行中的那段，从此刻的尺寸接着走', () => {
    const { panel } = mountList()
    unfold(panel, vi.fn())
    const [opening] = fakes.on(panel, 'fold')
    fold(panel, vi.fn())
    expect(opening?.playState).toBe('idle')
    expect(fakes.on(panel, 'fold')[1]?.frame(0)).toMatchObject({ height: '80px' })
  })

  it('display: contents 的元素没有盒子可折，直接交还', () => {
    const { panel } = mountList()
    panel.style.display = 'contents'
    const done = vi.fn()
    unfold(panel, done)
    expect(done).toHaveBeenCalledOnce()
    expect(fakes.all).toHaveLength(0)
  })
})
