// @vitest-environment node
import { test } from 'vitest'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { extractFragment, buildHtmlPreview } from './original-html-previews.mjs'

const hash = raw => createHash('sha256').update(raw).digest('hex')
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

test('excerpts are byte ranges, including non-ASCII content; stale ranges fail', () => {
  const prefix = Buffer.from('文档\n'), html = Buffer.from('<p>你好</p>')
  const raw = Buffer.concat([prefix, html, Buffer.from('\nnotes')])
  const selection = { start: prefix.length, end: prefix.length + html.length, sha256: hash(html) }
  assert.equal(extractFragment(raw, selection), html.toString())
  for (const bad of [{ ...selection, start: -1 }, { ...selection, end: raw.length + 1 },
    { ...selection, sha256: 'a'.repeat(64) }, { ...selection, start: 1.5 }]) {
    assert.throws(() => extractFragment(raw, bad))
  }
})

test('HTML compilation preserves the selected markup and strict offline CSP', async () => {
  const data = await mkdtemp(resolve(tmpdir(), 'html-preview-test-'))
  try {
    const output = resolve(data, 'output')
    await mkdir(output)
    const html = Buffer.from('<button class="bg-primary p-4">Example</button>')
    const doc = Buffer.concat([Buffer.from('# Docs\n'), html, Buffer.from('\n<img src="https://remote.test/x">')])
    const css = Buffer.from('@theme { --color-primary: #123456; }')
    await writeFile(resolve(data, 'doc.mdx'), doc)
    await writeFile(resolve(data, 'example.html'), html)
    await writeFile(resolve(data, 'theme.css'), css)
    const item = { id: 'html-test', provider_id: 'test', name: { en: 'Test' },
      preview_adapter: 'original-html-v1', preview_tailwind: 4, preview_css: 'theme.css', preview_scripts: [],
      files: [{ name: 'example.html', path: 'example.html', sha256: hash(html) },
        { name: 'doc.mdx', path: 'doc.mdx', sha256: hash(doc) },
        { name: 'theme.css', path: 'theme.css', sha256: hash(css) }],
      preview_fragment: { path: 'doc.mdx', start: 7, end: 7 + html.length, sha256: hash(html) } }
    assert.equal(await buildHtmlPreview(item, data, output, root), true)
    const built = await readFile(resolve(output, 'html-test.html'), 'utf8')
    assert.ok(built.includes(html.toString()))
    assert.ok(!built.includes('remote.test'))
    assert.ok(built.includes("connect-src 'none'"))
    assert.ok(built.includes("script-src 'self';"))
    assert.ok((await readFile(resolve(output, 'html-test.css'), 'utf8')).includes('#123456'))
    assert.match(await readFile(resolve(output, 'html-test.LICENSE.txt'), 'utf8'), /MIT License/)
    await writeFile(resolve(data, 'example.html'), '<p>Different example</p>')
    item.files[0].sha256 = hash(Buffer.from('<p>Different example</p>'))
    await assert.rejects(buildHtmlPreview(item, data, output, root), /differs from source excerpt/)
    await writeFile(resolve(data, 'example.html'), html)
    item.files[0].sha256 = hash(html)
    await writeFile(resolve(data, 'doc.mdx'), 'tampered')
    await assert.rejects(buildHtmlPreview(item, data, output, root), /integrity/)
  } finally { await rm(data, { recursive: true, force: true }) }
})

test('Sailboat forms compile with the reviewed theme and local plugin notices', async () => {
  const data = await mkdtemp(resolve(tmpdir(), 'sailboat-preview-test-'))
  try {
    const output = resolve(data, 'output')
    await mkdir(output)
    const html = Buffer.from('<input type="checkbox" class="text-primary-600 rounded" />')
    const css = Buffer.from('@tailwind base; @tailwind components; @tailwind utilities;')
    await writeFile(resolve(data, 'example.html'), html)
    await writeFile(resolve(data, 'doc.html'), html)
    await writeFile(resolve(data, 'theme.css'), css)
    const item = { id: 'sailboat-test', provider_id: 'sailboatui', name: { en: 'Test' },
      preview_adapter: 'original-html-v1', preview_tailwind: 3, preview_css: 'theme.css', preview_scripts: [],
      files: [{ name: 'example.html', path: 'example.html', sha256: hash(html) },
        { name: 'doc.html', path: 'doc.html', sha256: hash(html) },
        { name: 'theme.css', path: 'theme.css', sha256: hash(css) }],
      preview_fragment: { path: 'doc.html', start: 0, end: html.length, sha256: hash(html), wrapper_class: 'w-full' } }
    await buildHtmlPreview(item, data, output, root)
    const built = await readFile(resolve(output, 'sailboat-test.css'), 'utf8')
    assert.match(built, /text-primary-600/)
    assert.match(built, /data:image\/svg\+xml/)
    const notices = await readFile(resolve(output, 'sailboat-test.LICENSE.txt'), 'utf8')
    assert.match(notices, /@tailwindcss\/forms/)
    assert.equal(notices.match(/MIT License/g).length, 2)
    const cycle = Buffer.from('@import "./theme.css";')
    await writeFile(resolve(data, 'theme.css'), cycle)
    item.files[2].sha256 = hash(cycle)
    await assert.rejects(buildHtmlPreview(item, data, output, root), /cyclic/)
  } finally { await rm(data, { recursive: true, force: true }) }
})
