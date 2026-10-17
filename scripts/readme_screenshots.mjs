// Captures the README screenshots from a running Image Lab server using headless Chrome.
//
//   node scripts/readme_screenshots.mjs <server-url> <photos-dir> <out-dir>
//
// <photos-dir> needs two folders of JPEGs: Trip/ (shown first) and More/ (added for the batch shot).
// Use a throwaway server (IMAGE_LAB_DATA_DIR=$(mktemp -d)): the script fills and processes its queue.
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, readdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const [BASE, PHOTOS, OUT] = process.argv.slice(2).map((a, i) => (i ? resolve(a) : a.replace(/\/$/, '')))
if (!OUT) {
  console.error('usage: node scripts/readme_screenshots.mjs <server-url> <photos-dir> <out-dir>')
  process.exit(2)
}
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const WIDTH = 1440
const HEIGHT = 860
const DEBUG_PORT = 9334
const SETTINGS = {
  compress_mode: 'target_size',
  target_size: 900,
  target_unit: 'KB',
  resize_enabled: true,
  max_width: 2560,
  max_height: 2560,
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const hardStop = setTimeout(() => fail('timed out'), 240000)
const profile = mkdtempSync(join(tmpdir(), 'imglab-shots-'))
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', 'about:blank',
], { stdio: 'ignore' })

function fail(message) {
  console.error(`✗ ${message}`)
  finish(1)
}
function finish(code) {
  clearTimeout(hardStop)
  try { chrome.kill('SIGKILL') } catch {}
  process.exit(code)
}

let ws
let nextId = 0
const pending = new Map()
function send(method, params = {}) {
  const id = ++nextId
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out`)) }, 20000)
    pending.set(id, (msg) => { clearTimeout(timer); msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result) })
  })
}
async function evaluate(expression) {
  const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || 'evaluate failed')
  return r.result.value
}
async function waitFor(label, expression, timeout = 30000) {
  const end = Date.now() + timeout
  while (Date.now() < end) {
    if (await evaluate(expression)) return
    await sleep(150)
  }
  const state = await evaluate(`JSON.stringify({
    rows: document.querySelectorAll('.q-row').length,
    imgs: [...document.querySelectorAll('.compare-img')].map((i) => [i.complete, i.naturalWidth]),
    busy: document.querySelector('.busy-chip')?.textContent,
    stage: document.querySelector('main, .stage')?.innerText.slice(0, 200),
  })`).catch((e) => e.message)
  fail(`waiting for ${label}: ${state}`)
}
async function api(path, body) {
  const res = await fetch(BASE + path, {
    method: body ? 'POST' : 'GET',
    headers: { 'content-type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) fail(`${path}: HTTP ${res.status}`)
  return res.json()
}
async function load(theme) {
  await send('Page.navigate', { url: BASE + '/' })
  await sleep(400)
  await evaluate(`localStorage.setItem('image-lab-theme', ${JSON.stringify(theme)});
    localStorage.setItem('image-lab-settings-v2', ${JSON.stringify(JSON.stringify(SETTINGS))}); location.reload(); 1`)
  await sleep(400)
  await waitFor('app', `!!document.querySelector('.topbar, .app')`)
}
const previewReady = `(() => {
  const imgs = [...document.querySelectorAll('.compare-img')]
  return imgs.length >= 2 && imgs.every((i) => i.complete && i.naturalWidth > 0) && !document.querySelector('.busy-chip')
})()`
async function select(name) {
  await evaluate(`[...document.querySelectorAll('.q-row')].find((r) => r.querySelector('.q-name')?.textContent.trim() === ${JSON.stringify(name)})?.click(); 1`)
  await sleep(300)
  await waitFor(`preview of ${name}`, previewReady)
  await sleep(500)
}
async function shot(name) {
  await evaluate(`document.activeElement?.blur(); 1`)
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
  console.log(`✓ ${name}.png`)
}
const jpegs = (dir) => readdirSync(join(PHOTOS, dir)).filter((f) => /\.jpe?g$/i.test(f)).sort().map((f) => join(PHOTOS, dir, f))

let opened
for (let i = 0; i < 50 && !ws; i++) {
  try {
    const page = (await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`)).json()).find((t) => t.type === 'page')
    if (page) {
      ws = new WebSocket(page.webSocketDebuggerUrl)
      opened = new Promise((r) => ws.addEventListener('open', r))
      break
    }
  } catch {}
  await sleep(200)
}
if (!ws) fail('could not start Chrome')
await opened
ws.addEventListener('message', (e) => {
  const msg = JSON.parse(e.data)
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id) }
})
mkdirSync(OUT, { recursive: true })
await send('Page.enable')
await send('Runtime.enable')
await send('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: HEIGHT, deviceScaleFactor: 2, mobile: false })

const trip = jpegs('Trip')
await api('/api/queue/paths', { paths: trip })

// 1. Live preview of the current settings before anything is processed.
await load('dark')
await select('DSC_0472.jpg')
await shot('preview')

// 2. A bigger batch mid-run.
await api('/api/queue/paths', { paths: jpegs('More') })
await load('dark')
await waitFor('queue rows', `document.querySelectorAll('.q-row').length >= ${trip.length + 8}`)
await evaluate(`document.querySelector('.process-btn').click(); 1`)
await waitFor('batch progress', `(async () => { const s = await (await fetch('/api/process/status')).json(); return s.done >= 10 })()`, 60000)
await sleep(250)
await shot('batch')

// 3. Finished batch, dark and light.
await waitFor('batch to finish', `(async () => { const s = await (await fetch('/api/process/status')).json(); return !s.running })()`, 120000)
await sleep(800)
await select('DSC_0412.jpg')
await shot('done-dark')
await load('light')
await select('DSC_0412.jpg')
await shot('done-light')
finish(0)
