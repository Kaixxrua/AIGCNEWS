import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { highlightSource } from './highlight'
import { sourceBundle, type UiTemplate } from './catalog'

const dataRoot = resolve(process.cwd(), '../mcp-go/internal/uicatalog/data')
const items: UiTemplate[] = JSON.parse(readFileSync(resolve(dataRoot, 'catalog.json'), 'utf8')).items
describe('Original source presentation', () => {
  it('preserves every original source and license while highlighting only safe spans', () => {
    const files = new Map(items.flatMap(item => [...item.files, ...item.notices]).map(file => [file.path, file]))
    for (const file of files.values()) {
      const code = readFileSync(resolve(dataRoot, file.path), 'utf8')
      const { html } = highlightSource(code, file.name)
      const element = document.createElement('div')
      element.innerHTML = html
      expect(element.textContent).toBe(code.replace(/\r\n/g, '\n'))
      expect([...element.querySelectorAll('*')].every(node => node.tagName === 'SPAN')).toBe(true)
    }
  }, 120000)
  it.each(['Component.vue', 'effect.tsx', 'LICENSE'])('renders executable-looking content as text in %s', filename => {
    const code = '<script>alert("source")</script><img src=x onerror=alert(1)>&copy;'
    const element = document.createElement('div')
    element.innerHTML = highlightSource(code, filename).html
    expect(element.textContent).toBe(code)
    expect(element.querySelector('script,img')).toBeNull()
  })
  it('copies the complete original file bundle, including CSS and licenses', () => {
    const item = items[0]!
    const files = [...item.files, ...item.notices].map(file => ({ name: file.name, content: readFileSync(resolve(dataRoot, file.path), 'utf8') }))
    const bundle = sourceBundle(files)
    for (const file of files) {
      expect(bundle).toContain(`--- ${file.name} ---`)
      expect(bundle).toContain(file.content)
    }
  })
})
