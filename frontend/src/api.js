const API = '/api'

export async function fetchHealth() {
  const r = await fetch(`${API}/health`)
  return r.json()
}

export async function fetchQueue() {
  const r = await fetch(`${API}/queue`)
  return r.json()
}

export async function uploadFiles(files) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  const r = await fetch(`${API}/queue`, { method: 'POST', body: form })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function addPaths(paths, recursive = true) {
  const r = await fetch(`${API}/queue/paths`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths, recursive }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function clearQueue() {
  const r = await fetch(`${API}/queue`, { method: 'DELETE' })
  return r.json()
}

export async function startProcess(settings, itemIds) {
  const r = await fetch(`${API}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings, item_ids: itemIds }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function cancelProcess() {
  const r = await fetch(`${API}/process/cancel`, { method: 'POST' })
  return r.json()
}

export async function fetchProcessStatus() {
  const r = await fetch(`${API}/process/status`)
  return r.json()
}

export async function previewImage(path, settings) {
  const r = await fetch(`${API}/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, settings }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function fetchPresets() {
  const r = await fetch(`${API}/presets`)
  return r.json()
}

export async function savePreset(preset) {
  const r = await fetch(`${API}/presets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(preset),
  })
  return r.json()
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}
