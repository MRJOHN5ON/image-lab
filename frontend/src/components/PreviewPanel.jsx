import { useEffect, useState } from 'react'
import { formatBytes, formatDims, savingsLabel, shortenPath } from '../utils/format'
import CompareView from './CompareView'
import { Button, Segmented, Spinner } from './controls'
import Icon from './Icon'

// Mirrors MAX_DISPLAY_PIXELS / MAX_DISPLAY_SIDE in backend/main.py.
function displayDims(w, h) {
  if (!w || !h) return [1, 1]
  const factor = Math.min(1, Math.sqrt(16_000_000 / (w * h)), 6000 / Math.max(w, h))
  return [Math.max(1, Math.floor(w * factor)), Math.max(1, Math.floor(h * factor))]
}

function EmptyHero({ onAddFiles, onAddFolder, health }) {
  return (
    <div className="hero">
      <div className="hero-card">
        <div className="hero-icon">
          <Icon name="upload" size={26} />
        </div>
        <h2>Drop images to get started</h2>
        <p>JPEG, PNG, WebP, AVIF, HEIC, TIFF and GIF. Folders work too.</p>
        <div className="row gap-s center">
          <Button variant="primary" icon="plus" onClick={onAddFiles} kbd="⌘O">
            Add images
          </Button>
          <Button icon="folder" onClick={onAddFolder} kbd="⇧⌘O">
            Add folder
          </Button>
        </div>
        <div className="hero-foot">
          <Icon name="lock" size={13} />
          <span>Everything runs on this {health?.platform === 'darwin' ? 'Mac' : 'computer'}. Nothing is uploaded.</span>
        </div>
      </div>
      <div className="hero-tips">
        <span><kbd>⌘V</kbd> paste</span>
        <span><kbd>↑</kbd><kbd>↓</kbd> select</span>
        <span><kbd>Space</kbd> hold for original</span>
        <span><kbd>⌘↩</kbd> process</span>
      </div>
    </div>
  )
}

function Stat({ label, value, sub, tone }) {
  return (
    <div className={`stat ${tone || ''}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export default function PreviewPanel({
  item,
  hasItems,
  preview,
  settings,
  holdOriginal,
  onRetry,
  onAddFiles,
  onAddFolder,
  onReveal,
  onFocusField,
  health,
}) {
  const [view, setView] = useState('split')
  const [zoom, setZoom] = useState('fit')
  const [imagesLoading, setImagesLoading] = useState(false)

  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.target.closest?.('input, textarea, select, [role=dialog]')) return
      const zooms = { 0: 'fit', 1: 1, 2: 2 }
      if (e.key in zooms) setZoom(zooms[e.key])
      else if (e.key === 's') setView('split')
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!hasItems) {
    return (
      <main className="stage">
        <EmptyHero onAddFiles={onAddFiles} onAddFolder={onAddFolder} health={health} />
      </main>
    )
  }

  if (!item) {
    return (
      <main className="stage">
        <div className="stage-empty">Select an image to preview it.</div>
      </main>
    )
  }

  const data = preview.data?.item_id === item.id ? preview.data : null
  const busy = preview.status === 'loading' || imagesLoading
  const beforeFit = settings.resize_enabled && settings.resize_mode === 'exact' && settings.fit_mode === 'cover' ? 'cover' : 'contain'
  const dims = data?.display_dimensions || displayDims(item.width, item.height)
  const displayScale = data?.display_scale ?? 1
  const savings = data?.savings_percent
  const output = item.result?.output_path

  return (
    <main className="stage">
      <div className="stage-toolbar">
        <div className="stage-title">
          <span className="stage-name" title={item.path}>
            {item.filename}
          </span>
          <span className="muted">
            {item.format} · {formatDims([item.width, item.height])} · {formatBytes(item.original_size)}
          </span>
        </div>
        <div className="row gap-s">
          {busy && (
            <span className="busy-chip">
              <Spinner size={12} /> <span>Rendering</span>
            </span>
          )}
          {!busy && displayScale < 0.999 && (
            <span
              className="busy-chip"
              title={`The result is ${formatDims(data.new_dimensions)}, too large to draw here at full size. The preview is scaled down; the saved file is not.`}
            >
              <Icon name="info" size={13} /> <span>Shown at {Math.max(1, Math.round(displayScale * 100))}%</span>
            </span>
          )}
          <Segmented
            size="sm"
            ariaLabel="Compare view"
            value={holdOriginal ? 'before' : view}
            onChange={setView}
            options={[
              { value: 'split', label: 'Split' },
              { value: 'before', label: 'Original' },
              { value: 'after', label: 'Result' },
            ]}
          />
          <Segmented
            size="sm"
            ariaLabel="Zoom"
            value={zoom}
            onChange={setZoom}
            options={[
              { value: 'fit', label: 'Fit', title: 'Fit to window (0)' },
              { value: 1, label: '100%', title: 'Actual pixels (1)' },
              { value: 2, label: '200%', title: 'Inspect artifacts (2)' },
            ]}
          />
        </div>
      </div>

      <div className="stage-body">
        {preview.status === 'error' && preview.itemId === item.id ? (
          <div className="stage-error">
            <Icon name="alert" size={22} />
            <h3>{preview.error?.field ? 'Check your settings' : "Couldn't preview this image"}</h3>
            <p>{preview.error?.message}</p>
            <div className="row gap-s center">
              {preview.error?.field && (
                <Button variant="primary" onClick={() => onFocusField(preview.error.field)}>
                  Show setting
                </Button>
              )}
              <Button icon="refresh" onClick={onRetry}>
                Try again
              </Button>
            </div>
          </div>
        ) : (
          <CompareView
            key={item.id}
            beforeUrl={`/api/items/${item.id}/source`}
            afterUrl={data?.after_url}
            dims={dims}
            beforeFit={beforeFit}
            view={holdOriginal ? 'before' : view}
            zoom={zoom}
            onLoadingChange={setImagesLoading}
          />
        )}
      </div>

      <div className="stage-stats">
        <Stat label="Original" value={formatBytes(item.original_size)} sub={`${formatDims([item.width, item.height])} · ${item.format}`} />
        <Icon name="chevronRight" size={16} className="stat-arrow" />
        <Stat
          label="Result"
          value={data ? formatBytes(data.new_size) : '—'}
          sub={
            data
              ? [formatDims(data.new_dimensions), data.format, data.quality_used != null && `q${data.quality_used}`, data.method_used]
                  .filter(Boolean)
                  .join(' · ')
              : 'Rendering preview…'
          }
        />
        <Stat
          label="Change"
          value={data ? savingsLabel(savings) : '—'}
          sub={data ? `${formatBytes(Math.abs(item.original_size - data.new_size))} ${savings >= 0 ? 'smaller' : 'larger'}` : ''}
          tone={data ? (savings > 0 ? 'good' : savings < 0 ? 'bad' : '') : ''}
        />
        <div className="stat-spacer" />
        {data?.warnings?.length > 0 && (
          <div className="stat-warnings">
            {data.warnings.map((w) => (
              <div key={w}>
                <Icon name="alert" size={13} /> {w}
              </div>
            ))}
          </div>
        )}
        {output && (
          <button type="button" className="saved-chip" onClick={() => onReveal(output)} title={output}>
            <Icon name="check" size={13} />
            <span>Saved · {shortenPath(output, 34)}</span>
            <Icon name="reveal" size={13} />
          </button>
        )}
        {data && (
          <span className="stat-time" title={data.steps?.join('\n')}>
            {Math.round(data.processing_time_ms)} ms
          </span>
        )}
      </div>
    </main>
  )
}
