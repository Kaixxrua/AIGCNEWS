import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync, brotliCompressSync } from 'node:zlib'

const hash = data => createHash('sha256').update(data).digest('hex')
const supportedBoot = '123367bbd2940a4989dcf12aed74b825dbb81f7dd501cb0a8e40f7188407c1c3'

// Derive delivery-only files after the private release has passed its pinned
// staging contract. Never modify the private source, Godot packs, or ready gate.
export function prepareSceneDelivery(scene) {
  if (!existsSync(scene)) return
  const marker = 'meadow-delivery-manifest.js'
  if (existsSync(resolve(scene, marker))) {
    if (readFileSync(resolve(scene, 'meadow-delivery.js'), 'utf8') !== readFileSync(new URL('./scene-delivery.js', import.meta.url), 'utf8'))
      throw Error('Delivery adapter changed; restage the pinned private release before rebuilding')
    return
  }
  let boot = readFileSync(resolve(scene, 'meadow-boot.js'), 'utf8')
  if (hash(boot) !== supportedBoot) throw Error('Unreviewed Godot bootstrap; review delivery adapter before building')
  const assets = Object.fromEntries(readdirSync(scene).filter(n => /\.(pck|wasm)$/.test(n)).map(name => {
    const bytes = readFileSync(resolve(scene, name))
    return [name, { sha256: hash(bytes), bytes: bytes.length }]
  }))
  let html = readFileSync(resolve(scene, 'index.html'), 'utf8')
  if (!/<script src="meadow-engine-preload\.js[^"]*"><\/script>/.test(html) || !/meadow-boot\.js\?v=[a-f0-9]+/.test(html))
    throw Error('Unreviewed Godot entrypoint; restage and review the delivery adapter')
  const put = (name, value) => {
    writeFileSync(resolve(scene, name), value)
    writeFileSync(resolve(scene, name + '.gz'), gzipSync(value))
    writeFileSync(resolve(scene, name + '.br'), brotliCompressSync(value))
  }
  boot = boot.replace('const deadline = performance.now() + 90000;', 'let deadline = performance.now() + 90000;\n      let phase = "引擎初始化";')
    .replace("Error('场景启动超时（90秒），请刷新后重试')", 'Error(`${phase}超时，请重新载入`)')
    .replace('const timer = setTimeout(() => cancel(timeout()), 90000);', `const timer = setInterval(() => { state.isOpen(); }, 1000);
      const progress = event => {
        if (event.detail.file !== config.mainPack || state.closed) return;
        deadline = performance.now() + 120000;
        options.onProgress?.(event.detail.loaded, event.detail.total);
      };
      window.addEventListener('meadow-download', progress);`)
    .replace('const core = fetch(config.mainPack,', 'phase = "素材下载停滞（120秒无进展）";\n        deadline = performance.now() + 120000;\n        const core = fetch(config.mainPack,')
    .replace("engine.copyToFS('/meadow-core.pck', bytes);", "phase = '场景初始化（90秒）';\n        deadline = performance.now() + 90000;\n        engine.copyToFS('/meadow-core.pck', bytes);")
    .replace('clearTimeout(timer);', "clearInterval(timer);\n        window.removeEventListener('meadow-download', progress);")
  put('meadow-boot.js', boot)
  put(marker, `window.MEADOW_DELIVERY = ${JSON.stringify({ cdn: 'https://scene.aigcnews.cn/camp-scene/', assets })};\n`)
  const runtime = readFileSync(new URL('./scene-delivery.js', import.meta.url), 'utf8')
  put('meadow-delivery.js', runtime)
  // The transport warms the shared engine once; avoid a second, unversioned
  // same-origin <link preload> competing with the CDN transfer.
  put('meadow-engine-preload.js', '/* Shared engine warmup is owned by meadow-delivery.js. */\n')
  html = html.replace(/<script src="meadow-engine-preload\.js[^\"]*"><\/script>/,
    `<script src="${marker}?v=${hash(readFileSync(resolve(scene, marker))).slice(0, 16)}"></script>\n  <script src="meadow-delivery.js?v=${hash(runtime).slice(0, 16)}"></script>`)
  html = html.replace(/meadow-boot\.js\?v=[a-f0-9]+/, `meadow-boot.js?v=${hash(boot).slice(0, 16)}`)
  put('index.html', html)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  prepareSceneDelivery(resolve(dirname(fileURLToPath(import.meta.url)), '../public/camp-scene'))
}
