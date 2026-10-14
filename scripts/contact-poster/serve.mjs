import { createReadStream, existsSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize } from 'node:path'
const root = process.argv[2]; const port = Number(process.argv[3] || 4191)
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.wasm': 'application/wasm', '.pck': 'application/octet-stream', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.ttf': 'font/ttf' }
createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
  const rel = normalize(pathname).replace(/^(\.\.(\/|\\|$))+/, '').replace(/^[/\\]+/, '')
  let file = join(root, rel)
  if (!existsSync(file) || statSync(file).isDirectory()) { if (rel === '' ) file = join(root, 'index.html'); else { console.log('404', pathname); res.statusCode = 404; return res.end() } }
  console.log(req.method, pathname)
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin'); res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp'); res.setHeader('Cross-Origin-Resource-Policy', 'same-origin')
  res.setHeader('Content-Type', types[extname(file)] || 'application/octet-stream'); res.setHeader('Content-Length', statSync(file).size)
  createReadStream(file).pipe(res)
}).listen(port, '127.0.0.1', () => console.log(`http://127.0.0.1:${port}`))
