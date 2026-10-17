import { memo, useEffect, useRef, useState } from 'react'
import { urls } from '../api'
import { formatBytes, plural, savingsLabel } from '../utils/format'
import { IconButton, Spinner } from './controls'
import Icon from './Icon'
import Menu from './Menu'

const FILTERS = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'pending', label: 'To do', match: (i) => ['pending', 'queued', 'processing', 'cancelled'].includes(i.status) },
  { id: 'done', label: 'Done', match: (i) => i.status === 'done' || i.status === 'skipped' },
  { id: 'failed', label: 'Failed', match: (i) => i.status === 'failed' },
]

export function filterItems(items, filter) {
  const f = FILTERS.find((x) => x.id === filter) || FILTERS[0]
  return items.filter(f.match)
}

function StatusIcon({ status }) {
  switch (status) {
    case 'processing':
      return <Spinner size={14} />
    case 'queued':
      return <span className="status-dot queued" title="Queued" />
    case 'done':
      return <Icon name="check" size={14} className="status-ok" title="Done" />
    case 'skipped':
      return <span className="status-tag warn">Skipped</span>
    case 'failed':
      return <Icon name="alert" size={14} className="status-fail" title="Failed" />
    case 'cancelled':
      return <span className="status-tag">Cancelled</span>
    default:
      return null
  }
}

const Thumb = memo(function Thumb({ id }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <div className="q-thumb placeholder">
        <Icon name="image" size={16} />
      </div>
    )
  }
  return (
    <div className="q-thumb">
      <img src={urls.thumbnail(id)} alt="" loading="lazy" decoding="async" draggable={false} onError={() => setFailed(true)} />
    </div>
  )
})

const QueueRow = memo(function QueueRow({ item, selected, onSelect, onRemove, onReveal, onDownload }) {
  const ref = useRef(null)
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: 'nearest' })
  }, [selected])
  const r = item.result
  const warnings = r?.warnings?.length ? r.warnings.join('\n') : null
  const active = item.status === 'queued' || item.status === 'processing'
  const formatChanged = r && r.format && r.format !== item.format

  return (
    <div
      ref={ref}
      role="option"
      aria-selected={selected}
      tabIndex={-1}
      className={`q-row status-${item.status} ${selected ? 'selected' : ''}`}
      onClick={() => onSelect(item.id)}
      onDoubleClick={() => r?.output_path && onReveal(r.output_path)}
    >
      <Thumb id={item.id} />
      <div className="q-main">
        <div className="q-name" title={item.path}>
          {item.filename}
        </div>
        {item.error ? (
          <div className="q-error" title={item.error}>
            {item.error}
          </div>
        ) : r ? (
          <div className="q-meta">
            <span>{formatBytes(item.original_size)}</span>
            <Icon name="chevronRight" size={11} className="q-arrow" />
            <span className="q-new">{formatBytes(r.new_size)}</span>
            {item.status === 'done' && (
              <span className={`pill ${r.savings_percent > 0 ? 'good' : r.savings_percent < 0 ? 'bad' : ''}`}>
                {savingsLabel(r.savings_percent)}
              </span>
            )}
            {formatChanged && <span className="q-fmt">{r.format}</span>}
            {warnings && (
              <span className="q-warn" title={warnings}>
                <Icon name="alert" size={12} />
              </span>
            )}
          </div>
        ) : (
          <div className="q-meta">
            <span className="q-fmt">{item.format}</span>
            <span>{item.width ? `${item.width}×${item.height}` : '—'}</span>
            <span>{formatBytes(item.original_size)}</span>
          </div>
        )}
      </div>
      <div className="q-side">
        <StatusIcon status={item.status} />
        <div className="q-actions" onClick={(e) => e.stopPropagation()}>
          {r?.output_path && (
            <>
              <IconButton size="sm" icon="reveal" label="Show in Finder" onClick={() => onReveal(r.output_path)} />
              <IconButton size="sm" icon="download" label="Save a copy" onClick={() => onDownload(item)} />
            </>
          )}
          <IconButton size="sm" icon="x" label="Remove from queue" disabled={active} onClick={() => onRemove(item.id)} />
        </div>
      </div>
    </div>
  )
})

export default function QueuePanel({
  items,
  selectedId,
  onSelect,
  filter,
  setFilter,
  onRemove,
  onReveal,
  onDownload,
  onAddFiles,
  onAddFolder,
  onClear,
  onRetryFailed,
  running,
  upload,
}) {
  const visible = filterItems(items, filter)
  const counts = Object.fromEntries(FILTERS.map((f) => [f.id, items.filter(f.match).length]))
  const totalSize = items.reduce((sum, i) => sum + i.original_size, 0)

  return (
    <aside className="queue" aria-label="Queue">
      <div className="panel-head">
        <div>
          <div className="panel-title">Queue</div>
          <div className="panel-sub">
            {items.length ? `${plural(items.length, 'image')} · ${formatBytes(totalSize)}` : 'No images yet'}
          </div>
        </div>
        <div className="row gap-xs">
          <IconButton icon="plus" label="Add images (⌘O)" onClick={onAddFiles} />
          <IconButton icon="folder" label="Add folder (⇧⌘O)" onClick={onAddFolder} />
          <Menu
            align="right"
            width={220}
            trigger={({ toggle }) => <IconButton icon="more" label="Queue options" onClick={toggle} />}
            items={[
              { label: 'Retry failed', icon: 'refresh', disabled: running || !counts.failed, onClick: onRetryFailed },
              { label: 'Remove finished', icon: 'check', disabled: !counts.done, onClick: () => onClear('finished') },
              { divider: true },
              { label: 'Clear queue', icon: 'trash', danger: true, disabled: running || !items.length, onClick: () => onClear('all') },
            ]}
          />
        </div>
      </div>

      {upload && (
        <div className="upload-bar">
          <div className="row between">
            <span>
              Adding {plural(upload.count, 'file')}… {Math.round((upload.loaded / Math.max(upload.total, 1)) * 100)}%
            </span>
            <span className="muted">{formatBytes(upload.total)}</span>
          </div>
          <div className="bar">
            <div style={{ width: `${(upload.loaded / Math.max(upload.total, 1)) * 100}%` }} />
          </div>
        </div>
      )}

      {items.length > 0 && (
        <div className="filters" role="tablist">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={filter === f.id}
              className={`filter ${filter === f.id ? 'active' : ''} ${f.id === 'failed' && counts.failed ? 'has-failed' : ''}`}
              onClick={() => setFilter(f.id)}
              disabled={f.id !== 'all' && !counts[f.id]}
            >
              {f.label}
              <span className="count">{counts[f.id]}</span>
            </button>
          ))}
        </div>
      )}

      <div className="q-list" role="listbox" aria-label="Images">
        {visible.map((item) => (
          <QueueRow
            key={item.id}
            item={item}
            selected={item.id === selectedId}
            onSelect={onSelect}
            onRemove={onRemove}
            onReveal={onReveal}
            onDownload={onDownload}
          />
        ))}
        {!items.length && (
          <div className="q-empty">
            <Icon name="image" size={22} />
            <p>Drop images or folders anywhere in the window.</p>
            <div className="row gap-s center">
              <button type="button" className="btn default sm" onClick={onAddFiles}>
                <Icon name="plus" size={14} /> <span>Images</span>
              </button>
              <button type="button" className="btn default sm" onClick={onAddFolder}>
                <Icon name="folder" size={14} /> <span>Folder</span>
              </button>
            </div>
          </div>
        )}
        {items.length > 0 && !visible.length && <div className="q-empty small">Nothing here.</div>}
      </div>
    </aside>
  )
}
