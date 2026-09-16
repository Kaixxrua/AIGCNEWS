// Only the mounting/packaging layer is ours. Components remain upstream originals.
import { build } from 'esbuild'
import { parse, compileScript, compileStyle } from '@vue/compiler-sfc'
import { readFile, writeFile, mkdir, readdir, unlink } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import postcss from 'postcss'
import tailwindcss from 'tailwindcss'
import { compile as compileTailwind4 } from 'tailwindcss4'
import { buildQualityPreview } from './quality-previews.mjs'
import { buildOriginalPreview } from './original-react-previews.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const data = resolve(root, '../mcp-go/internal/uicatalog/data')
const output = resolve(root, '.ui-previews/previews')
const { items } = JSON.parse(await readFile(resolve(data, 'catalog.json'), 'utf8'))
const selectedPrefixes = process.env.UI_PREVIEW_IDS_FILE ? JSON.parse(await readFile(process.env.UI_PREVIEW_IDS_FILE, 'utf8')) : process.argv.slice(2)
await mkdir(output, { recursive: true })
// Remove only stale flat outputs. Reviewed application packages use subdirectories.
for (const entry of await readdir(output, { withFileTypes: true })) {
  if (entry.isFile() && !items.some(item => entry.name.startsWith(`${item.id}.`))) await unlink(resolve(output, entry.name))
}

const vuePlugin = {
  name: 'upstream-vue',
  setup(builder) {
    builder.onLoad({ filter: /\.vue$/ }, async ({ path }) => {
      const source = await readFile(path, 'utf8')
      const { descriptor } = parse(source, { filename: path })
      const id = Buffer.from(path).toString('hex').slice(-16)
      const script = compileScript(descriptor, { id, inlineTemplate: true })
      let code = script.content
      // Nuxt supplies this auto-import; standalone previews supply it explicitly.
      if (source.includes('useTemplateRef(') && !/import\s*\{[^}]*useTemplateRef/s.test(source)) {
        code = 'import { useTemplateRef } from "vue";\n' + code
      }
      for (const style of descriptor.styles) {
        const css = compileStyle({ source: style.content, id, scoped: false }).code
        code += `\n{ const style = document.createElement('style'); style.textContent = ${JSON.stringify(css)}; document.head.append(style); }`
      }
      return { contents: code, loader: 'ts', resolveDir: dirname(path) }
    })
    builder.onResolve({ filter: /^@inspira-ui\/plugins$/ }, () => ({ path: 'cn', namespace: 'integration' }))
    builder.onLoad({ filter: /.*/, namespace: 'integration' }, () => ({ contents: 'import {clsx} from "clsx"; import {twMerge} from "tailwind-merge"; export const cn=(...args)=>twMerge(clsx(args));', loader: 'js', resolveDir: root }))
    builder.onResolve({ filter: /^@\/lib\/utils$/ }, args => ({ path: resolve(data, args.importer.includes('/motion/') || args.importer.includes('\\motion\\') ? 'sources/motion/lib/utils.ts' : 'sources/uilayouts/apps/ui-layout/lib/utils.ts') }))
    builder.onResolve({ filter: /^@\/components\/core\// }, args => ({ path: resolve(data, `sources/motion/${args.path.slice(2)}.tsx`) }))
    builder.onResolve({ filter: /\?raw$/ }, (args) => ({ path: resolve(args.resolveDir, args.path.replace(/\?raw$/, '')), namespace: 'raw' }))
    builder.onLoad({ filter: /.*/, namespace: 'raw' }, async (args) => ({ contents: `export default ${JSON.stringify(await readFile(args.path, 'utf8'))}`, loader: 'js' }))
  },
}
const statusCode = `
let failed = false;
const report = (state) => { if (state === 'ready' && failed) return; if (state !== 'ready') failed = true; parent.postMessage({type:'ui-library-preview', id:${'ITEM_ID'}, state}, '*'); };
window.addEventListener('error', () => report('error'));
window.addEventListener('unhandledrejection', () => report('error'));
const needsGPU = ${'NEEDS_GPU'};
const contextCanvas = needsGPU ? document.createElement('canvas') : null;
const gpu = contextCanvas && (contextCanvas.getContext('webgl2') || contextCanvas.getContext('webgl'));
if (!gpu && needsGPU) report('unsupported');
else setTimeout(() => report('ready'), 600);
if (gpu) gpu.getExtension('WEBGL_lose_context')?.loseContext();
`
for (const item of items) {
  if (selectedPrefixes.length && !selectedPrefixes.some(prefix => item.id.startsWith(prefix))) continue
  // These complete applications already have pinned, visually reviewed builds.
  // uiLibraryAssets verifies their files and hashes during the production build.
  if (item.preview_package && Object.keys(item.preview_files ?? {}).length) continue
  if (await buildQualityPreview(item, data, output, root)) continue
  if (await buildOriginalPreview(item, data, output, root)) continue
  const source = resolve(data, item.files[0].path)
  if (item.provider_id === 'galaxy') {
    const original = await readFile(source, 'utf8')
    const originalCSS = [...original.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/gi)].map(match => match[1]).join('\n')
    const markup = original.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
    let css = originalCSS
    if (item.dependencies.tailwindcss) css = (await postcss([tailwindcss({ content: [{ raw: original, extension: 'html' }] })]).process('@tailwind base;@tailwind utilities;', { from: undefined })).css + css
    const parsed = postcss.parse(css)
    parsed.walkRules(rule => { if (rule.selector.includes(':hover')) rule.selector = rule.selector.replaceAll(':hover', ':is(:hover,[data-ui-hover])') })
    const baseCSS = 'html,body{margin:0;width:100%;min-height:100%;font-family:system-ui,sans-serif}body{background:#f3f4f6;color:#111827}#ui-original-mount{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;box-sizing:border-box}*,*:before,*:after{box-sizing:border-box}'
    await writeFile(resolve(output, `${item.id}.css`), baseCSS + parsed.toString())
    const bridge = `window.addEventListener('message',e=>{if(e.source!==parent||e.data?.type!=='ui-library-pointer')return;document.querySelectorAll('[data-ui-hover]').forEach(el=>el.removeAttribute('data-ui-hover'));if(e.data.leave)return;let el=document.elementFromPoint(e.data.x,e.data.y);while(el){el.setAttribute('data-ui-hover','');el=el.parentElement}});document.addEventListener('submit',e=>e.preventDefault());`
    await writeFile(resolve(output, `${item.id}.js`), bridge + statusCode.replace('ITEM_ID', JSON.stringify(item.id)).replace('NEEDS_GPU', 'false'))
    const csp = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
    await writeFile(resolve(output, `${item.id}.html`), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><title>${item.id}</title><link rel="stylesheet" href="./${item.id}.css"></head><body><div id="ui-original-mount">${markup}</div><script src="./${item.id}.js"></script></body></html>`)
    continue
  }
  if (item.frameworks.includes('html')) {
    const original = await readFile(source, 'utf8')
    const content = original.match(/<body[^>]*>([\s\S]*?)<\/body>/i)?.[1]
    const classes = original.match(/<body[^>]*class="([^"]*)"/i)?.[1] ?? ''
    if (!content) throw new Error(`Missing original HTML body: ${item.id}`)
    const css = await readFile(resolve(data, item.assets[0].path), 'utf8')
    const helper = await readFile(resolve(data, item.files[1].path), 'utf8')
    await writeFile(resolve(output, `${item.id}.css`), css + '\nhtml,body{margin:0;min-height:100%;font-family:system-ui,sans-serif}body{background:#fff;color:#111827}#preview-mount{min-height:100vh;display:grid;place-items:center;padding:20px}.original-body{max-width:100%;width:100%}')
    await writeFile(resolve(output, `${item.id}.js`), helper + statusCode.replace('ITEM_ID', JSON.stringify(item.id)).replace('NEEDS_GPU', 'false'))
    const csp = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
    await writeFile(resolve(output, `${item.id}.html`), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><title>${item.name.en}</title><link rel="stylesheet" href="./${item.id}.css"></head><body><main id="preview-mount"><div class="original-body ${classes}">${content}</div></main><script src="./${item.id}.js"></script></body></html>`)
    continue
  }
  let entry
  if (item.frameworks.includes('vue')) {
    const helper = resolve(data, 'sources/inspira/app/components/inspira/ui/shader-toy/ShaderToy.vue')
    entry = `import {createApp,h} from 'vue'; import Component from ${JSON.stringify(source)}; const app=createApp({render:()=>h(Component)});`
    if (item.id === 'inspira-bg-silk') entry += `import ShaderToy from ${JSON.stringify(helper)}; app.component('ShaderToy',ShaderToy);`
    entry += `app.mount('#root');`
  } else {
    const name = item.export_name
    entry = `import React from 'react'; import {createRoot} from 'react-dom/client'; import {${name} as Component} from ${JSON.stringify(source)};`
    if (item.id === 'uilayouts-spotlight') {
      entry += `import {SpotLightItem} from ${JSON.stringify(source)}; createRoot(document.getElementById('root')).render(<Component className="grid grid-cols-2 gap-4 p-8 w-full"><SpotLightItem className="p-px rounded-xl"><div className="relative z-10 bg-neutral-950 rounded-xl p-10">Spotlight</div></SpotLightItem><SpotLightItem className="p-px rounded-xl"><div className="relative z-10 bg-neutral-950 rounded-xl p-10">Move your cursor</div></SpotLightItem></Component>);`
    } else {
      entry += `createRoot(document.getElementById('root')).render(<Component {...${JSON.stringify(item.props)}} />);`
    }
  }
  entry = statusCode.replace('ITEM_ID', JSON.stringify(item.id)).replace('NEEDS_GPU', String(item.category === 'shader' || item.provider_id === 'threeui')) + entry
  await build({ stdin: { contents: entry, loader: 'tsx', resolveDir: root }, outfile: resolve(output, `${item.id}.js`),
    bundle: true, minify: true, format: 'iife', platform: 'browser', jsx: 'automatic', nodePaths: [resolve(root, 'node_modules')],
    define: { 'process.env.NODE_ENV': '"production"', '__VUE_OPTIONS_API__': 'true', '__VUE_PROD_DEVTOOLS__': 'false', '__VUE_PROD_HYDRATION_MISMATCH_DETAILS__': 'false' }, plugins: [vuePlugin], legalComments: 'linked' })
  const originals = await Promise.all(item.files.filter(file => /\.(tsx|vue|css)$/.test(file.path)).map(file => readFile(resolve(data, file.path), 'utf8')))
  const rawContent = entry + originals.join('\n')
  let utilitiesCSS
  if (item.provider_id === 'motion') {
    const baseCSS = await readFile(resolve(root, 'node_modules/tailwindcss4/index.css'), 'utf8')
    const compiler = await compileTailwind4(baseCSS + '\n@custom-variant dark (&:where(.dark, .dark *));')
    const candidates = rawContent.match(/[^\s"'`<>]+/g) ?? []
    utilitiesCSS = compiler.build(candidates)
  } else {
    const utilities = await postcss([tailwindcss({ content: [{ raw: rawContent, extension: 'html' }], corePlugins: { preflight: false } })]).process('@tailwind utilities;', { from: undefined })
    utilitiesCSS = utilities.css
  }
  let css = 'html,body,#root{width:100%;height:100%;margin:0;overflow:hidden}body{background:#080a0c;color:#f5f5f5;font-family:system-ui,sans-serif}#root{position:relative;display:grid;place-items:center}*,*:before,*:after{box-sizing:border-box}canvas{display:block}' + utilitiesCSS
  if (item.provider_id === 'threeui') {
    const font = await readFile(resolve(data, item.assets[0].path))
    const originalCSS = await readFile(resolve(data, 'sources/threeui/src/shaders/community.css'), 'utf8')
    css += originalCSS.replace('./fonts/fragment-mono.woff2', `data:font/woff2;base64,${font.toString('base64')}`)
  }
  if (item.category === 'text' && item.provider_id === 'uilayouts') css += '#root{font-size:clamp(18px,4vw,40px);font-family:monospace}'
  if (item.provider_id === 'motion') css += 'body{background:#fff;color:#09090b}#root{padding:24px}'
  await writeFile(resolve(output, `${item.id}.css`), css)
  // No same-origin capability, outbound connections, forms or top navigation.
  const csp = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
  await writeFile(resolve(output, `${item.id}.html`), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${csp}"><title>${item.name.en}</title><link rel="stylesheet" href="./${item.id}.css"></head><body><div id="root"></div><script src="./${item.id}.js"></script></body></html>`)
}
console.log('Prepared requested previews; preserved reviewed application packages.')
