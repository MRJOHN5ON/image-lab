export class ApiError extends Error {
  constructor(message, { status = 0, field = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.field = field
  }
}

function errorMessage(data, text, status) {
  const detail = data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg || String(d)).join('; ')
  if (text && text.length < 300) return text
  return `Request failed (${status})`
}

async function request(path, { method = 'GET', json, signal } = {}) {
  const options = { method, signal, headers: {} }
  if (json !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(json)
  }
  let response
  try {
    response = await fetch(`/api${path}`, options)
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new ApiError("Can't reach the Image Lab engine. Is it still running?")
  }
  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = null
  }
  if (!response.ok) {
    throw new ApiError(errorMessage(data, text, response.status), {
      status: response.status,
      field: data?.field ?? null,
    })
  }
  return data
}

export const api = {
  health: () => request('/health'),
  queue: () => request('/queue'),
  addPaths: (paths, recursive = true) => request('/queue/paths', { method: 'POST', json: { paths, recursive } }),
  remove: (ids) => request('/queue/remove', { method: 'POST', json: { ids } }),
  clear: (scope = 'all') => request(`/queue?scope=${scope}`, { method: 'DELETE' }),
  process: (settings, itemIds) => request('/process', { method: 'POST', json: { settings, item_ids: itemIds } }),
  cancel: () => request('/process/cancel', { method: 'POST' }),
  status: () => request('/process/status'),
  preview: (itemId, settings, signal) =>
    request('/preview', { method: 'POST', json: { item_id: itemId, settings }, signal }),
  presets: () => request('/presets'),
  savePreset: (preset) => request('/presets', { method: 'POST', json: preset }),
  deletePreset: (id) => request(`/presets/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  reveal: (path) => request('/system/reveal', { method: 'POST', json: { path } }),
  pick: (kind) => request('/system/pick', { method: 'POST', json: { kind } }),
}

export const urls = {
  thumbnail: (id) => `/api/items/${id}/thumbnail`,
  source: (id) => `/api/items/${id}/source`,
  output: (id, download = false) => `/api/items/${id}/output${download ? '?download=1' : ''}`,
  zip: (ids) => (ids?.length ? `/api/export/zip?ids=${ids.join(',')}` : '/api/export/zip'),
  csv: '/api/report?format=csv',
}

const BATCH_FILES = 40
const BATCH_BYTES = 256 * 1024 * 1024

function chunkFiles(files) {
  const batches = []
  let current = []
  let bytes = 0
  for (const file of files) {
    if (current.length && (current.length >= BATCH_FILES || bytes + file.size > BATCH_BYTES)) {
      batches.push(current)
      current = []
      bytes = 0
    }
    current.push(file)
    bytes += file.size
  }
  if (current.length) batches.push(current)
  return batches
}

function uploadBatch(files, onProgress) {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    for (const file of files) form.append('files', file, file.name)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/queue/upload')
    xhr.responseType = 'json'
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response)
      else reject(new ApiError(errorMessage(xhr.response, '', xhr.status), { status: xhr.status }))
    }
    xhr.onerror = () => reject(new ApiError('Upload failed — connection to Image Lab was lost'))
    xhr.send(form)
  })
}

/** Upload in batches so huge drops don't hit multipart limits; reports cumulative bytes. */
export async function uploadFiles(files, onProgress = () => {}) {
  const total = files.reduce((sum, f) => sum + f.size, 0)
  const merged = { added: [], rejected: [], duplicates: 0 }
  let done = 0
  for (const batch of chunkFiles(files)) {
    const batchBytes = batch.reduce((sum, f) => sum + f.size, 0)
    const result = await uploadBatch(batch, (loaded) => onProgress(done + loaded, total))
    done += batchBytes
    onProgress(done, total)
    merged.added.push(...(result.added || []))
    merged.rejected.push(...(result.rejected || []))
    merged.duplicates += result.duplicates || 0
  }
  return merged
}
