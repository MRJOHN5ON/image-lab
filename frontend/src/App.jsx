import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addPaths,
  cancelProcess,
  clearQueue,
  fetchHealth,
  fetchPresets,
  fetchProcessStatus,
  fetchQueue,
  formatBytes,
  previewImage,
  savePreset,
  startProcess,
  uploadFiles,
} from './api'
import {
  DEFAULT_SETTINGS,
  exportSettings,
  importSettings,
  loadSettingsFromStorage,
  saveSettingsToStorage,
} from './settings'
import './App.css'

function StatusBadge({ status }) {
  const colors = {
    pending: '#8b95a8',
    processing: '#4da3ff',
    done: '#3dd68c',
    failed: '#ff5c5c',
    skipped: '#f5a623',
    cancelled: '#8b95a8',
  }
  return (
    <span className="status-badge" style={{ color: colors[status] || colors.pending }}>
      {status}
    </span>
  )
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [queue, setQueue] = useState({ items: [], count: 0, total_size: 0 })
  const [settings, setSettings] = useState(loadSettingsFromStorage)
  const [presets, setPresets] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [progress, setProgress] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [toast, setToast] = useState(null)
  const [showTip, setShowTip] = useState(() => !localStorage.getItem('tip-dismissed'))
  const [dragOver, setDragOver] = useState(false)
  const [presetOpen, setPresetOpen] = useState(false)
  const fileInputRef = useRef(null)
  const pollRef = useRef(null)

  const refreshQueue = useCallback(async () => {
    const data = await fetchQueue()
    setQueue(data)
  }, [])

  useEffect(() => {
    fetchHealth().then(setHealth)
    fetchPresets().then((d) => setPresets(d.presets || []))
    refreshQueue()
  }, [refreshQueue])

  useEffect(() => {
    saveSettingsToStorage(settings)
  }, [settings])

  useEffect(() => {
    if (progress?.running) {
      pollRef.current = setInterval(async () => {
        const st = await fetchProcessStatus()
        setProgress(st)
        await refreshQueue()
        if (!st.running) {
          clearInterval(pollRef.current)
          setToast(
            `${st.completed} images processed in ${st.elapsed_seconds}s — saved ${st.mb_saved} MB`,
          )
          setTimeout(() => setToast(null), 6000)
        }
      }, 400)
      return () => clearInterval(pollRef.current)
    }
  }, [progress?.running, refreshQueue])

  const updateSetting = (key, value) => {
    setSettings((s) => ({ ...s, [key]: value }))
  }

  const handleFiles = async (fileList) => {
    const files = Array.from(fileList)
    if (!files.length) return
    if (files.length > 500 && !window.confirm(`Process ${files.length} files? This may take a while.`)) {
      return
    }
    try {
      await uploadFiles(files)
      await refreshQueue()
    } catch (e) {
      alert('Upload failed: ' + e.message)
    }
  }

  const onDrop = async (e) => {
    e.preventDefault()
    setDragOver(false)
    const items = e.dataTransfer.items
    const files = []
    const paths = []

    if (items) {
      for (const item of items) {
        if (item.kind === 'file') {
          const entry = item.webkitGetAsEntry?.()
          if (entry?.isDirectory) {
            alert('Folder drop: use file picker or drag individual files. For local paths, use Settings → Add folder path.')
            continue
          }
          const f = item.getAsFile()
          if (f) files.push(f)
        }
      }
    } else {
      files.push(...Array.from(e.dataTransfer.files))
    }

    if (files.length) await handleFiles(files)
    if (paths.length) {
      await addPaths(paths)
      await refreshQueue()
    }
  }

  const applyPreset = (preset) => {
    setSettings((s) => ({ ...s, ...preset.settings }))
    setPresetOpen(false)
  }

  const runProcess = async () => {
    if (!queue.count) return
    if (settings.overwrite && !window.confirm('Overwrite existing files? Originals may be replaced.')) {
      return
    }
    try {
      const result = await startProcess(settings)
      setProgress(result.progress)
    } catch (e) {
      alert('Failed to start: ' + e.message)
    }
  }

  const runPreview = async () => {
    const item = queue.items.find((i) => i.id === selectedId) || queue.items[0]
    if (!item) return
    setPreviewLoading(true)
    try {
      const data = await previewImage(item.path, settings)
      setPreview(data)
    } catch (e) {
      alert('Preview failed: ' + e.message)
    } finally {
      setPreviewLoading(false)
    }
  }

  const saveCurrentPreset = async () => {
    const name = window.prompt('Preset name:')
    if (!name) return
    const id = name.toLowerCase().replace(/\s+/g, '-')
    await savePreset({ id, name, description: 'Custom preset', settings })
    const d = await fetchPresets()
    setPresets(d.presets || [])
  }

  const totalSaved = queue.items.reduce((acc, i) => {
    if (i.result) return acc + Math.max(0, i.original_size - i.result.new_size)
    return acc
  }, 0)

  return (
    <div className="app">
      {showTip && health && !health.jpegtran_available && (
        <div className="tip-banner">
          <span>
            Install <code>jpegtran</code> for lossless JPEG optimization:{' '}
            <code>brew install jpeg</code>
          </span>
          <button
            onClick={() => {
              localStorage.setItem('tip-dismissed', '1')
              setShowTip(false)
            }}
          >
            ×
          </button>
        </div>
      )}

      <header className="header">
        <div className="header-left">
          <h1>Image Lab</h1>
          <span className="subtitle">Local batch processor</span>
        </div>
        <div className="header-actions">
          <div className="preset-dropdown">
            <button onClick={() => setPresetOpen(!presetOpen)}>Presets ▾</button>
            {presetOpen && (
              <div className="preset-menu panel">
                {presets.map((p) => (
                  <button key={p.id} className="preset-item" onClick={() => applyPreset(p)}>
                    <strong>{p.name}</strong>
                    <small>{p.description}</small>
                  </button>
                ))}
                <button className="preset-item" onClick={saveCurrentPreset}>
                  + Save current as preset
                </button>
              </div>
            )}
          </div>
          <button onClick={() => exportSettings(settings)}>Export settings</button>
          <button
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'
              input.accept = '.json'
              input.onchange = async (e) => {
                const f = e.target.files[0]
                if (f) setSettings(await importSettings(f))
              }
              input.click()
            }}
          >
            Import settings
          </button>
        </div>
      </header>

      <main className="layout">
        <aside className="sidebar panel">
          <div
            className={`drop-zone ${dragOver ? 'drag-over' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*,.heic,.heif"
              hidden
              onChange={(e) => handleFiles(e.target.files)}
            />
            <div className="drop-icon">⬇</div>
            <p>Drop files or folders</p>
            <small>JPEG · PNG · WEBP · GIF · HEIC</small>
          </div>

          <div className="queue-stats">
            <span>{queue.count} images</span>
            <span>{formatBytes(queue.total_size)}</span>
            {totalSaved > 0 && <span className="saved">−{formatBytes(totalSaved)} saved</span>}
          </div>

          <div className="queue-list">
            {queue.items.map((item) => (
              <div
                key={item.id}
                className={`queue-item ${selectedId === item.id ? 'selected' : ''}`}
                onClick={() => setSelectedId(item.id)}
              >
                {item.thumbnail ? (
                  <img src={`data:image/jpeg;base64,${item.thumbnail}`} alt="" className="thumb" />
                ) : (
                  <div className="thumb placeholder" />
                )}
                <div className="queue-meta">
                  <div className="filename" title={item.filename}>
                    {item.filename}
                  </div>
                  <div className="meta-row">
                    <span>{item.width}×{item.height}</span>
                    <span>{formatBytes(item.original_size)}</span>
                    <StatusBadge status={item.status} />
                  </div>
                  {item.result && (
                    <div className="result-row">
                      → {formatBytes(item.result.new_size)}
                      {item.result.savings_percent > 0 && (
                        <span className="savings"> (−{item.result.savings_percent}%)</span>
                      )}
                      {item.result.method_used && (
                        <span className="method"> {item.result.method_used}</span>
                      )}
                    </div>
                  )}
                  {item.error && <div className="error-text">{item.error}</div>}
                </div>
              </div>
            ))}
          </div>

          {progress && (
            <div className="progress-bar panel">
              {progress.running ? (
                <>
                  <div className="progress-text">
                    {progress.completed}/{progress.total} done · {progress.files_per_second} files/sec
                    · saved {progress.mb_saved} MB · ETA {progress.eta_seconds}s
                  </div>
                  {progress.current_file && (
                    <div className="current-file">Processing: {progress.current_file}</div>
                  )}
                </>
              ) : progress.completed > 0 ? (
                <div className="progress-text done">
                  Done — {progress.completed} files in {progress.elapsed_seconds}s
                </div>
              ) : null}
            </div>
          )}
        </aside>

        <section className="workspace">
          <div className="operations panel">
            <h3>Operations</h3>
            <div className="op-toggles">
              {[
                ['compress_enabled', 'Compress'],
                ['resize_enabled', 'Resize'],
                ['upscale_enabled', 'Upscale'],
                ['convert_enabled', 'Convert'],
                ['strip_exif', 'Strip EXIF'],
                ['trim_transparent', 'Trim transparent'],
                ['auto_rotate', 'Auto-rotate'],
                ['keep_icc', 'Keep ICC'],
              ].map(([key, label]) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={!!settings[key]}
                    onChange={(e) => updateSetting(key, e.target.checked)}
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>

          {settings.compress_enabled && (
            <div className="settings-section panel">
              <h3>Compress</h3>
              <div className="field-row">
                <div className="field">
                  <span>Mode</span>
                  <select
                    value={settings.compress_mode}
                    onChange={(e) => updateSetting('compress_mode', e.target.value)}
                  >
                    <option value="target_size">Target max size</option>
                    <option value="quality">Target quality</option>
                    <option value="lossless_first">Lossless first</option>
                  </select>
                </div>
                {settings.compress_mode === 'target_size' && (
                  <div className="field">
                    <span>Max size (MB)</span>
                    <input
                      type="number"
                      min="0.1"
                      step="0.1"
                      value={settings.target_size_mb}
                      onChange={(e) => updateSetting('target_size_mb', parseFloat(e.target.value))}
                    />
                  </div>
                )}
                {settings.compress_mode !== 'target_size' && (
                  <div className="field">
                    <span>Quality</span>
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={settings.quality}
                      onChange={(e) => updateSetting('quality', parseInt(e.target.value, 10))}
                    />
                  </div>
                )}
                <label>
                  <input
                    type="checkbox"
                    checked={settings.lossless_first}
                    onChange={(e) => updateSetting('lossless_first', e.target.checked)}
                  />
                  jpegtran first
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={settings.progressive}
                    onChange={(e) => updateSetting('progressive', e.target.checked)}
                  />
                  Progressive
                </label>
                <div className="field">
                  <span>Subsampling</span>
                  <select
                    value={settings.subsampling}
                    onChange={(e) => updateSetting('subsampling', parseInt(e.target.value, 10))}
                  >
                    <option value={0}>0 (4:4:4 best)</option>
                    <option value={1}>1</option>
                    <option value={2}>2 (default)</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {settings.resize_enabled && (
            <div className="settings-section panel">
              <h3>Resize</h3>
              <div className="field-row">
                <div className="field">
                  <span>Max width</span>
                  <input
                    type="number"
                    placeholder="—"
                    value={settings.max_width ?? ''}
                    onChange={(e) =>
                      updateSetting('max_width', e.target.value ? parseInt(e.target.value, 10) : null)
                    }
                  />
                </div>
                <div className="field">
                  <span>Max height</span>
                  <input
                    type="number"
                    placeholder="—"
                    value={settings.max_height ?? ''}
                    onChange={(e) =>
                      updateSetting('max_height', e.target.value ? parseInt(e.target.value, 10) : null)
                    }
                  />
                </div>
                <div className="field">
                  <span>Exact W×H</span>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <input
                      type="number"
                      placeholder="W"
                      value={settings.exact_width ?? ''}
                      onChange={(e) =>
                        updateSetting('exact_width', e.target.value ? parseInt(e.target.value, 10) : null)
                      }
                    />
                    <input
                      type="number"
                      placeholder="H"
                      value={settings.exact_height ?? ''}
                      onChange={(e) =>
                        updateSetting('exact_height', e.target.value ? parseInt(e.target.value, 10) : null)
                      }
                    />
                  </div>
                </div>
                <div className="field">
                  <span>Fit mode</span>
                  <select
                    value={settings.fit_mode}
                    onChange={(e) => updateSetting('fit_mode', e.target.value)}
                  >
                    <option value="contain">Contain</option>
                    <option value="cover">Cover</option>
                    <option value="crop_center">Crop center</option>
                  </select>
                </div>
                <div className="field">
                  <span>Scale %</span>
                  <input
                    type="number"
                    placeholder="—"
                    value={settings.scale_percent ?? ''}
                    onChange={(e) =>
                      updateSetting('scale_percent', e.target.value ? parseFloat(e.target.value) : null)
                    }
                  />
                </div>
              </div>
            </div>
          )}

          {settings.upscale_enabled && (
            <div className="settings-section panel">
              <h3>Upscale</h3>
              <p className="warning-text">
                Standard upscale uses Lanczos interpolation — it cannot create detail that is not in the
                original.
              </p>
              <div className="field-row">
                <div className="field">
                  <span>Scale factor</span>
                  <input
                    type="number"
                    min="1.1"
                    step="0.5"
                    value={settings.upscale_factor}
                    onChange={(e) => updateSetting('upscale_factor', parseFloat(e.target.value))}
                  />
                </div>
                <div className="field">
                  <span>Method</span>
                  <select
                    value={settings.upscale_method}
                    onChange={(e) => updateSetting('upscale_method', e.target.value)}
                  >
                    <option value="standard">Standard (Lanczos)</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {(settings.convert_enabled || settings.compress_enabled) && (
            <div className="settings-section panel">
              <h3>Output format</h3>
              <div className="field-row">
                <div className="field">
                  <span>Format</span>
                  <select
                    value={settings.output_format}
                    onChange={(e) => updateSetting('output_format', e.target.value)}
                  >
                    <option value="keep">Keep original</option>
                    <option value="JPEG">JPEG</option>
                    <option value="PNG">PNG</option>
                    <option value="WEBP">WEBP</option>
                    <option value="AVIF">AVIF</option>
                  </select>
                </div>
                {settings.convert_enabled && settings.output_format === 'JPEG' && (
                  <div className="field" title="Fill color for transparent areas when converting PNG/WEBP/GIF to JPEG">
                    <span>Transparency fill</span>
                    <input
                      type="text"
                      value={settings.bg_color}
                      onChange={(e) => updateSetting('bg_color', e.target.value)}
                      placeholder="#ffffff"
                    />
                  </div>
                )}
                <div className="field">
                  <span>Output folder</span>
                  <input
                    type="text"
                    placeholder="processed/ (default)"
                    value={settings.output_dir}
                    onChange={(e) => updateSetting('output_dir', e.target.value)}
                  />
                </div>
                <div className="field">
                  <span>Suffix</span>
                  <input
                    type="text"
                    value={settings.naming_suffix}
                    onChange={(e) => updateSetting('naming_suffix', e.target.value)}
                  />
                </div>
                <label>
                  <input
                    type="checkbox"
                    checked={settings.overwrite}
                    onChange={(e) => updateSetting('overwrite', e.target.checked)}
                  />
                  Overwrite
                </label>
              </div>
            </div>
          )}

          <div className="preview-section panel">
            <div className="preview-header">
              <h3>Preview</h3>
              <button onClick={runPreview} disabled={!queue.count || previewLoading}>
                {previewLoading ? 'Processing…' : 'Preview selected'}
              </button>
            </div>
            {preview && (
              <div className="preview-grid">
                <div className="preview-pane">
                  <div className="preview-label">Before · {formatBytes(preview.original_size)} · {preview.original_dimensions?.join('×')}</div>
                  {preview.before && (
                    <img src={`data:image/jpeg;base64,${preview.before}`} alt="Before" />
                  )}
                </div>
                <div className="preview-pane">
                  <div className="preview-label">
                    After · {formatBytes(preview.new_size)} · {preview.new_dimensions?.join('×')}
                    {preview.quality_used != null && ` · q${preview.quality_used}`}
                    {preview.method_used && ` · ${preview.method_used}`}
                    {preview.processing_time_ms != null && ` · ${preview.processing_time_ms.toFixed(0)}ms`}
                  </div>
                  {preview.after && (
                    <img
                      src={`data:image/${preview.after_format || 'jpeg'};base64,${preview.after}`}
                      alt="After"
                    />
                  )}
                </div>
              </div>
            )}
            {!preview && <p className="muted">Select a file and click Preview to compare before/after.</p>}
          </div>

          <div className="actions-bar">
            {progress?.running ? (
              <button className="danger" onClick={cancelProcess}>
                Cancel
              </button>
            ) : (
              <button className="primary" onClick={runProcess} disabled={!queue.count}>
                ▶ Process All ({queue.count})
              </button>
            )}
            <button
              onClick={async () => {
                await clearQueue()
                await refreshQueue()
                setPreview(null)
              }}
              disabled={progress?.running || !queue.count}
            >
              Clear
            </button>
            <a href="/api/export/zip" className="btn-link" onClick={(e) => !queue.count && e.preventDefault()}>
              Download ZIP
            </a>
            <a href="/api/report?format=csv" className="btn-link">
              Export CSV
            </a>
          </div>

          {health && (
            <div className="health-footer">
              Pillow {health.pillow_version} · jpegtran {health.jpegtran_available ? '✓' : '✗'} · HEIC{' '}
              {health.heif_available ? '✓' : '✗'} · {health.cpu_count} threads
            </div>
          )}
        </section>
      </main>

      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
