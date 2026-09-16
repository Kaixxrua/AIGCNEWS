import { createHash } from 'node:crypto'
import { readFile, rename, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

const [root, asset = 'assets/contact-godot-interaction-v2.css'] = process.argv.slice(2)
if (!root) throw new Error('usage: node add-release-stylesheet.mjs <release-root> [asset]')

const indexPath = join(root, 'index.html')
const swPath = join(root, 'sw.js')
const href = `/${asset}`
const link = `<link rel="stylesheet" crossorigin href="${href}">`

let html = await readFile(indexPath, 'utf8')
if (!html.includes(href)) {
  html = html.replace('</head>', `  ${link}\n</head>`)
  if (!html.includes(href)) throw new Error('could not insert stylesheet into index.html')
  await writeAtomic(indexPath, html)
}

const revision = createHash('md5').update(html).digest('hex')
let sw = await readFile(swPath, 'utf8')
sw = sw.replace(/\{url:"index\.html",revision:"[^"]+"\}/, `{url:"index.html",revision:"${revision}"}`)
if (!sw.includes(`{url:"${asset}",revision:null}`)) {
  const anchor = '{url:"assets/index-C7gy1L4K.css",revision:null}'
  if (!sw.includes(anchor)) throw new Error('could not locate service-worker asset anchor')
  sw = sw.replace(anchor, `${anchor},{url:"${asset}",revision:null}`)
}
await writeAtomic(swPath, sw)

async function writeAtomic(path, content) {
  const temporary = `${path}.tmp-contact-style`
  await writeFile(temporary, content)
  await rename(temporary, path)
}
