import { useCallback, useEffect, useRef, useState } from 'react'
import { api, uploadFiles, urls } from './api'
import ActionBar from './components/ActionBar'
import { useFeedback } from './components/Feedback'
import Icon from './components/Icon'
import PreviewPanel from './components/PreviewPanel'
import QueuePanel, { filterItems } from './components/QueuePanel'
import SettingsPanel from './components/SettingsPanel'
import TopBar from './components/TopBar'
import { downloadBlob, downloadUrl, filesFromDrop, isDesktopApp, nativeDropPaths, onBridgeReady, pickPaths } from './native'
import {
  DEFAULT_SETTINGS,
  applyPreset,
  exportSettingsFile,
  loadSettings,
  presetMatches,
  readSettingsFile,
  saveSettings,
} from './settings'
import { ACCEPTED_EXTENSIONS, isAcceptedFile, plural } from './utils/format'

const THEME_KEY = 'image-lab-theme'
const PRESET_KEY = 'image-lab-active-preset'

const FIELD_INPUT_IDS = {
  target_size: 'target-size',
  quality: 'quality',
  max_width: 'max-w',
  max_height: 'max-h',
  exact_width: 'ex-w',
  exact_height: 'ex-h',
  scale_percent: 'scale',
  output_dir: 'out-dir',
  naming_prefix: 'prefix',
  naming_suffix: 'suffix',
  bg_color: 'bg-color',
  png_colors: 'png-colors',
}

const SHORTCUTS = [
  ['⌘O', 'Add images'],
  ['⇧⌘O', 'Add a folder'],
  ['⌘V', 'Paste an image'],
  ['⌘↩', 'Process the queue'],
  ['Esc', 'Cancel processing'],
  ['↑ ↓', 'Select previous / next image'],
  ['⌫', 'Remove selected image'],
  ['Space (hold)', 'Show the original'],
  ['0 · 1 · 2', 'Zoom: fit · 100% · 200%'],
]

function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem(THEME_KEY) || 'system')
  useEffect(() => {
    localStorage.setItem(THEME_KEY, theme)
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme
    }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [theme])
  return [theme, setTheme]
}

const isTyping = (el) => Boolean(el?.closest?.('input, textarea, select, [contenteditable="true"]'))
const isControl = (el) => Boolean(el?.closest?.('button, [role="radio"], [role="slider"], a'))
const basename = (path) => (path || '').split('/').pop()

export default function App() {
  const { toast, confirm, prompt } = useFeedback()
  const [theme, setTheme] = useTheme()
  const [isApp, setIsApp] = useState(isDesktopApp)
  const [health, setHealth] = useState(null)
  const [engineDown, setEngineDown] = useState(false)
  const [items, setItems] = useState([])
  const [settings, setSettings] = useState(loadSettings)
  const [presets, setPresets] = useState([])
  const [activePresetId, setActivePresetId] = useState(() => localStorage.getItem(PRESET_KEY))
  const [selectedId, setSelectedId] = useState(null)
  const [filter, setFilter] = useState('all')
  const [status, setStatus] = useState(null)
  const [showSummary, setShowSummary] = useState(false)
  const [preview, setPreview] = useState({ status: 'idle', data: null, error: null, itemId: null })
  const [previewNonce, setPreviewNonce] = useState(0)
  const [upload, setUpload] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [holdOriginal, setHoldOriginal] = useState(false)
  const [settingsError, setSettingsError] = useState(null)

  const fileInput = useRef(null)
  const folderInput = useRef(null)
  const importInput = useRef(null)
  const versionRef = useRef(-1)
  const previewRun = useRef(0)
  const actions = useRef({})

  useEffect(() => onBridgeReady(() => setIsApp(true)), [])

  const refreshQueue = useCallback(async () => {
    const q = await api.queue()
    versionRef.current = q.version
    setItems(q.items)
    return q
  }, [])

  const loadPresets = useCallback(async () => {
    try {
      const data = await api.presets()
      setPresets(data.presets || [])
    } catch {
      /* presets are optional */
    }
  }, [])

  // ── boot (retries until the engine answers) ──────────────────────────
  useEffect(() => {
    let cancelled = false
    let timer
    const boot = async (attempt = 0) => {
      try {
        const [h, , st] = await Promise.all([api.health(), refreshQueue(), api.status()])
        if (cancelled) return
        setHealth(h)
        setStatus(st)
        setEngineDown(false)
        loadPresets()
      } catch {
        if (cancelled) return
        setEngineDown(true)
        timer = setTimeout(() => boot(attempt + 1), Math.min(4000, 400 * (attempt + 1)))
      }
    }
    boot()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [refreshQueue, loadPresets])

  // ── settings persistence & preset tracking ───────────────────────────
  useEffect(() => saveSettings(settings), [settings])

  useEffect(() => {
    if (activePresetId) localStorage.setItem(PRESET_KEY, activePresetId)
    else localStorage.removeItem(PRESET_KEY)
  }, [activePresetId])

  useEffect(() => {
    if (!activePresetId || !presets.length) return
    const preset = presets.find((p) => p.id === activePresetId)
    if (!preset || !presetMatches(preset, settings)) setActivePresetId(null)
  }, [settings, presets, activePresetId])

  const update = useCallback((key, value) => {
    setSettings((s) => ({ ...s, [key]: value }))
    setSettingsError((e) => (e?.field === key ? null : e))
  }, [])

  // ── selection ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!items.length) {
      if (selectedId) setSelectedId(null)
      return
    }
    if (!selectedId || !items.some((i) => i.id === selectedId)) setSelectedId(items[0].id)
  }, [items, selectedId])

  const selected = items.find((i) => i.id === selectedId) || null

  // ── batch polling ────────────────────────────────────────────────────
  const running = Boolean(status?.running)

  const onBatchFinished = useRef(() => {})
  onBatchFinished.current = (st) => {
    setShowSummary(true)
    if (!st.total) return
    if (st.failed) {
      toast(`${plural(st.failed, 'image')} failed`, {
        type: 'error',
        detail: `${st.done} processed. Select a failed image to see why.`,
        action: { label: 'Show', onClick: () => setFilter('failed') },
      })
    } else if (!st.cancelled) {
      toast(`Processed ${plural(st.done + st.skipped, 'image')}`, { type: 'success' })
    }
  }

  useEffect(() => {
    if (!running) return undefined
    let stopped = false
    let timer
    const tick = async () => {
      try {
        const st = await api.status()
        if (stopped) return
        setStatus(st)
        if (st.version !== versionRef.current) await refreshQueue()
        if (!st.running) {
          onBatchFinished.current(st)
          return
        }
      } catch {
        /* transient: keep polling */
      }
      if (!stopped) timer = setTimeout(tick, 400)
    }
    timer = setTimeout(tick, 200)
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [running, refreshQueue])

  useEffect(() => {
    document.title = running && status.total ? `${Math.round((status.completed / status.total) * 100)}% · Image Lab` : 'Image Lab'
  }, [running, status])

  // ── live preview ─────────────────────────────────────────────────────
  const previewKey = selected ? `${selected.id}|${JSON.stringify(settings)}` : null
  useEffect(() => {
    if (!previewKey) return undefined
    const id = previewKey.slice(0, previewKey.indexOf('|'))
    const body = JSON.parse(previewKey.slice(previewKey.indexOf('|') + 1))
    const controller = new AbortController()
    const run = ++previewRun.current
    setPreview((p) => ({ ...p, status: 'loading', itemId: id }))
    const timer = setTimeout(async () => {
      try {
        const data = await api.preview(id, body, controller.signal)
        if (run !== previewRun.current) return
        setPreview({ status: 'ready', data, error: null, itemId: id })
        setSettingsError(null)
      } catch (e) {
        if (e.name === 'AbortError' || run !== previewRun.current) return
        const error = { message: e.message, field: e.field || null }
        setPreview((p) => ({ status: 'error', data: p.data, error, itemId: id }))
        if (e.field) setSettingsError(error)
      }
    }, 260)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [previewKey, previewNonce])

  // ── adding images ────────────────────────────────────────────────────
  const reportAdded = useCallback(
    (result, unsupported = 0) => {
      const added = result.added?.length || 0
      const rejected = result.rejected || []
      const notes = []
      if (result.duplicates) notes.push(`${result.duplicates} already in the queue`)
      if (rejected.length + unsupported) notes.push(`${rejected.length + unsupported} skipped`)
      if (added) {
        toast(`Added ${plural(added, 'image')}`, { type: 'success', detail: notes.join(' · ') || undefined })
        setFilter('all')
        setSelectedId(result.added[0].id)
      } else {
        const why = rejected
          .slice(0, 3)
          .map((r) => `${r.name}: ${r.reason}`)
          .join('\n')
        toast(result.duplicates ? 'Those images are already in the queue' : 'No images were added', {
          type: rejected.length ? 'error' : 'info',
          detail: why || notes.join(' · ') || undefined,
        })
      }
    },
    [toast],
  )

  const addFiles = useCallback(
    async (fileList) => {
      const all = [...fileList]
      const files = all.filter((f) => isAcceptedFile(f.name))
      const unsupported = all.length - files.length
      if (!files.length) {
        if (all.length) toast('None of those files are supported images', { type: 'error', detail: ACCEPTED_EXTENSIONS.join(' ') })
        return
      }
      if (
        files.length > 1000 &&
        !(await confirm({
          title: `Add ${files.length.toLocaleString()} images?`,
          message: 'Large drops are copied into Image Lab first. Adding the folder instead processes them in place.',
          confirmLabel: 'Add them',
        }))
      ) {
        return
      }
      const total = files.reduce((sum, f) => sum + f.size, 0)
      setUpload({ loaded: 0, total, count: files.length })
      try {
        const result = await uploadFiles(files, (loaded) => setUpload({ loaded, total, count: files.length }))
        await refreshQueue()
        reportAdded(result, unsupported)
      } catch (e) {
        toast("Couldn't add images", { type: 'error', detail: e.message })
        refreshQueue().catch(() => {})
      } finally {
        setUpload(null)
      }
    },
    [confirm, refreshQueue, reportAdded, toast],
  )

  const addPaths = useCallback(
    async (paths) => {
      if (!paths?.length) return
      setUpload({ loaded: 0, total: 1, count: paths.length })
      try {
        const result = await api.addPaths(paths)
        await refreshQueue()
        reportAdded(result)
      } catch (e) {
        toast("Couldn't add those files", { type: 'error', detail: e.message })
      } finally {
        setUpload(null)
      }
    },
    [refreshQueue, reportAdded, toast],
  )

  const onAddFiles = useCallback(async () => {
    if (isApp) {
      try {
        const paths = await pickPaths('files', health)
        if (paths?.length) await addPaths(paths)
        return
      } catch (e) {
        toast("Couldn't open the file picker", { type: 'error', detail: e.message })
      }
    }
    fileInput.current?.click()
  }, [isApp, health, addPaths, toast])

  const onAddFolder = useCallback(async () => {
    try {
      const paths = await pickPaths('folder', health)
      if (paths === null) folderInput.current?.click()
      else if (paths.length) await addPaths(paths)
    } catch (e) {
      toast("Couldn't open the folder picker", { type: 'error', detail: e.message })
      folderInput.current?.click()
    }
  }, [health, addPaths, toast])

  // ── processing ───────────────────────────────────────────────────────
  const focusField = useCallback((field) => {
    setTimeout(() => {
      const el = document.getElementById(FIELD_INPUT_IDS[field])
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      el?.focus()
    }, 60)
  }, [])

  const process = useCallback(
    async (ids) => {
      if (running || !items.length) return
      const count = ids?.length || items.length
      if (
        settings.replace_originals &&
        !(await confirm({
          title: 'Replace original files?',
          message: `${plural(count, 'original')} will be overwritten with the processed version. This can't be undone.`,
          confirmLabel: 'Replace originals',
          danger: true,
        }))
      ) {
        return
      }
      try {
        const result = await api.process(settings, ids)
        setShowSummary(false)
        setSettingsError(null)
        setStatus(result.progress)
        await refreshQueue()
      } catch (e) {
        if (e.field) {
          setSettingsError({ field: e.field, message: e.message })
          focusField(e.field)
          toast('Check your settings', { type: 'error', detail: e.message })
        } else {
          toast("Couldn't start processing", { type: 'error', detail: e.message })
        }
      }
    },
    [running, items.length, settings, confirm, refreshQueue, focusField, toast],
  )

  const cancel = useCallback(async () => {
    try {
      const result = await api.cancel()
      setStatus(result.progress)
    } catch (e) {
      toast("Couldn't cancel", { type: 'error', detail: e.message })
    }
  }, [toast])

  const retryFailed = useCallback(() => {
    const ids = items.filter((i) => i.status === 'failed').map((i) => i.id)
    if (ids.length) process(ids)
  }, [items, process])

  // ── queue actions ────────────────────────────────────────────────────
  const removeItem = useCallback(
    async (id) => {
      const visible = filterItems(items, filter)
      const index = visible.findIndex((i) => i.id === id)
      try {
        await api.remove([id])
        if (id === selectedId) setSelectedId(visible[index + 1]?.id || visible[index - 1]?.id || null)
        await refreshQueue()
      } catch (e) {
        toast("Couldn't remove image", { type: 'error', detail: e.message })
      }
    },
    [items, filter, selectedId, refreshQueue, toast],
  )

  const clearQueue = useCallback(
    async (scope) => {
      if (
        scope === 'all' &&
        !(await confirm({
          title: `Clear ${plural(items.length, 'image')}?`,
          message: 'They are removed from the queue only. Files on disk are not touched.',
          confirmLabel: 'Clear queue',
        }))
      ) {
        return
      }
      try {
        const result = await api.clear(scope)
        await refreshQueue()
        if (scope === 'all') {
          setPreview({ status: 'idle', data: null, error: null, itemId: null })
          setShowSummary(false)
        }
        if (scope === 'finished') toast(`Removed ${plural(result.removed, 'finished image')}`)
      } catch (e) {
        toast("Couldn't clear the queue", { type: 'error', detail: e.message })
      }
    },
    [items.length, confirm, refreshQueue, toast],
  )

  const reveal = useCallback(
    async (path) => {
      try {
        await api.reveal(path)
      } catch (e) {
        toast("Couldn't show that in Finder", { type: 'error', detail: e.message })
      }
    },
    [toast],
  )

  const doneItems = items.filter((i) => i.result?.output_path)

  const revealOutput = useCallback(() => {
    const target =
      (selected?.result?.output_path && selected.result.output_path) ||
      doneItems[doneItems.length - 1]?.result.output_path ||
      health?.default_output_dir
    if (target) reveal(target)
  }, [selected, doneItems, health, reveal])

  const save = useCallback(
    async (url, filename) => {
      try {
        const result = await downloadUrl(url, filename)
        if (result?.path) toast('Saved', { type: 'success', detail: result.path })
      } catch (e) {
        toast("Couldn't save the file", { type: 'error', detail: e.message })
      }
    },
    [toast],
  )

  // ── presets & settings files ─────────────────────────────────────────
  const onApplyPreset = useCallback(
    (preset) => {
      setSettings((current) => applyPreset(preset, current))
      setActivePresetId(preset.id)
      setSettingsError(null)
      toast(`Applied “${preset.name}”`)
    },
    [toast],
  )

  const onSavePreset = useCallback(async () => {
    const values = await prompt({
      title: 'Save preset',
      message: 'Saves every setting, including output folder and naming.',
      confirmLabel: 'Save preset',
      fields: [
        { name: 'name', label: 'Name', required: true, maxLength: 60, placeholder: 'e.g. Blog images' },
        { name: 'description', label: 'Description (optional)', maxLength: 200, placeholder: 'What it’s for' },
      ],
    })
    if (!values) return
    try {
      const { preset } = await api.savePreset({ name: values.name.trim(), description: values.description, settings })
      await loadPresets()
      setActivePresetId(preset.id)
      toast(`Saved preset “${preset.name}”`, { type: 'success' })
    } catch (e) {
      toast("Couldn't save the preset", { type: 'error', detail: e.message })
    }
  }, [prompt, settings, loadPresets, toast])

  const onDeletePreset = useCallback(
    async (preset) => {
      if (!(await confirm({ title: `Delete “${preset.name}”?`, confirmLabel: 'Delete', danger: true }))) return
      try {
        await api.deletePreset(preset.id)
        if (activePresetId === preset.id) setActivePresetId(null)
        await loadPresets()
      } catch (e) {
        toast("Couldn't delete the preset", { type: 'error', detail: e.message })
      }
    },
    [confirm, activePresetId, loadPresets, toast],
  )

  const onExportSettings = useCallback(async () => {
    const { blob, filename } = exportSettingsFile(settings)
    try {
      await downloadBlob(blob, filename)
    } catch (e) {
      toast("Couldn't export settings", { type: 'error', detail: e.message })
    }
  }, [settings, toast])

  const onResetSettings = useCallback(async () => {
    if (!(await confirm({ title: 'Reset all settings?', message: 'Restores the defaults. Saved presets are kept.', confirmLabel: 'Reset' }))) return
    setSettings({ ...DEFAULT_SETTINGS })
    setActivePresetId(null)
    setSettingsError(null)
  }, [confirm])

  const showShortcuts = useCallback(() => {
    confirm({
      title: 'Keyboard shortcuts',
      cancelLabel: null,
      confirmLabel: 'Done',
      message: (
        <dl className="shortcuts">
          {SHORTCUTS.map(([keys, label]) => (
            <div key={keys}>
              <dt>
                <kbd>{keys}</kbd>
              </dt>
              <dd>{label}</dd>
            </div>
          ))}
        </dl>
      ),
    })
  }, [confirm])

  const pickOutput = useCallback(async () => {
    try {
      const paths = await pickPaths('output', health)
      if (paths?.length) update('output_dir', paths[0])
    } catch (e) {
      toast("Couldn't open the folder picker", { type: 'error', detail: e.message })
    }
  }, [health, update, toast])

  // ── global input: drop, paste, keys ──────────────────────────────────
  actions.current = { addFiles, addPaths, onAddFiles, onAddFolder, process, cancel, removeItem, showShortcuts, running, selectedId, items, filter }

  useEffect(() => {
    let depth = 0
    const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files')
    const enter = (e) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth += 1
      setDragging(true)
    }
    const over = (e) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    }
    const leave = (e) => {
      if (!hasFiles(e)) return
      depth = Math.max(0, depth - 1)
      if (!depth) setDragging(false)
    }
    const drop = (e) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth = 0
      setDragging(false)
      const files = filesFromDrop(e.dataTransfer).catch(() => [...(e.dataTransfer.files || [])])
      nativeDropPaths().then((paths) =>
        paths ? actions.current.addPaths(paths) : files.then((list) => actions.current.addFiles(list)),
      )
    }
    const paste = (e) => {
      if (isTyping(e.target)) return
      const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/'))
      if (!files.length) return
      e.preventDefault()
      const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
      actions.current.addFiles(
        files.map((f, i) =>
          isAcceptedFile(f.name) && f.name !== 'image.png' ? f : new File([f], `pasted-${stamp}${i ? `-${i}` : ''}.${f.type.split('/')[1] || 'png'}`, { type: f.type }),
        ),
      )
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    window.addEventListener('paste', paste)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
      window.removeEventListener('paste', paste)
    }
  }, [])

  useEffect(() => {
    const down = (e) => {
      const a = actions.current
      if (document.querySelector('.modal-backdrop')) return
      const mod = e.metaKey || e.ctrlKey
      const key = e.key.toLowerCase()
      if (mod && key === 'o') {
        e.preventDefault()
        if (e.shiftKey) a.onAddFolder()
        else a.onAddFiles()
        return
      }
      if (mod && e.key === 'Enter') {
        e.preventDefault()
        a.process()
        return
      }
      if (isTyping(e.target) || mod) return
      if (e.key === 'Escape' && a.running) {
        a.cancel()
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const visible = filterItems(a.items, a.filter)
        if (!visible.length) return
        const index = visible.findIndex((i) => i.id === a.selectedId)
        const next = e.key === 'ArrowDown' ? Math.min(visible.length - 1, index + 1) : Math.max(0, index - 1)
        setSelectedId(visible[index < 0 ? 0 : next].id)
      } else if ((e.key === 'Backspace' || e.key === 'Delete') && a.selectedId) {
        a.removeItem(a.selectedId)
      } else if (e.key === ' ' && !isControl(e.target)) {
        if (!e.repeat) setHoldOriginal(true)
      } else if (e.key === '?') {
        a.showShortcuts()
      } else {
        return
      }
      e.preventDefault()
    }
    const up = (e) => e.key === ' ' && setHoldOriginal(false)
    const blur = () => setHoldOriginal(false)
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', blur)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', blur)
    }
  }, [])

  const revealLabel = isApp || health?.platform === 'darwin' ? 'Show in Finder' : 'Open folder'

  return (
    <div className="app">
      <TopBar
        health={health}
        presets={presets}
        activePresetId={activePresetId}
        onApplyPreset={onApplyPreset}
        onSavePreset={onSavePreset}
        onDeletePreset={onDeletePreset}
        onImportSettings={() => importInput.current?.click()}
        onExportSettings={onExportSettings}
        onResetSettings={onResetSettings}
        theme={theme}
        setTheme={setTheme}
        onShowShortcuts={showShortcuts}
        isApp={isApp}
      />

      <div className="workspace">
        <QueuePanel
          items={items}
          selectedId={selectedId}
          onSelect={setSelectedId}
          filter={filter}
          setFilter={setFilter}
          onRemove={removeItem}
          onReveal={reveal}
          onDownload={(item) => save(urls.output(item.id, true), basename(item.result.output_path))}
          onAddFiles={onAddFiles}
          onAddFolder={onAddFolder}
          onClear={clearQueue}
          onRetryFailed={retryFailed}
          running={running}
          upload={upload}
        />
        <PreviewPanel
          item={selected}
          hasItems={items.length > 0}
          preview={preview}
          settings={settings}
          holdOriginal={holdOriginal}
          onRetry={() => setPreviewNonce((n) => n + 1)}
          onAddFiles={onAddFiles}
          onAddFolder={onAddFolder}
          onReveal={reveal}
          onFocusField={focusField}
          health={health}
        />
        <SettingsPanel
          settings={settings}
          update={update}
          health={health}
          error={settingsError}
          exampleFile={selected?.filename}
          onPickOutput={pickOutput}
          onRevealOutput={revealOutput}
          isApp={isApp}
        />
      </div>

      <ActionBar
        status={status}
        showSummary={showSummary}
        onDismissSummary={() => setShowSummary(false)}
        count={items.length}
        doneCount={doneItems.length}
        onProcess={() => process()}
        onCancel={cancel}
        onZip={() => save(urls.zip(), isApp ? 'Image Lab export.zip' : undefined)}
        onCsv={() => save(urls.csv, isApp ? 'Image Lab report.csv' : undefined)}
        onRevealOutput={revealOutput}
        onRetryFailed={retryFailed}
        revealLabel={revealLabel}
      />

      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        accept={['image/*', ...ACCEPTED_EXTENSIONS].join(',')}
        onChange={(e) => {
          addFiles(e.target.files)
          e.target.value = ''
        }}
      />
      <input
        ref={folderInput}
        type="file"
        hidden
        webkitdirectory=""
        directory=""
        multiple
        onChange={(e) => {
          addFiles(e.target.files)
          e.target.value = ''
        }}
      />
      <input
        ref={importInput}
        type="file"
        hidden
        accept=".json,application/json"
        onChange={async (e) => {
          const file = e.target.files?.[0]
          e.target.value = ''
          if (!file) return
          try {
            setSettings(await readSettingsFile(file))
            setActivePresetId(null)
            toast('Settings imported', { type: 'success' })
          } catch {
            toast("That file isn't an Image Lab settings file", { type: 'error' })
          }
        }}
      />

      {dragging && (
        <div className="drop-overlay">
          <div className="drop-card">
            <Icon name="upload" size={28} />
            <div className="drop-title">Drop to add images</div>
            <div className="muted">Files and folders · {ACCEPTED_EXTENSIONS.length} formats</div>
          </div>
        </div>
      )}

      {engineDown && (
        <div className="engine-down" role="alert">
          <div className="engine-card">
            <span className="spinner" style={{ width: 22, height: 22 }} />
            <h2>Connecting to the Image Lab engine…</h2>
            <p className="muted">
              {isApp ? 'This usually takes a second.' : 'Make sure the backend is running (./start.sh). Retrying automatically.'}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
