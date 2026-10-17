import { formatBytes, formatDuration, plural } from '../utils/format'
import { Button } from './controls'
import Icon from './Icon'

function Progress({ status }) {
  const pct = status.total ? (status.completed / status.total) * 100 : 0
  const current = status.current_files?.[0]
  return (
    <div className="progress">
      <div className="row between">
        <span className="progress-main">
          {status.cancelling ? 'Cancelling…' : `Processing ${status.completed.toLocaleString()} of ${status.total.toLocaleString()}`}
        </span>
        <span className="muted mono">
          {status.files_per_second > 0 && `${status.files_per_second} img/s · `}
          {status.eta_seconds > 0 ? `${formatDuration(status.eta_seconds)} left` : 'estimating…'}
          {status.bytes_saved > 0 && ` · saved ${formatBytes(status.bytes_saved)}`}
        </span>
      </div>
      <div className="bar large">
        <div style={{ width: `${pct}%` }} />
      </div>
      <div className="progress-current muted">
        {current ? `${current}${status.current_files.length > 1 ? ` +${status.current_files.length - 1} more` : ''}` : ' '}
      </div>
    </div>
  )
}

function Summary({ status, onRetryFailed, onDismiss }) {
  const parts = []
  if (status.done) parts.push(plural(status.done, 'image') + ' processed')
  if (status.skipped) parts.push(`${status.skipped} skipped`)
  if (status.cancelled) parts.push(`${status.cancelled} cancelled`)
  const ok = !status.failed && !status.cancelled
  return (
    <div className={`summary ${ok ? 'ok' : status.failed ? 'warn' : ''}`}>
      <Icon name={ok ? 'check' : 'alert'} size={16} />
      <span>
        {parts.join(' · ') || 'Nothing processed'}
        {status.bytes_saved > 0 && (
          <>
            {' '}
            · saved <strong>{formatBytes(status.bytes_saved)}</strong> ({status.savings_percent}%)
          </>
        )}{' '}
        <span className="muted">in {formatDuration(status.elapsed_seconds)}</span>
      </span>
      {status.failed > 0 && (
        <button type="button" className="link danger" onClick={onRetryFailed}>
          {status.failed} failed · Retry
        </button>
      )}
      <button type="button" className="link muted" onClick={onDismiss} aria-label="Dismiss summary">
        <Icon name="x" size={13} />
      </button>
    </div>
  )
}

export default function ActionBar({
  status,
  showSummary,
  onDismissSummary,
  count,
  doneCount,
  onProcess,
  onCancel,
  onZip,
  onCsv,
  onRevealOutput,
  onRetryFailed,
  revealLabel,
}) {
  const running = status?.running
  return (
    <footer className="actionbar">
      <div className="actionbar-left">
        {running ? (
          <Progress status={status} />
        ) : showSummary && status?.total ? (
          <Summary status={status} onRetryFailed={onRetryFailed} onDismiss={onDismissSummary} />
        ) : (
          <span className="muted">{count ? `Ready · ${plural(count, 'image')}` : 'Add images to begin'}</span>
        )}
      </div>
      <div className="actionbar-right">
        <Button variant="ghost" icon="table" onClick={onCsv} disabled={!status?.total} title="Export a CSV report of the last batch">
          Report
        </Button>
        <Button variant="ghost" icon="zip" onClick={onZip} disabled={!doneCount} title="Save all processed images as a ZIP">
          ZIP
        </Button>
        <Button icon="reveal" onClick={onRevealOutput} disabled={!doneCount}>
          {revealLabel}
        </Button>
        {running ? (
          <Button variant="danger" icon="stop" onClick={onCancel} disabled={status.cancelling} kbd="esc">
            {status.cancelling ? 'Cancelling' : 'Cancel'}
          </Button>
        ) : (
          <Button variant="primary" icon="play" onClick={onProcess} disabled={!count} kbd="⌘↩" className="process-btn">
            {count ? `Process ${count.toLocaleString()}` : 'Process'}
          </Button>
        )}
      </div>
    </footer>
  )
}
