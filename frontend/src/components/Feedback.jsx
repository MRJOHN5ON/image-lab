import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon'

const FeedbackContext = createContext(null)

export function useFeedback() {
  return useContext(FeedbackContext)
}

let toastSeq = 0

export function FeedbackProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const [dialog, setDialog] = useState(null)
  const timers = useRef(new Map())

  const dismiss = useCallback((id) => {
    setToasts((list) => list.filter((t) => t.id !== id))
    clearTimeout(timers.current.get(id))
    timers.current.delete(id)
  }, [])

  const toast = useCallback(
    (message, { type = 'info', detail, action, duration } = {}) => {
      const id = ++toastSeq
      setToasts((list) => [...list.slice(-3), { id, message, type, detail, action }])
      const ms = duration ?? (type === 'error' ? 9000 : 5000)
      if (ms > 0) timers.current.set(id, setTimeout(() => dismiss(id), ms))
      return id
    },
    [dismiss],
  )

  const confirm = useCallback(
    (options) =>
      new Promise((resolve) => {
        setDialog({ kind: 'confirm', ...options, resolve })
      }),
    [],
  )

  const prompt = useCallback(
    (options) =>
      new Promise((resolve) => {
        setDialog({ kind: 'prompt', ...options, resolve })
      }),
    [],
  )

  const value = useMemo(() => ({ toast, dismiss, confirm, prompt }), [toast, dismiss, confirm, prompt])

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.type}`} role={t.type === 'error' ? 'alert' : 'status'}>
            <Icon name={t.type === 'error' ? 'alert' : t.type === 'success' ? 'check' : 'info'} size={16} className="toast-icon" />
            <div className="toast-body">
              <div className="toast-message">{t.message}</div>
              {t.detail && <div className="toast-detail">{t.detail}</div>}
            </div>
            {t.action && (
              <button
                type="button"
                className="toast-action"
                onClick={() => {
                  t.action.onClick()
                  dismiss(t.id)
                }}
              >
                {t.action.label}
              </button>
            )}
            <button type="button" className="toast-close" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
              <Icon name="x" size={14} />
            </button>
          </div>
        ))}
      </div>
      {dialog && (
        <Dialog
          {...dialog}
          onClose={(result) => {
            dialog.resolve(result)
            setDialog(null)
          }}
        />
      )}
    </FeedbackContext.Provider>
  )
}

function Dialog({ kind, title, message, confirmLabel = 'OK', cancelLabel = 'Cancel', danger, fields = [], onClose }) {
  const [values, setValues] = useState(() => Object.fromEntries(fields.map((f) => [f.name, f.value ?? ''])))
  const firstInput = useRef(null)
  const confirmRef = useRef(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    ;(firstInput.current || confirmRef.current)?.focus()
    const onKey = (e) => e.key === 'Escape' && closeRef.current(kind === 'prompt' ? null : false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [kind])

  const missing = fields.some((f) => f.required && !String(values[f.name] || '').trim())
  const submit = (e) => {
    e.preventDefault()
    if (missing) return
    onClose(kind === 'prompt' ? values : true)
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose(kind === 'prompt' ? null : false)}>
      <form className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" onSubmit={submit}>
        <div className="modal-head">
          {danger && <Icon name="alert" size={18} className="modal-danger-icon" />}
          <h2 id="modal-title">{title}</h2>
        </div>
        {message && <div className="modal-message">{message}</div>}
        {fields.map((f, i) => (
          <div key={f.name} className="field">
            <label className="field-label" htmlFor={`dlg-${f.name}`}>
              {f.label}
            </label>
            <input
              id={`dlg-${f.name}`}
              ref={i === 0 ? firstInput : undefined}
              className="input"
              value={values[f.name]}
              maxLength={f.maxLength}
              placeholder={f.placeholder}
              onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
            />
          </div>
        ))}
        <div className="modal-actions">
          {cancelLabel !== null && (
            <button type="button" className="btn default" onClick={() => onClose(kind === 'prompt' ? null : false)}>
              {cancelLabel}
            </button>
          )}
          <button ref={confirmRef} type="submit" className={`btn ${danger ? 'danger' : 'primary'}`} disabled={missing}>
            {confirmLabel}
          </button>
        </div>
      </form>
    </div>
  )
}
