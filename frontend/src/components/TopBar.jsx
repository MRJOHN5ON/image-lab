import { IconButton } from './controls'
import Icon from './Icon'
import Menu from './Menu'

function Logo() {
  return (
    <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6aa8ff" />
          <stop offset="1" stopColor="#3b6cf6" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#lg)" />
      <path d="M8 21.5l5-5.5 3.5 3.5 2.5-2.5 5 4.5" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="20.5" cy="11.5" r="2.3" fill="#fff" />
    </svg>
  )
}

export default function TopBar({
  health,
  presets,
  activePresetId,
  onApplyPreset,
  onSavePreset,
  onDeletePreset,
  onImportSettings,
  onExportSettings,
  onResetSettings,
  theme,
  setTheme,
  onShowShortcuts,
  isApp,
}) {
  const builtin = presets.filter((p) => p.builtin)
  const custom = presets.filter((p) => !p.builtin)
  const active = presets.find((p) => p.id === activePresetId)

  const presetItem = (p) => ({
    key: p.id,
    label: p.name,
    hint: p.description,
    checked: p.id === activePresetId,
    onClick: () => onApplyPreset(p),
    aside: p.builtin ? null : (
      <button type="button" className="menu-aside" aria-label={`Delete ${p.name}`} title="Delete preset" onClick={() => onDeletePreset(p)}>
        <Icon name="trash" size={13} />
      </button>
    ),
  })

  return (
    <header className={`topbar ${isApp ? 'in-app' : ''}`}>
      <div className="brand">
        <Logo />
        <span className="brand-name">Image Lab</span>
        {health?.version && <span className="brand-version">{health.version}</span>}
      </div>

      <Menu
        width={320}
        className="preset-menu"
        trigger={({ toggle, open }) => (
          <button type="button" className={`preset-trigger ${open ? 'open' : ''}`} onClick={toggle}>
            <Icon name="sliders" size={15} />
            <span className="preset-label">{active ? active.name : 'Presets'}</span>
            <Icon name="chevronDown" size={14} />
          </button>
        )}
        items={[
          { header: 'Built-in' },
          ...builtin.map(presetItem),
          custom.length ? { header: 'Your presets' } : null,
          ...custom.map(presetItem),
          { divider: true },
          { label: 'Save current settings as preset…', icon: 'save', onClick: onSavePreset },
        ]}
      />

      <div className="topbar-spacer" />

      {health && (
        <div className="caps" aria-label="Engine capabilities">
          <span className={`cap ${health.jpegtran_available ? 'ok' : 'missing'}`} title={health.jpegtran_available ? 'jpegtran found: extra lossless JPEG savings' : 'Optional: install jpegtran (brew install jpeg-turbo) for extra lossless JPEG savings'}>
            jpegtran
          </span>
          <span className={`cap ${health.heif_available ? 'ok' : 'missing'}`} title="HEIC/HEIF support">
            HEIC
          </span>
          <span className={`cap ${health.avif_supported ? 'ok' : 'missing'}`} title="AVIF support">
            AVIF
          </span>
        </div>
      )}

      <Menu
        align="right"
        width={250}
        trigger={({ toggle }) => <IconButton icon="more" label="More" onClick={toggle} />}
        items={[
          { header: 'Appearance' },
          { label: 'System', icon: 'monitor', checked: theme === 'system', onClick: () => setTheme('system') },
          { label: 'Light', icon: 'sun', checked: theme === 'light', onClick: () => setTheme('light') },
          { label: 'Dark', icon: 'moon', checked: theme === 'dark', onClick: () => setTheme('dark') },
          { divider: true },
          { label: 'Import settings…', icon: 'upload', onClick: onImportSettings },
          { label: 'Export settings…', icon: 'download', onClick: onExportSettings },
          { label: 'Reset to defaults', icon: 'refresh', onClick: onResetSettings },
          { divider: true },
          { label: 'Keyboard shortcuts', icon: 'keyboard', kbd: '?', onClick: onShowShortcuts },
        ]}
      />
    </header>
  )
}
