import { useEffect, useRef, useState } from 'react'
import Icon from './Icon'

/** Popover menu. `items`: {label, icon, onClick, danger, disabled, hint, divider, header, checked, aside}. */
export default function Menu({ trigger, items, align = 'left', width = 240, className = '' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false)
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className={`menu-anchor ${className}`} ref={ref}>
      {trigger({ open, toggle: () => setOpen((v) => !v) })}
      {open && (
        <div className={`menu ${align}`} style={{ width }} role="menu">
          {items.filter(Boolean).map((item, index) => {
            if (item.divider) return <div key={`d${index}`} className="menu-divider" />
            if (item.header) {
              return (
                <div key={`h${index}`} className="menu-header">
                  {item.header}
                </div>
              )
            }
            return (
              <div key={item.key || item.label} className="menu-row">
                <button
                  type="button"
                  role="menuitem"
                  className={`menu-item ${item.danger ? 'danger' : ''} ${item.checked ? 'checked' : ''}`}
                  disabled={item.disabled}
                  onClick={() => {
                    setOpen(false)
                    item.onClick?.()
                  }}
                >
                  <span className="menu-icon">
                    {item.checked ? <Icon name="check" size={14} /> : item.icon ? <Icon name={item.icon} size={14} /> : null}
                  </span>
                  <span className="menu-text">
                    <span>{item.label}</span>
                    {item.hint && <small>{item.hint}</small>}
                  </span>
                  {item.kbd && <kbd>{item.kbd}</kbd>}
                </button>
                {item.aside}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
