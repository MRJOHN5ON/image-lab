export const DEFAULT_SETTINGS = {
  compress_enabled: true,
  resize_enabled: false,
  upscale_enabled: false,
  convert_enabled: false,
  strip_exif: true,
  keep_icc: false,
  auto_rotate: true,
  trim_transparent: false,
  compress_mode: 'target_size',
  target_size_mb: 12,
  target_size_kb: null,
  quality: 85,
  lossless_first: true,
  progressive: true,
  subsampling: 0,
  optimize: true,
  png_compression: 6,
  png_palette: false,
  webp_quality: 80,
  webp_lossless: false,
  webp_method: 4,
  avif_quality: 80,
  avif_speed: 6,
  max_width: null,
  max_height: null,
  exact_width: null,
  exact_height: null,
  scale_percent: null,
  fit_mode: 'contain',
  resample: 'lanczos',
  upscale_factor: 2,
  upscale_method: 'standard',
  output_format: 'keep',
  bg_color: '#ffffff',
  output_dir: '',
  naming_suffix: '_processed',
  naming_prefix: '',
  mirror_structure: false,
  overwrite: false,
  skip_existing: true,
}

export function loadSettingsFromStorage() {
  try {
    const raw = localStorage.getItem('image-lab-settings')
    if (raw) return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) }
  } catch (_) {}
  return { ...DEFAULT_SETTINGS }
}

export function saveSettingsToStorage(settings) {
  localStorage.setItem('image-lab-settings', JSON.stringify(settings))
}

export function exportSettings(settings) {
  const blob = new Blob([JSON.stringify(settings, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'image-lab-settings.json'
  a.click()
  URL.revokeObjectURL(url)
}

export function importSettings(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      try {
        resolve({ ...DEFAULT_SETTINGS, ...JSON.parse(reader.result) })
      } catch (e) {
        reject(e)
      }
    }
    reader.onerror = reject
    reader.readAsText(file)
  })
}
