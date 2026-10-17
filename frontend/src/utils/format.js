export function formatBytes(bytes) {
  if (bytes == null || Number.isNaN(bytes)) return '—'
  const abs = Math.abs(bytes)
  if (abs < 1024) return `${bytes} B`
  if (abs < 1024 * 1024) return `${(bytes / 1024).toFixed(abs < 10 * 1024 ? 1 : 0)} KB`
  if (abs < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(abs < 100 * 1024 ** 2 ? 2 : 1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

export function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return `${m}m ${String(s).padStart(2, '0')}s`
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`
}

export function formatDims(dims) {
  if (!dims || !dims[0]) return '—'
  return `${dims[0]}×${dims[1]}`
}

export function plural(count, word, pluralWord = `${word}s`) {
  return `${count.toLocaleString()} ${count === 1 ? word : pluralWord}`
}

export function savingsLabel(percent) {
  if (percent == null) return ''
  if (percent > 0) return `−${percent}%`
  if (percent < 0) return `+${Math.abs(percent)}%`
  return '0%'
}

export const ACCEPTED_EXTENSIONS = [
  '.jpg',
  '.jpeg',
  '.jpe',
  '.jfif',
  '.png',
  '.webp',
  '.avif',
  '.gif',
  '.bmp',
  '.tif',
  '.tiff',
  '.heic',
  '.heif',
]

export function isAcceptedFile(name) {
  const lower = (name || '').toLowerCase()
  if (lower.startsWith('.')) return false
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

const FORMAT_EXT = { JPEG: '.jpg', PNG: '.png', WEBP: '.webp', AVIF: '.avif', TIFF: '.tiff', GIF: '.gif', BMP: '.bmp' }

/** Mirrors plan_output_path() naming in backend/processor/pipeline.py. */
export function exampleOutputName(filename, settings) {
  const name = filename || 'IMG_0001.jpg'
  const dot = name.lastIndexOf('.')
  const stem = dot > 0 ? name.slice(0, dot) : name
  const ext = dot > 0 ? name.slice(dot) : '.jpg'
  const outExt = settings.output_format === 'keep' ? (ext.toLowerCase().startsWith('.heic') || ext.toLowerCase().startsWith('.heif') ? '.jpg' : ext) : FORMAT_EXT[settings.output_format] || ext
  if (settings.replace_originals) return `${stem}${outExt}`
  return `${settings.naming_prefix || ''}${stem}${settings.naming_suffix || ''}${outExt}`
}

export function shortenPath(path, max = 42) {
  if (!path) return ''
  const home = path.match(/^\/Users\/[^/]+/)
  let p = home ? `~${path.slice(home[0].length)}` : path
  if (p.length <= max) return p
  // Keep the first segment and the tail, dropping middle folders until it fits.
  const parts = p.split('/')
  const head = parts[0]
  const tail = parts.slice(1)
  while (tail.length > 2 && [head, '…', ...tail].join('/').length > max) tail.shift()
  p = tail.length < parts.length - 1 ? [head, '…', ...tail].join('/') : p
  return p.length > max ? `…${p.slice(-max + 1)}` : p
}
