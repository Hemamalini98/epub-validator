# EPUB Validator

A full-stack web application for validating, inspecting, and editing EPUB files. Upload a ZIP containing an EPUB and PDF, validate every XHTML chapter against configurable rules, edit source files directly in the browser, and export a corrected EPUB — all without leaving the app.

---

## Features

### Upload
- Drag-and-drop or browse a `.zip` file containing a matching `.epub` and `.pdf`
- Duplicate uploads are rejected automatically

### Dashboard
- All uploaded books persist server-side (`books.json`) and are visible to every user
- Click any book card to open its chapter list

### Validation
- **Validate all** chapters at once or run a single chapter on demand
- Status filter cards (Pending / Passed / Warnings / Failed) narrow the chapter grid instantly
- Elapsed-time counter shows how long a validation run is taking
- Validation results survive page refreshes within the session

### Validation Rules (configurable via `rules/rules.json`)

| ID | Name | What it checks |
|---|---|---|
| URL001 | Internal XHTML Links | Every `<a href="*.xhtml">` resolves to an existing file |
| URL002 | External URL Reachability | Every `<a class="url" href="https://…">` returns a 2xx response (HEAD → GET fallback, retry, 10-worker parallel checks) |
| URL003 | URL Text Match | Displayed link text matches the `href` attribute |
| NAV001 | NAV TOC Headings | Navigation TOC entry text matches the actual heading in the target chapter |
| CSS001 | CSS W3C Validation | Linked CSS files are validated against the W3C CSS Validator API |

### Detail Modal (per file — XHTML or CSS)

| Tab | Description |
|---|---|
| **Validation Result** | Filterable issue list (Error / Warning) with expected vs. actual diff blocks |
| **Preview** | Rendered XHTML with CSS inlined, images resolved, links disabled |
| **Source** | Editable source viewer with synced line numbers — edit and save directly in the browser |
| **PDF** | Book PDF opened at the page that matches the chapter heading (auto-detected) |

### Source Edit & Save
- The **Source** tab is fully editable — click into the code and start typing
- An orange dot (`●`) appears on the Source tab label when there are unsaved changes
- The **Save** button turns active and labelled `Save*` when edits are pending
- Saving writes the file back to disk immediately; the **Preview** tab regenerates on next open
- Closing the modal with unsaved changes shows a confirmation dialog: **Keep editing** or **Close anyway**
- `Ctrl+S` / `Cmd+S` can be used to save while the source editor is focused

### CSS Stylesheets
- A **CSS Stylesheets** section appears below the XHTML chapter grid whenever the EPUB contains `.css` files
- Each CSS card shows a violet `{}` icon and a **View Source** button
- Clicking opens the same Source tab — fully editable and saveable
- CSS files are excluded from the validation stat cards (Pending / Passed / Warnings / Failed) since those only track XHTML validation

### Export EPUB
- The **Export EPUB** button lives in the page header next to **Validate all**
- Before building the ZIP the frontend sends the current validation summary to the backend:
  - **Errors present** → blocked with a popup: *"There are validation errors. Please fix them before downloading."*
  - **Warnings or unvalidated files** → confirmation popup with **Cancel** and **Proceed**
  - **All passed** → downloads immediately with no prompt
- The exported EPUB is built from the live files on disk (`uploads/{folder}/extract/epub/`), so any source edits you saved are included automatically
- The `mimetype` entry is written first and stored uncompressed, satisfying the EPUB specification
- A green success banner confirms the download; the button shows a spinner while the ZIP is being built

### Multi-User Concurrency
- All long-running operations (validation, PDF rendering, export) run in a thread pool via `asyncio.to_thread`, keeping the event loop free to serve other users simultaneously
- External URL checks run in parallel (up to 10 concurrent per file) rather than sequentially
- `books.json` reads and writes are protected by a `threading.Lock` to prevent corruption during concurrent uploads
- Default thread pool is 20 workers; tune with the `THREAD_POOL_WORKERS` environment variable

---

## Tech Stack

### Backend
| Package | Role |
|---|---|
| FastAPI | REST API framework |
| Uvicorn | ASGI server |
| BeautifulSoup4 + lxml | XHTML / HTML parsing |
| PyMuPDF | PDF page detection and rendering |
| requests + urllib3 | External URL validation |
| python-multipart | File upload handling |

### Frontend
| Package | Role |
|---|---|
| React 18 + TypeScript | UI framework |
| Vite 5 | Dev server and bundler |
| Tailwind CSS | Styling |
| Framer Motion | Animations and transitions |
| @tanstack/react-query | Server state / data fetching |
| Axios | HTTP client |
| Lucide React | Icons |

---

## Project Structure

```
epub-validator/
├── backend/
│   ├── main.py                  # FastAPI app, lifespan thread-pool setup
│   ├── requirements.txt
│   ├── books.json               # Persisted book metadata (auto-created)
│   ├── uploads/                 # Uploaded ZIPs and extracted files (runtime)
│   ├── routes/
│   │   └── upload.py            # All API routes
│   ├── rules/
│   │   └── rules.json           # Validation rule definitions
│   └── services/
│       ├── upload_service.py    # ZIP extraction, book registration
│       ├── validate_service.py  # Validation logic + parallel URL checker
│       ├── books_service.py     # Thread-safe books.json read/write
│       └── pdf_service.py       # PDF page detection (PyMuPDF)
└── frontend/
    ├── vite.config.ts           # Dev server + API proxy rules
    └── src/
        ├── pages/
        │   ├── Dashboard.tsx    # Book grid
        │   ├── FilesPage.tsx    # Chapter + CSS file list, validation, export
        │   └── UploadPage.tsx   # Upload flow
        ├── components/
        │   ├── ValidationDetailModal.tsx  # Per-file detail modal (Result / Preview / Source / PDF)
        │   ├── XHTMLCard.tsx              # Chapter card (xhtml and css variants)
        │   ├── BookCard.tsx               # Book card
        │   ├── Toaster.tsx                # Toast notification system
        │   └── Sidebar.tsx
        ├── hooks/
        │   └── useBookStore.ts  # React Query wrapper for /books
        ├── lib/
        │   ├── api.ts           # Axios API calls
        │   └── utils.ts
        └── types/
            └── index.ts         # Shared TypeScript types
```

---

## Prerequisites

- Python 3.11+
- Node.js 18+

---

## Getting Started

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
python main.py
```

The API starts at `http://localhost:5002`.

**Production (multiple workers):**
```bash
WORKERS=4 python main.py
```
Setting `WORKERS` to more than `1` disables hot-reload and starts that many Uvicorn processes, each capable of handling requests in parallel.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

The app opens at `http://localhost:5173`. The Vite dev server proxies all API calls to the backend automatically.

---

## Docker setup 

### Build Containers

```bash
docker-compose up --build
```
### Start Application

```bash
docker-compose up
```
### Access Application

Frontend API

``` bash
http://localhost:5003
```
Backend API
``` bash
http://localhost:5002
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/upload` | Upload a ZIP file |
| `GET` | `/books` | List all uploaded books |
| `GET` | `/files/{folder}` | List all files in an uploaded book |
| `GET` | `/files/{folder}/{path}` | Serve any file from the extracted EPUB |
| `PUT` | `/files/{folder}/{path}` | Save edited content back to a file |
| `GET` | `/validate/{folder}` | Run all enabled rules (`?file=name.xhtml` for single file) |
| `POST` | `/export/{folder}` | Build and download an EPUB from the current files on disk |
| `GET` | `/pdf/{folder}` | Serve the book PDF |
| `GET` | `/pdf/{folder}/page?file=name.xhtml` | Detect the PDF page matching a chapter heading |
| `GET` | `/pdf/{folder}/render?page=N` | Render a PDF page to PNG |

All error responses use a consistent format:
```json
{ "status": false, "message": "..." }
```

### Export request body (`POST /export/{folder}`)

```json
{
  "failed": 2,
  "warnings": 1,
  "pending": 0,
  "force": false
}
```

- If `failed > 0` → HTTP 400 (blocked)
- If `warnings > 0` or `pending > 0` and `force` is `false` → returns `{ "status": "confirm", "message": "..." }`
- Otherwise → returns the `.epub` binary

---

## ZIP File Format

The uploaded ZIP must contain exactly:

```
your-book.zip
├── your-book.epub
└── your-book.pdf
```

The ZIP name, EPUB name, and PDF name must all share the same stem (e.g. `9798894105444_EPUB`).

---

## Validation Rules (`rules/rules.json`)

Rules are defined as JSON and loaded at runtime. Each rule maps to a Python function in `validate_service.py`:

```json
{
  "rules": [
    {
      "id": "URL001",
      "name": "Validate Internal XHTML Links",
      "enabled": true,
      "function": "validate_internal_xhtml_links",
      "target_path": "OEBPS/Text",
      "file_name_pattern": "*.xhtml"
    }
  ]
}
```

Set `"enabled": false` to disable a rule without removing it.

---

## Adding a New Validation Rule

**1.** Add a function to `backend/services/validate_service.py`:

```python
def validate_my_rule(file_details):
    issues = []
    # ... inspection logic using file_details["full_path"] ...
    issues.append({
        "type": "my_issue_type",
        "message": "Description of the problem",
        "category": "Error"   # or "Warning"
    })
    return {"issues_count": len(issues), "issues": issues}
```

**2.** Register it in `backend/rules/rules.json`:

```json
{
  "id": "MY001",
  "name": "My Custom Rule",
  "enabled": true,
  "function": "validate_my_rule",
  "target_path": "OEBPS/Text",
  "file_name_pattern": "*.xhtml"
}
```

The backend resolves the function by name at runtime — no router changes needed.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `WORKERS` | `1` | Number of Uvicorn worker processes (set > 1 for production; disables hot-reload) |
| `THREAD_POOL_WORKERS` | `20` | Size of the asyncio default thread pool per worker process |
