import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { spawn } from 'node:child_process'

const source = readFileSync(process.argv[2], 'utf8')
const prefix = 'window.MEADOW_DELIVERY = '
if (!source.startsWith(prefix) || !source.trimEnd().endsWith(';')) throw Error('Invalid scene manifest')
const {cdn, assets} = JSON.parse(source.trim().slice(prefix.length, -1))
if (cdn !== 'https://scene.aigcnews.cn/camp-scene/') throw Error('Unapproved scene CDN')
const files = Object.keys(assets).filter(name => /^(index(?:-lite|-balanced)?\.(?:wasm|pck)|camp-bootstrap-[\w-]+\.pck)$/.test(name))
if (!files.includes('index.pck') || !files.includes('index.wasm')) throw Error('Scene manifest is incomplete')
// Sequential warmup avoids saturating the small origin uplink on a cold release.
for (const file of files) {
  const {sha256, bytes} = assets[file]
  if (!/^[a-f0-9]{64}$/.test(sha256) || !Number.isSafeInteger(bytes) || bytes <= 0) throw Error('Invalid asset pin')
  const transfer = spawn('curl', ['--fail', '--silent', '--show-error', '--compressed',
    '--connect-timeout', '15', '--max-time', '600', '--speed-limit', '1', '--speed-time', '30',
    '-H', 'Origin: https://aigcnews.cn', `${cdn}${file}?v=${sha256}`], {stdio: ['ignore', 'pipe', 'inherit']})
  const done = new Promise((resolve, reject) => {
    transfer.on('error', reject)
    transfer.on('close', code => code === 0 ? resolve() : reject(Error(`${file}: curl exited ${code}`)))
  })
  done.catch(() => {})
  const digest = createHash('sha256')
  let received = 0
  for await (const chunk of transfer.stdout) { digest.update(chunk); received += chunk.length }
  await done
  if (received !== bytes || digest.digest('hex') !== sha256) throw Error(`${file}: CDN integrity mismatch`)
  console.log(`${file}: verified ${received} bytes`)
}
