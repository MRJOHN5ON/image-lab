import { useEffect, useState } from 'react'
import { exampleOutputName, shortenPath } from '../utils/format'
import {
  Button,
  ColorInput,
  Field,
  NumberInput,
  RangeInput,
  Section,
  Segmented,
  Select,
  Switch,
  TextInput,
} from './controls'
import Icon from './Icon'

const SECTION_OF_FIELD = {
  output_format: 'format',
  bg_color: 'format',
  compress_mode: 'compress',
  target_size: 'compress',
  target_unit: 'compress',
  quality: 'compress',
  subsampling: 'compress',
  png_colors: 'compress',
  resize_mode: 'resize',
  max_width: 'resize',
  max_height: 'resize',
  exact_width: 'resize',
  exact_height: 'resize',
  scale_percent: 'resize',
  fit_mode: 'resize',
  upscale_factor: 'upscale',
  output_dir: 'output',
  naming_prefix: 'output',
  naming_suffix: 'output',
  on_conflict: 'output',
}

const OPEN_KEY = 'image-lab-open-sections'

function loadOpen() {
  try {
    return { format: true, compress: true, resize: true, ...JSON.parse(localStorage.getItem(OPEN_KEY) || '{}') }
  } catch {
    return { format: true, compress: true, resize: true }
  }
}

function compressSummary(s) {
  if (!s.compress_enabled) return 'Off'
  if (s.compress_mode === 'target_size') return `≤ ${s.target_size} ${s.target_unit}`
  if (s.compress_mode === 'lossless') return 'Lossless'
  return `Quality ${s.quality}`
}

function resizeSummary(s) {
  if (!s.resize_enabled) return 'Off'
  if (s.resize_mode === 'scale') return s.scale_percent ? `${s.scale_percent}%` : 'Scale'
  if (s.resize_mode === 'exact') return `${s.exact_width || 'auto'}×${s.exact_height || 'auto'} ${s.fit_mode}`
  return `Fit ${s.max_width || '∞'}×${s.max_height || '∞'}`
}

const FORMAT_NOTES = {
  keep: 'Each file keeps its format. HEIC becomes JPEG.',
  JPEG: 'Best compatibility. No transparency.',
  WEBP: 'Smaller than JPEG, supports transparency. Works in all modern browsers.',
  AVIF: 'Smallest files, slower to encode. Supported by modern browsers.',
  PNG: 'Lossless with transparency. Large for photos.',
  TIFF: 'Lossless (LZW). For print and archiving.',
}

export default function SettingsPanel({ settings, update, health, error, exampleFile, onPickOutput, onRevealOutput, isApp }) {
  const [open, setOpen] = useState(loadOpen)
  const s = settings
  const err = (field) => (error?.field === field ? error.message : null)

  useEffect(() => {
    const section = error?.field && SECTION_OF_FIELD[error.field]
    if (section) setOpen((o) => ({ ...o, [section]: true }))
  }, [error])

  useEffect(() => {
    localStorage.setItem(OPEN_KEY, JSON.stringify(open))
  }, [open])

  const section = (key) => ({ open: !!open[key], onOpenChange: (v) => setOpen((o) => ({ ...o, [key]: v })) })
  const lossy = s.output_format !== 'PNG' && s.output_format !== 'TIFF'
  const jpegOut = s.output_format === 'JPEG'
  const canPick = isApp || health?.native_dialogs

  return (
    <aside className="inspector" aria-label="Settings">
      <Section title="Format" icon="file" summary={s.output_format === 'keep' ? 'Original' : s.output_format} {...section('format')}>
        <Field error={err('output_format')} hint={FORMAT_NOTES[s.output_format]}>
          <Segmented
            ariaLabel="Output format"
            value={s.output_format}
            onChange={(v) => update('output_format', v)}
            options={[
              { value: 'keep', label: 'Original' },
              { value: 'JPEG', label: 'JPEG' },
              { value: 'WEBP', label: 'WebP' },
              {
                value: 'AVIF',
                label: 'AVIF',
                disabled: health && !health.avif_supported,
                title: health && !health.avif_supported ? 'AVIF is not supported by this Pillow build' : undefined,
              },
              { value: 'PNG', label: 'PNG' },
              { value: 'TIFF', label: 'TIFF' },
            ]}
          />
        </Field>
        {(jpegOut || s.fit_mode === 'pad') && (
          <Field label="Background" htmlFor="bg-color" error={err('bg_color')} hint="Fills transparent areas and padding">
            <ColorInput id="bg-color" value={s.bg_color} onChange={(v) => update('bg_color', v)} />
          </Field>
        )}
      </Section>

      <Section
        title="Compression"
        icon="layers"
        enabled={s.compress_enabled}
        onToggle={(v) => update('compress_enabled', v)}
        summary={compressSummary(s)}
        {...section('compress')}
      >
        <Field error={err('compress_mode')}>
          <Segmented
            ariaLabel="Compression mode"
            value={s.compress_mode}
            onChange={(v) => update('compress_mode', v)}
            options={[
              { value: 'target_size', label: 'Target size' },
              { value: 'quality', label: 'Quality' },
              { value: 'lossless', label: 'Lossless' },
            ]}
          />
        </Field>

        {s.compress_mode === 'target_size' && (
          <>
            <Field
              label="Max file size"
              htmlFor="target-size"
              error={err('target_size')}
              hint="Searches for the highest quality that fits. Files already under the limit are kept as-is."
            >
              <div className="row gap-s">
                <NumberInput
                  id="target-size"
                  value={s.target_size}
                  onChange={(v) => v != null && update('target_size', v)}
                  min={0.001}
                  step={s.target_unit === 'MB' ? 0.5 : 50}
                  integer={false}
                  invalid={!!err('target_size')}
                />
                <Segmented
                  size="sm"
                  ariaLabel="Size unit"
                  value={s.target_unit}
                  onChange={(v) => update('target_unit', v)}
                  options={[
                    { value: 'KB', label: 'KB' },
                    { value: 'MB', label: 'MB' },
                  ]}
                />
              </div>
            </Field>
            <Field label="Highest quality to try" htmlFor="quality" error={err('quality')}>
              <RangeInput id="quality" value={s.quality} onChange={(v) => update('quality', v)} />
            </Field>
          </>
        )}

        {s.compress_mode === 'quality' && (
          <Field
            label="Quality"
            htmlFor="quality"
            error={err('quality')}
            hint={lossy ? '80–90 is visually lossless for most photos.' : 'PNG and TIFF are always lossless.'}
          >
            <RangeInput id="quality" value={s.quality} onChange={(v) => update('quality', v)} />
          </Field>
        )}

        {s.compress_mode === 'lossless' && (
          <div className="note">
            <Icon name="lock" size={14} />
            <span>
              Pixels are never changed. JPEGs keep their encoding
              {health?.jpegtran_available ? ' and get jpegtran Huffman optimisation' : ''}; PNG is re-packed; WebP is saved
              lossless.
              {(s.resize_enabled || s.upscale_enabled) && ' Resizing a JPEG requires re-encoding at quality 95.'}
            </span>
          </div>
        )}

        <details className="advanced">
          <summary>
            <Icon name="chevronRight" size={12} /> Advanced
          </summary>
          <Switch label="Progressive JPEG" hint="Loads gradually on slow connections" checked={s.progressive} onChange={(v) => update('progressive', v)} />
          <Field label="Chroma subsampling" htmlFor="subsampling" error={err('subsampling')}>
            <Select
              id="subsampling"
              value={String(s.subsampling)}
              onChange={(v) => update('subsampling', Number(v))}
              options={[
                { value: '0', label: '4:4:4 — sharpest colour edges' },
                { value: '1', label: '4:2:2 — balanced' },
                { value: '2', label: '4:2:0 — smallest files' },
              ]}
            />
          </Field>
          <Switch
            label="Never make files larger"
            hint="Keep the original encoding if re-compressing would grow the file"
            checked={s.never_larger}
            onChange={(v) => update('never_larger', v)}
          />
          <Switch label="Reduce PNG colours" hint="Lossy palette quantisation" checked={s.png_palette} onChange={(v) => update('png_palette', v)} />
          {s.png_palette && (
            <Field label="Colours" htmlFor="png-colors" error={err('png_colors')}>
              <NumberInput id="png-colors" value={s.png_colors} onChange={(v) => v != null && update('png_colors', v)} min={2} max={256} width={96} />
            </Field>
          )}
        </details>
      </Section>

      <Section
        title="Resize"
        icon="maximize"
        enabled={s.resize_enabled}
        onToggle={(v) => update('resize_enabled', v)}
        summary={resizeSummary(s)}
        {...section('resize')}
      >
        <Field error={err('resize_mode')}>
          <Segmented
            ariaLabel="Resize mode"
            value={s.resize_mode}
            onChange={(v) => update('resize_mode', v)}
            options={[
              { value: 'fit', label: 'Fit within' },
              { value: 'exact', label: 'Exact size' },
              { value: 'scale', label: 'Scale' },
            ]}
          />
        </Field>

        {s.resize_mode === 'fit' && (
          <>
            <div className="row gap-s">
              <Field label="Max width" htmlFor="max-w" error={err('max_width')}>
                <NumberInput id="max-w" value={s.max_width} onChange={(v) => update('max_width', v)} min={1} max={65535} allowEmpty placeholder="Any" suffix="px" invalid={!!err('max_width')} />
              </Field>
              <Field label="Max height" htmlFor="max-h" error={err('max_height')}>
                <NumberInput id="max-h" value={s.max_height} onChange={(v) => update('max_height', v)} min={1} max={65535} allowEmpty placeholder="Any" suffix="px" />
              </Field>
            </div>
            <Switch label="Enlarge smaller images" checked={s.allow_enlarge} onChange={(v) => update('allow_enlarge', v)} />
          </>
        )}

        {s.resize_mode === 'exact' && (
          <>
            <div className="row gap-s">
              <Field label="Width" htmlFor="ex-w" error={err('exact_width')}>
                <NumberInput id="ex-w" value={s.exact_width} onChange={(v) => update('exact_width', v)} min={1} max={65535} allowEmpty placeholder="Auto" suffix="px" invalid={!!err('exact_width')} />
              </Field>
              <Field label="Height" htmlFor="ex-h" error={err('exact_height')}>
                <NumberInput id="ex-h" value={s.exact_height} onChange={(v) => update('exact_height', v)} min={1} max={65535} allowEmpty placeholder="Auto" suffix="px" />
              </Field>
            </div>
            {s.exact_width && s.exact_height ? (
              <Field
                label="Fit"
                hint={
                  s.fit_mode === 'cover'
                    ? 'Fill the frame, cropping the overflow from the centre.'
                    : s.fit_mode === 'contain'
                      ? 'Fit inside the frame without cropping; output may be smaller.'
                      : 'Fit inside and pad to the exact size with the background colour.'
                }
              >
                <Segmented
                  ariaLabel="Fit mode"
                  value={s.fit_mode}
                  onChange={(v) => update('fit_mode', v)}
                  options={[
                    { value: 'cover', label: 'Crop to fill' },
                    { value: 'contain', label: 'Fit' },
                    { value: 'pad', label: 'Pad' },
                  ]}
                />
              </Field>
            ) : (
              <div className="hint">Leave one side empty to keep the aspect ratio.</div>
            )}
          </>
        )}

        {s.resize_mode === 'scale' && (
          <Field label="Scale" htmlFor="scale" error={err('scale_percent')}>
            <NumberInput id="scale" value={s.scale_percent} onChange={(v) => update('scale_percent', v)} min={1} max={1000} integer={false} allowEmpty placeholder="50" suffix="%" invalid={!!err('scale_percent')} />
          </Field>
        )}

        <Field label="Resampling" htmlFor="resample">
          <Select
            id="resample"
            value={s.resample}
            onChange={(v) => update('resample', v)}
            options={[
              { value: 'lanczos', label: 'Lanczos — sharpest (recommended)' },
              { value: 'bicubic', label: 'Bicubic — smooth' },
              { value: 'bilinear', label: 'Bilinear — soft' },
              { value: 'nearest', label: 'Nearest — pixel art' },
            ]}
          />
        </Field>
      </Section>

      <Section
        title="Upscale"
        icon="spark"
        enabled={s.upscale_enabled}
        onToggle={(v) => update('upscale_enabled', v)}
        summary={s.upscale_enabled ? `${s.upscale_factor}×` : 'Off'}
        {...section('upscale')}
      >
        <Field label="Factor" error={err('upscale_factor')}>
          <div className="row gap-s">
            <Segmented
              size="sm"
              ariaLabel="Upscale factor"
              value={s.upscale_factor}
              onChange={(v) => update('upscale_factor', v)}
              options={[1.5, 2, 3, 4].map((f) => ({ value: f, label: `${f}×` }))}
            />
            <NumberInput value={s.upscale_factor} onChange={(v) => v != null && update('upscale_factor', v)} min={1} max={8} step={0.5} integer={false} width={72} suffix="×" />
          </div>
        </Field>
        <div className="note">
          <Icon name="info" size={14} />
          <span>Lanczos interpolation makes images bigger, not sharper. It can't invent detail.</span>
        </div>
      </Section>

      <Section
        title="Metadata & cleanup"
        icon="eye"
        summary={[s.strip_metadata ? 'Strip' : 'Keep', s.auto_rotate && 'rotate'].filter(Boolean).join(' · ')}
        {...section('metadata')}
      >
        <Switch label="Strip metadata" hint="Removes camera info, GPS location and edit history" checked={s.strip_metadata} onChange={(v) => update('strip_metadata', v)} />
        <Switch
          label="Keep colour profile"
          hint="Recommended. Without it, wide-gamut photos (iPhone, P3) shift colour."
          checked={s.keep_icc || !s.strip_metadata}
          disabled={!s.strip_metadata}
          onChange={(v) => update('keep_icc', v)}
        />
        <Switch label="Auto-rotate" hint="Apply the camera's orientation flag" checked={s.auto_rotate} onChange={(v) => update('auto_rotate', v)} />
        <Switch label="Trim transparent edges" checked={s.trim_transparent} onChange={(v) => update('trim_transparent', v)} />
      </Section>

      <Section title="Output" icon="folder" summary={s.replace_originals ? 'Replace originals' : s.output_dir ? shortenPath(s.output_dir, 24) : 'processed/'} {...section('output')}>
        {!s.replace_originals && (
          <Field label="Save to" htmlFor="out-dir" error={err('output_dir')}>
            <div className="path-box">
              <Icon name="folder" size={14} />
              <TextInput
                id="out-dir"
                mono
                value={s.output_dir}
                onChange={(v) => update('output_dir', v)}
                placeholder="processed/ next to each original"
                invalid={!!err('output_dir')}
              />
            </div>
            <div className="row gap-s wrap">
              {canPick && (
                <Button size="sm" icon="folderOpen" onClick={onPickOutput}>
                  Choose…
                </Button>
              )}
              {s.output_dir && (
                <Button size="sm" variant="ghost" onClick={() => update('output_dir', '')}>
                  Reset
                </Button>
              )}
              <Button size="sm" variant="ghost" icon="reveal" onClick={onRevealOutput}>
                {isApp || health?.platform === 'darwin' ? 'Show in Finder' : 'Open'}
              </Button>
            </div>
            {!s.output_dir && (
              <div className="hint">
                Dropped files have no folder of their own, so they go to{' '}
                <code>{shortenPath(health?.default_output_dir || '~/Pictures/Image Lab', 40)}</code>.
              </div>
            )}
          </Field>
        )}

        {!s.replace_originals && (
          <div className="row gap-s">
            <Field label="Prefix" htmlFor="prefix" error={err('naming_prefix')}>
              <TextInput id="prefix" value={s.naming_prefix} onChange={(v) => update('naming_prefix', v)} placeholder="none" invalid={!!err('naming_prefix')} />
            </Field>
            <Field label="Suffix" htmlFor="suffix" error={err('naming_suffix')}>
              <TextInput id="suffix" value={s.naming_suffix} onChange={(v) => update('naming_suffix', v)} placeholder="none" invalid={!!err('naming_suffix')} />
            </Field>
          </div>
        )}
        <div className="example-name">
          <span className="hint">Example</span>
          <code title={exampleOutputName(exampleFile, s)}>{exampleOutputName(exampleFile, s)}</code>
        </div>

        <Field label="If the file exists" error={err('on_conflict')}>
          <Segmented
            ariaLabel="When the output exists"
            value={s.on_conflict}
            onChange={(v) => update('on_conflict', v)}
            options={[
              { value: 'overwrite', label: 'Replace' },
              { value: 'rename', label: 'Keep both' },
              { value: 'skip', label: 'Skip' },
            ]}
          />
        </Field>
        <Switch label="Keep original dates" hint="Copy the modification date to the output" checked={s.preserve_dates} onChange={(v) => update('preserve_dates', v)} />
        <Switch
          label="Replace originals"
          hint="Overwrites source files in place. Can't be undone."
          danger
          checked={s.replace_originals}
          onChange={(v) => update('replace_originals', v)}
        />
        {s.replace_originals && (
          <div className="note danger">
            <Icon name="alert" size={14} />
            <span>Originals will be overwritten. If the format changes, the new file is written beside the original.</span>
          </div>
        )}
      </Section>
    </aside>
  )
}
