/** Defaults mirror ProcessingSettings in backend/processor/pipeline.py. */
export const DEFAULT_SETTINGS = {
  compress_enabled: true,
  resize_enabled: false,
  upscale_enabled: false,
  strip_metadata: true,
  keep_icc: true,
  auto_rotate: true,
  trim_transparent: false,

  compress_mode: 'target_size',
  target_size: 12,
  target_unit: 'MB',
  quality: 85,
  progressive: true,
  subsampling: 0,
  png_palette: false,
  png_colors: 256,
  never_larger: true,

  resize_mode: 'fit',
  max_width: null,
  max_height: null,
  exact_width: null,
  exact_height: null,
  fit_mode: 'cover',
  scale_percent: null,
  allow_enlarge: false,
  resample: 'lanczos',

  upscale_factor: 2,

  output_format: 'keep',
  bg_color: '#ffffff',

  output_dir: '',
  naming_prefix: '',
  naming_suffix: '_processed',
  on_conflict: 'overwrite',
  replace_originals: false,
  preserve_dates: false,
}

const STORAGE_KEY = 'image-lab-settings-v2'
const LEGACY_KEY = 'image-lab-settings'
const KNOWN = Object.keys(DEFAULT_SETTINGS)

/** Accept settings from Image Lab 1.x (same rules as _migrate in the backend). */
export function migrateSettings(raw) {
  const data = { ...(raw && typeof raw === 'object' ? raw : {}) }
  if (!('strip_metadata' in data) && 'strip_exif' in data) data.strip_metadata = data.strip_exif
  if (!('target_size' in data)) {
    if (data.target_size_kb != null && data.target_size_kb !== '') {
      data.target_size = data.target_size_kb
      data.target_unit = 'KB'
    } else if (data.target_size_mb != null && data.target_size_mb !== '') {
      data.target_size = data.target_size_mb
      data.target_unit = 'MB'
    }
  }
  if (data.compress_mode === 'lossless_first') data.compress_mode = 'lossless'
  if (data.convert_enabled === false && 'output_format' in data) data.output_format = 'keep'
  if (data.fit_mode === 'crop_center') data.fit_mode = 'cover'
  if (!('resize_mode' in data)) {
    if (data.scale_percent) data.resize_mode = 'scale'
    else if (data.exact_width || data.exact_height) data.resize_mode = 'exact'
  }
  if (!('on_conflict' in data) && data.overwrite === true) data.on_conflict = 'overwrite'
  if (!('quality' in data) && data.webp_quality != null) data.quality = data.webp_quality
  if (typeof data.output_format === 'string' && data.output_format.toLowerCase() !== 'keep') {
    data.output_format = data.output_format.toUpperCase() === 'JPG' ? 'JPEG' : data.output_format.toUpperCase()
  }

  const clean = {}
  for (const key of KNOWN) if (key in data) clean[key] = data[key]
  if (clean.output_dir == null) clean.output_dir = ''
  return clean
}

export function withDefaults(raw) {
  return { ...DEFAULT_SETTINGS, ...migrateSettings(raw) }
}

export function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) ?? localStorage.getItem(LEGACY_KEY)
    if (raw) return withDefaults(JSON.parse(raw))
  } catch {
    /* corrupt storage falls back to defaults */
  }
  return { ...DEFAULT_SETTINGS }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    /* storage full or disabled */
  }
}

export function sameSettings(a, b) {
  return KNOWN.every((key) => (a[key] ?? null) === (b[key] ?? null))
}

/** Where results go is the user's choice, not the preset's — unless the preset says otherwise. */
const OUTPUT_KEYS = ['output_dir', 'on_conflict', 'replace_originals', 'preserve_dates', 'naming_prefix', 'naming_suffix']

export function applyPreset(preset, current) {
  const next = withDefaults(preset.settings)
  const specified = migrateSettings(preset.settings)
  for (const key of OUTPUT_KEYS) if (!(key in specified)) next[key] = current[key]
  return next
}

export function presetMatches(preset, settings) {
  return sameSettings(applyPreset(preset, settings), settings)
}

export function exportSettingsFile(settings) {
  const blob = new Blob([JSON.stringify({ app: 'Image Lab', version: 2, settings }, null, 2)], {
    type: 'application/json',
  })
  return { blob, filename: 'image-lab-settings.json' }
}

export async function readSettingsFile(file) {
  const text = await file.text()
  const parsed = JSON.parse(text)
  return withDefaults(parsed.settings ?? parsed)
}
