import { api } from './api'

/** pywebview injects window.pywebview.api in the packaged Mac app. */
function bridge() {
  return window.pywebview?.api
}

export function isDesktopApp() {
  return Boolean(bridge())
}

export function onBridgeReady(callback) {
  if (bridge()) {
    callback()
    return () => {}
  }
  window.addEventListener('pywebviewready', callback)
  return () => window.removeEventListener('pywebviewready', callback)
}

/**
 * kind: 'files' | 'folder' | 'output'. Returns absolute paths, or null when no native
 * picker exists (caller falls back to an <input type=file>).
 */
export async function pickPaths(kind, health) {
  if (bridge()?.pick) {
    const result = await bridge().pick(kind)
    return result?.paths || []
  }
  if (health?.native_dialogs && kind !== 'files') {
    const result = await api.pick(kind)
    return result.paths || []
  }
  return null
}

export async function downloadUrl(url, filename) {
  if (bridge()?.save_url) {
    const result = await bridge().save_url(url, filename || '')
    if (result?.error) throw new Error(result.error)
    return result
  }
  const link = document.createElement('a')
  link.href = url
  if (filename) link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  return { ok: true }
}

export async function downloadBlob(blob, filename) {
  if (bridge()?.save_text) {
    const result = await bridge().save_text(await blob.text(), filename)
    if (result?.error) throw new Error(result.error)
    return result
  }
  const url = URL.createObjectURL(blob)
  try {
    return await downloadUrl(url, filename)
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}

// The Mac app's Python side sees real paths of dropped files (the web view only sees
// File objects) and hands them over through this global, so files aren't copied.
let nativeDrop = null
let nativeWaiter = null
window.__imageLabNativeDrop = (paths) => {
  nativeDrop = { paths: Array.isArray(paths) ? paths : [], at: Date.now() }
  if (nativeWaiter) nativeWaiter()
}

/** Resolves with dropped absolute paths from the Mac app, or null if none arrive in time. */
export function nativeDropPaths(timeout = 700) {
  if (!isDesktopApp()) return Promise.resolve(null)
  const started = Date.now()
  const take = () => {
    if (nativeDrop && nativeDrop.at >= started - 1000 && nativeDrop.paths.length) {
      const { paths } = nativeDrop
      nativeDrop = null
      return paths
    }
    return null
  }
  const ready = take()
  if (ready) return Promise.resolve(ready)
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      nativeWaiter = null
      resolve(take())
    }, timeout)
    nativeWaiter = () => {
      clearTimeout(timer)
      nativeWaiter = null
      resolve(take())
    }
  })
}

/** Collect files from a drop, walking dropped folders. Must be called synchronously in the drop handler. */
export function filesFromDrop(dataTransfer) {
  const entries = [...(dataTransfer.items || [])]
    .filter((item) => item.kind === 'file')
    .map((item) => item.webkitGetAsEntry?.())
    .filter(Boolean)
  const plainFiles = [...(dataTransfer.files || [])]
  if (!entries.length) return Promise.resolve(plainFiles)

  const out = []
  const readEntries = (reader) => new Promise((resolve, reject) => reader.readEntries(resolve, reject))
  const fileOf = (entry) => new Promise((resolve, reject) => entry.file(resolve, reject))

  async function walk(entry) {
    if (entry.name.startsWith('.')) return
    if (entry.isFile) {
      out.push(await fileOf(entry))
    } else if (entry.isDirectory) {
      const reader = entry.createReader()
      let batch
      do {
        batch = await readEntries(reader)
        for (const child of batch) await walk(child)
      } while (batch.length)
    }
  }

  return (async () => {
    for (const entry of entries) await walk(entry)
    return out
  })()
}
