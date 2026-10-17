import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Image Lab UI crashed', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="engine-down">
        <div className="engine-card">
          <h2>Something went wrong in the interface</h2>
          <p className="muted">Your queue and settings are safe — the engine keeps running.</p>
          <pre className="mono selectable" style={{ maxWidth: 480, whiteSpace: 'pre-wrap', fontSize: 11, color: 'var(--text-3)' }}>
            {String(this.state.error?.message || this.state.error)}
          </pre>
          <button type="button" className="btn primary" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    )
  }
}
