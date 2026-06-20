# Image Lab

Local-first batch image processor — compress, convert, resize, and optimize hundreds of photos in seconds. No cloud, no subscriptions. Everything runs on your machine.

## Quick start

```bash
chmod +x start.sh dev.sh
./start.sh
```

Open **http://127.0.0.1:8765** (production build served by backend).

For development with hot reload:

```bash
./dev.sh
```

Frontend dev server: **http://127.0.0.1:5173** (proxies API to backend).

## Features

- **Drag & drop** batch queue with thumbnails and live progress
- **Compress** to target file size (binary search) or quality — ports proven `compress_jpeg.py` logic
- **Lossless jpegtran** optimization when installed (`brew install jpeg`)
- **Resize**, **upscale** (honest Lanczos — not AI), **format convert**
- **Strip EXIF**, auto-rotate, trim transparent borders
- **Presets**: Web gallery, Email 12MB, Social OG, Print quality, PNG→JPG, Thumbnails, Upscale 2×
- **Preview** before/after with size and quality stats
- **Export** CSV report and ZIP download
- **Settings** export/import as JSON

## CLI (same engine)

```bash
python compress_jpeg.py photo.jpg -m 12 -o output.jpg
```

## Optional system tools

| Tool | Install | Purpose |
|------|---------|---------|
| jpegtran | `brew install jpeg` | Lossless JPEG optimization |
| pillow-heif | `pip install pillow-heif` | HEIC/HEIF support (included in requirements) |

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Pillow version, jpegtran/HEIC availability |
| `/api/queue` | GET/POST/DELETE | Manage file queue |
| `/api/process` | POST | Start batch with settings JSON |
| `/api/process/status` | GET | Progress, ETA, files/sec |
| `/api/preview` | POST | Single-file preview |
| `/api/presets` | GET/POST | Built-in + custom presets |
| `/api/report` | GET | CSV/JSON processing report |
| `/api/export/zip` | POST | Download all processed files |

## Project structure

```
image-lab/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── batch_queue.py       # Batch queue + thread pool
│   └── processor/
│       ├── compress.py      # Target size + jpegtran
│       ├── resize.py
│       ├── upscale.py
│       ├── convert.py
│       └── pipeline.py      # Operation chain
├── frontend/                # React + Vite
├── presets/default.json
├── compress_jpeg.py         # CLI wrapper
├── start.sh
└── dev.sh
```

## Performance

- Thread pool sized to CPU count (max 8)
- Binary search compression — typically 150 JPEGs in under 30s on M-series Mac
- Live stats: files/sec, MB saved, ETA

## Safety

- Never overwrites originals unless explicitly enabled + confirmed
- Warns before processing 500+ files
- Failed files don't stop the batch
- Cancel mid-batch supported

## v2 hooks (not built)

Watch folder, duplicate finder, watermark, Real-ESRGAN plugin, macOS menubar app, full CLI batch mode.
