import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

function usePreloaded(url) {
  const [state, setState] = useState({ shown: null, loading: false, failed: false })
  useEffect(() => {
    if (!url) {
      setState({ shown: null, loading: false, failed: false })
      return undefined
    }
    let cancelled = false
    setState((s) => ({ ...s, loading: true }))
    const img = new Image()
    img.src = url
    img
      .decode()
      .then(() => !cancelled && setState({ shown: url, loading: false, failed: false }))
      .catch(() => !cancelled && setState({ shown: null, loading: false, failed: true }))
    return () => {
      cancelled = true
    }
  }, [url])
  return state
}

function useElementSize(ref) {
  const [size, setSize] = useState({ width: 0, height: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const observer = new ResizeObserver(([entry]) => {
      const width = Math.floor(entry.contentRect.width)
      const height = Math.floor(entry.contentRect.height)
      setSize((s) => (s.width === width && s.height === height ? s : { width, height }))
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return size
}

/**
 * view: 'split' | 'before' | 'after'; zoom: 'fit' | 1 | 2 (1 = one image pixel per device pixel).
 */
export default function CompareView({ beforeUrl, afterUrl, dims, beforeFit = 'contain', view, zoom, onLoadingChange }) {
  const viewportRef = useRef(null)
  const boxRef = useRef(null)
  const viewport = useElementSize(viewportRef)
  const before = usePreloaded(beforeUrl)
  const after = usePreloaded(afterUrl)
  const [pos, setPos] = useState(50)
  const drag = useRef(null)

  useEffect(() => {
    onLoadingChange?.(before.loading || after.loading)
  }, [before.loading, after.loading, onLoadingChange])

  const [w, h] = dims?.[0] ? dims : [1, 1]
  const dpr = window.devicePixelRatio || 1
  const pad = 48
  const vw = Math.floor(viewport.width)
  const vh = Math.floor(viewport.height)
  const fitScale = Math.min((vw - pad) / w, (vh - pad) / h, 1)
  const scale = zoom === 'fit' ? Math.max(fitScale, 0.01) : zoom / dpr
  const boxW = Math.max(1, Math.floor(w * scale))
  const boxH = Math.max(1, Math.floor(h * scale))
  // Fit mode never scrolls. Letting it would let a scrollbar resize the viewport, which
  // re-fits the image, which removes the scrollbar — a layout loop that freezes the page.
  const zoomed = zoom !== 'fit' && (boxW + pad > vw || boxH + pad > vh)

  const shownPos = view === 'before' ? 100 : view === 'after' ? 0 : pos

  const setFromClientX = useCallback((clientX) => {
    const rect = boxRef.current?.getBoundingClientRect()
    if (!rect) return
    setPos(Math.min(100, Math.max(0, ((clientX - rect.left) / rect.width) * 100)))
  }, [])

  const onPointerDown = (e) => {
    if (e.button !== 0) return
    const onHandle = e.target.closest?.('.compare-handle')
    if (view === 'split' && (onHandle || !zoomed)) {
      drag.current = { mode: 'slider' }
      setFromClientX(e.clientX)
    } else if (zoomed) {
      const vp = viewportRef.current
      drag.current = { mode: 'pan', x: e.clientX, y: e.clientY, left: vp.scrollLeft, top: vp.scrollTop }
    } else {
      return
    }
    e.currentTarget.setPointerCapture(e.pointerId)
    e.preventDefault()
  }

  const onPointerMove = (e) => {
    const d = drag.current
    if (!d) return
    if (d.mode === 'slider') setFromClientX(e.clientX)
    else {
      const vp = viewportRef.current
      vp.scrollLeft = d.left - (e.clientX - d.x)
      vp.scrollTop = d.top - (e.clientY - d.y)
    }
  }

  const endDrag = () => {
    drag.current = null
  }

  const onHandleKey = (e) => {
    const step = e.shiftKey ? 10 : 2
    if (e.key === 'ArrowLeft') setPos((p) => Math.max(0, p - step))
    else if (e.key === 'ArrowRight') setPos((p) => Math.min(100, p + step))
    else return
    e.preventDefault()
    e.stopPropagation()
  }

  // Keep the centre of the image in view when switching zoom levels.
  useLayoutEffect(() => {
    const vp = viewportRef.current
    if (!vp) return
    vp.scrollLeft = (vp.scrollWidth - vp.clientWidth) / 2
    vp.scrollTop = (vp.scrollHeight - vp.clientHeight) / 2
  }, [zoom])

  const pixelated = zoom === 2 ? 'pixelated' : 'auto'

  return (
    <div
      ref={viewportRef}
      className={`compare-viewport ${zoomed ? 'zoomed' : ''} ${drag.current?.mode === 'pan' ? 'panning' : ''}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      <div className="compare-canvas" style={{ width: boxW + pad, height: boxH + pad }}>
        <div ref={boxRef} className="compare-box checker" style={{ width: boxW, height: boxH }}>
          {before.shown && (
            <img
              className="compare-img"
              src={before.shown}
              alt="Original"
              draggable={false}
              style={{ objectFit: beforeFit, imageRendering: pixelated }}
            />
          )}
          {after.shown && (
            <img
              className="compare-img"
              src={after.shown}
              alt="Result"
              draggable={false}
              style={{ clipPath: `inset(0 0 0 ${shownPos}%)`, imageRendering: pixelated }}
            />
          )}
          {view === 'split' && after.shown && (
            <div
              className="compare-handle"
              style={{ left: `${pos}%` }}
              role="slider"
              tabIndex={0}
              aria-label="Compare original and result"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(pos)}
              onKeyDown={onHandleKey}
            >
              <span className="compare-grip" />
            </div>
          )}
          {view === 'split' && after.shown && (
            <>
              <span className="compare-label left" style={{ opacity: pos > 12 ? 1 : 0 }}>
                Original
              </span>
              <span className="compare-label right" style={{ opacity: pos < 88 ? 1 : 0 }}>
                Result
              </span>
            </>
          )}
          {after.failed && <div className="compare-error">This format can't be shown here.</div>}
        </div>
      </div>
    </div>
  )
}
