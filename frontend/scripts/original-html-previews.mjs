// Mount pinned HTML excerpts without executing upstream documentation/config code.
import { readFile, writeFile, realpath } from 'node:fs/promises'
import { resolve, sep, posix } from 'node:path'
import { createHash } from 'node:crypto'
import postcss from 'postcss'
import tailwindcss from 'tailwindcss'
import colors from 'tailwindcss/colors.js'
import defaultTheme from 'tailwindcss/defaultTheme.js'
import forms from '@tailwindcss/forms'
import { compile } from 'tailwindcss4'

const hash = raw => createHash('sha256').update(raw).digest('hex')
const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;')
const imports = /@import\s+["']([^"']+)["']\s*;/g

export function extractFragment(raw, selection) {
  const { start, end, sha256 } = selection ?? {}
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > raw.length) {
    throw new Error('Invalid HTML excerpt range')
  }
  const fragment = raw.subarray(start, end)
  if (hash(fragment) !== sha256) throw new Error('HTML excerpt integrity failure')
  return fragment.toString('utf8')
}

export async function writeHtmlPreviewNotices(item, output, root) {
  const packages = item.preview_tailwind === 3 ? ['tailwindcss', '@tailwindcss/forms'] : ['tailwindcss4']
  const notices = await Promise.all(packages.map(async name => name + '\n\n'
    + await readFile(resolve(root, 'node_modules', name, 'LICENSE'), 'utf8')))
  await writeFile(resolve(output, item.id + '.LICENSE.txt'), notices.join('\n\n'))
}

export async function buildHtmlPreview(item, data, output, root) {
  if (item.preview_adapter !== 'original-html-v1') return false
  const files = new Map()
  const boundary = await realpath(data)
  for (const file of item.files) {
    const path = await realpath(resolve(data, file.path))
    if (!path.startsWith(boundary + sep)) throw new Error('HTML source outside catalog')
    const raw = await readFile(path)
    if (hash(raw) !== file.sha256) throw new Error('HTML source integrity failure: ' + file.name)
    files.set(file.name, raw)
  }
  const document = item.files.find(file => file.path === item.preview_fragment?.path)
  if (!document) throw new Error('HTML excerpt document absent from manifest')
  const markup = extractFragment(files.get(document.name), item.preview_fragment)
  if (files.get('example.html')?.toString('utf8') !== markup) throw new Error('HTML example differs from source excerpt')
  const stylesheet = (name, parents = new Set()) => {
    if (parents.has(name) || !files.has(name)) throw new Error('Missing or cyclic HTML stylesheet: ' + name)
    const ancestors = new Set([...parents, name])
    return files.get(name).toString('utf8').replace(imports, (_, specifier) => {
      if (!specifier.startsWith('.')) throw new Error('Nonlocal HTML stylesheet import')
      return stylesheet(posix.normalize(posix.join(posix.dirname(name), specifier)), ancestors)
    })
  }
  const wrapper = item.preview_fragment.wrapper_class ?? ''
  const bodyClass = item.provider_id === 'sailboatui' ? 'antialiased text-secondary-500' : ''
  const rawContent = markup + ' ' + wrapper + ' ' + bodyClass
  let css
  if (item.preview_tailwind === 3 && item.provider_id === 'sailboatui') {
    // Mirrors the hash-reviewed upstream configuration; never require() its code.
    css = (await postcss([tailwindcss({
      content: [{ raw: rawContent, extension: 'html' }],
      theme: { extend: {
        fontFamily: { sans: ['Inter', ...defaultTheme.fontFamily.sans] },
        colors: { primary: colors.blue, secondary: colors.slate },
        maxWidth: { '8xl': '90rem' },
      } },
      plugins: [forms],
    })]).process(stylesheet(item.preview_css), { from: undefined })).css
  } else if (item.preview_tailwind === 4) {
    const compiler = await compile(await readFile(resolve(root, 'node_modules/tailwindcss4/index.css'), 'utf8')
      + '\n' + stylesheet(item.preview_css))
    const candidates = [...rawContent.matchAll(/\bclass\s*=\s*(["'])(.*?)\1/gs)]
      .flatMap(match => match[2].split(/\s+/))
    css = compiler.build([...candidates, ...wrapper.split(/\s+/)])
  } else throw new Error('Unreviewed HTML compiler configuration')
  css += '\nhtml,body{margin:0;min-height:100%;font-family:ui-sans-serif,system-ui,sans-serif}'
    + 'body{background:var(--background,#fff);color:var(--foreground,#111827)}'
    + '#ui-html-mount{min-height:100vh;display:grid;place-items:center;padding:24px;box-sizing:border-box}'
    + '#ui-html-fragment{max-width:100%}'
  const bridge = `let failed=false;const report=state=>{if(state==='ready'&&failed)return;if(state!=='ready')failed=true;parent.postMessage({type:'ui-library-preview',id:${JSON.stringify(item.id)},state},'*')};
window.addEventListener('error',()=>report('error'));
window.addEventListener('unhandledrejection',()=>report('error'));
window.addEventListener('securitypolicyviolation',()=>report('error'));
document.addEventListener('submit',e=>e.preventDefault());
document.addEventListener('click',e=>{if(e.target.closest('a'))e.preventDefault()});
setTimeout(()=>report('ready'),700);\n`
  const scripts = item.preview_scripts.map(name => {
    if (!files.has(name)) throw new Error('HTML script absent from manifest: ' + name)
    return files.get(name).toString('utf8')
  }).join('\n;\n')
  await writeFile(resolve(output, item.id + '.css'), css)
  await writeFile(resolve(output, item.id + '.js'), bridge + scripts)
  const csp = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
  await writeFile(resolve(output, item.id + '.html'), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><title>${escape(item.name.en)}</title><link rel="stylesheet" href="./${item.id}.css"></head><body class="${bodyClass}"><main id="ui-html-mount"><div id="ui-html-fragment" class="${escape(wrapper)}">${markup}</div></main><script src="./${item.id}.js"></script></body></html>`)
  await writeHtmlPreviewNotices(item, output, root)
  return true
}
