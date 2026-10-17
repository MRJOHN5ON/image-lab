import { useEffect, useId, useState } from 'react'
import Icon from './Icon'

export function Switch({ checked, onChange, label, hint, disabled, danger }) {
  const id = useId()
  return (
    <label className={`switch-row ${disabled ? 'disabled' : ''}`} htmlFor={id}>
      <span className="switch-text">
        <span className="switch-label">{label}</span>
        {hint && <span className="hint">{hint}</span>}
      </span>
      <span className={`switch ${checked ? 'on' : ''} ${danger ? 'danger' : ''}`}>
        <input
          id={id}
          type="checkbox"
          role="switch"
          checked={!!checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="switch-thumb" />
      </span>
    </label>
  )
}

export function Segmented({ value, options, onChange, size = 'md', ariaLabel }) {
  return (
    <div className={`segmented ${size}`} role="radiogroup" aria-label={ariaLabel}>
      {options.map((opt) => (
        <button
          key={String(opt.value)}
          type="button"
          role="radio"
          aria-checked={value === opt.value}
          className={value === opt.value ? 'active' : ''}
          disabled={opt.disabled}
          title={opt.title}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export function Field({ label, hint, error, children, htmlFor, aside }) {
  return (
    <div className={`field ${error ? 'has-error' : ''}`}>
      {(label || aside) && (
        <div className="field-head">
          {label && (
            <label className="field-label" htmlFor={htmlFor}>
              {label}
            </label>
          )}
          {aside}
        </div>
      )}
      {children}
      {error ? <div className="field-error">{error}</div> : hint ? <div className="hint">{hint}</div> : null}
    </div>
  )
}

/** Number input that lets the user type freely and only commits valid values. */
export function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 1,
  integer = true,
  allowEmpty = false,
  placeholder,
  suffix,
  id,
  invalid,
  width,
}) {
  const [text, setText] = useState(value ?? '')
  useEffect(() => {
    setText(value ?? '')
  }, [value])

  const commit = (raw) => {
    if (raw === '' || raw == null) {
      if (allowEmpty) onChange(null)
      return
    }
    const n = Number(raw)
    if (!Number.isFinite(n)) return
    onChange(integer ? Math.round(n) : n)
  }

  const outOfRange = text !== '' && ((min != null && Number(text) < min) || (max != null && Number(text) > max))

  return (
    <div className={`input-wrap ${invalid || outOfRange ? 'invalid' : ''}`} style={width ? { width } : undefined}>
      <input
        id={id}
        className="input num"
        type="number"
        inputMode={integer ? 'numeric' : 'decimal'}
        value={text}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        onChange={(e) => {
          setText(e.target.value)
          commit(e.target.value)
        }}
        onBlur={() => setText(value ?? '')}
      />
      {suffix && <span className="input-suffix">{suffix}</span>}
    </div>
  )
}

export function TextInput({ value, onChange, placeholder, id, invalid, mono, ...rest }) {
  return (
    <input
      id={id}
      className={`input ${mono ? 'mono' : ''} ${invalid ? 'invalid' : ''}`}
      type="text"
      value={value ?? ''}
      placeholder={placeholder}
      spellCheck={false}
      autoComplete="off"
      onChange={(e) => onChange(e.target.value)}
      {...rest}
    />
  )
}

export function Select({ value, onChange, options, id }) {
  return (
    <div className="select-wrap">
      <select id={id} className="input select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value} disabled={opt.disabled}>
            {opt.label}
          </option>
        ))}
      </select>
      <Icon name="chevronDown" size={14} className="select-caret" />
    </div>
  )
}

export function ColorInput({ value, onChange, id }) {
  const valid = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.test(value || '')
  const hex = valid ? (value.startsWith('#') ? value : `#${value}`) : '#ffffff'
  const full = hex.length === 4 ? `#${[...hex.slice(1)].map((c) => c + c).join('')}` : hex
  return (
    <div className={`color-input ${valid ? '' : 'invalid'}`}>
      <input type="color" value={full} onChange={(e) => onChange(e.target.value)} aria-label="Pick colour" />
      <input
        id={id}
        className="input mono"
        type="text"
        value={value}
        maxLength={7}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  )
}

export function RangeInput({ value, onChange, min = 1, max = 100, id, marks }) {
  const pct = ((value - min) / (max - min)) * 100
  return (
    <div className="range-row">
      <input
        id={id}
        className="range"
        type="range"
        min={min}
        max={max}
        value={value}
        style={{ '--pct': `${pct}%` }}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <NumberInput value={value} onChange={(v) => v != null && onChange(Math.min(max, Math.max(min, v)))} min={min} max={max} width={64} />
      {marks && <div className="range-marks">{marks}</div>}
    </div>
  )
}

export function Section({ title, icon, enabled, onToggle, children, summary, open, onOpenChange, badge }) {
  const toggleable = typeof onToggle === 'function'
  const expanded = open && (!toggleable || enabled)
  return (
    <section className={`section ${expanded ? 'open' : ''} ${toggleable && !enabled ? 'off' : ''}`}>
      <header className="section-head">
        <button type="button" className="section-title" onClick={() => onOpenChange(!open)} aria-expanded={expanded}>
          <Icon name="chevronRight" size={14} className="section-caret" />
          {icon && <Icon name={icon} size={15} />}
          <span>{title}</span>
          {badge}
          {!expanded && summary && <span className="section-summary">{summary}</span>}
        </button>
        {toggleable && (
          <span className={`switch small ${enabled ? 'on' : ''}`}>
            <input
              type="checkbox"
              role="switch"
              aria-label={`Enable ${title}`}
              checked={!!enabled}
              onChange={(e) => {
                onToggle(e.target.checked)
                if (e.target.checked) onOpenChange(true)
              }}
            />
            <span className="switch-thumb" />
          </span>
        )}
      </header>
      {expanded && <div className="section-body">{children}</div>}
    </section>
  )
}

export function Button({ variant = 'default', size = 'md', icon, children, className = '', kbd, ...rest }) {
  return (
    <button type="button" className={`btn ${variant} ${size} ${className}`} {...rest}>
      {icon && <Icon name={icon} size={size === 'sm' ? 14 : 16} />}
      {children && <span>{children}</span>}
      {kbd && <kbd>{kbd}</kbd>}
    </button>
  )
}

export function IconButton({ icon, label, size = 'md', variant = 'ghost', ...rest }) {
  return (
    <button type="button" className={`icon-btn ${variant} ${size}`} aria-label={label} title={label} {...rest}>
      <Icon name={icon} size={size === 'sm' ? 14 : 16} />
    </button>
  )
}

export function Spinner({ size = 16 }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-label="Loading" />
}
