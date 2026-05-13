# EPUB Validator

A full-stack web application for validating EPUB files. Upload a ZIP containing an EPUB and PDF, inspect every XHTML chapter, run configurable validation rules, and preview the rendered content side-by-side with the source PDF.

---

## Features

- **Upload** — Drag-and-drop or browse a `.zip` file containing an `.epub` and matching `.pdf`
- **Dashboard** — All uploaded books are persisted server-side (`books.json`) and visible to every user
- **Per-file validation** — Validate a single chapter or all chapters at once
- **Validation rules** (configurable via `rules/rules.json`):
  - **URL001** — Internal XHTML link checker (missing file references)
  - **URL002** — External URL reachability checker (HTTP HEAD/GET with retry)
  - **URL003** — URL text vs. href mismatch detector
  - **NAV001** — Navigation TOC heading text matcher
- **Detail modal** with four tabs per chapter:
  - **Validation Result** — Filterable issue list (Error / Warning) with expected vs. actual diff blocks
  - **Preview** — Rendered XHTML with CSS inlined, images resolved, links disabled
  - **Source** — Line-numbered raw XHTML viewer
  - **PDF** — Book PDF opened at the page that matches the chapter heading (detected automatically)
- **Status filter cards** — Click Pending / Passed / Warnings / Failed to filter the chapter grid
- **Toast notifications** — Upload errors appear as auto-dismissing notifications

---

## Tech Stack

### Backend
| Package | Role |
|---|---|
| FastAPI | REST API framework |
| Uvicorn | ASGI server |
| BeautifulSoup4 + lxml | XHTML parsing |
| PyMuPDF | PDF page detection and rendering |
| requests + urllib3 | External URL validation |
| python-multipart | File upload handling |

### Frontend
| Package | Role |
|---|---|
| React 18 + TypeScript | UI framework |
| Vite 5 | Dev server and bundler |
| Tailwind CSS | Styling |
| Framer Motion | Animations |
| @tanstack/react-query | Server state / data fetching |
| Axios | HTTP client |
| Lucide React | Icons |

---

## Project Structure

```
epubValidator/
├── backend/
│   ├── main.py                  # FastAPI app, global exception handler
│   ├── requirements.txt
│   ├── books.json               # Persisted book metadata (auto-created)
│   ├── uploads/                 # Uploaded ZIPs and extracted files
│   ├── routes/
│   │   └── upload.py            # All API routes
│   ├── rules/
│   │   └── rules.json           # Validation rule definitions
│   └── services/
│       ├── upload_service.py    # ZIP extraction, book registration
│       ├── validate_service.py  # Validation logic
│       ├── books_service.py     # books.json read/write
│       └── pdf_service.py       # PDF page detection (PyMuPDF)
└── frontend/
    ├── vite.config.ts
    └── src/
        ├── pages/
        │   ├── Dashboard.tsx    # Book grid
        │   ├── FilesPage.tsx    # Chapter list + validation
        │   └── UploadPage.tsx   # Upload flow
        ├── components/
        │   ├── ValidationDetailModal.tsx  # Per-file detail modal
        │   ├── XHTMLCard.tsx              # Chapter card
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

The API starts at `http://localhost:8000`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

The app opens at `http://localhost:5173`. The Vite dev server proxies all API calls to the backend.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/upload` | Upload a ZIP file |
| `GET` | `/books` | List all uploaded books |
| `GET` | `/files/{folder}` | List XHTML files in an uploaded book |
| `GET` | `/files/{folder}/{path}` | Serve any file from the extracted EPUB |
| `GET` | `/validate/{folder}` | Run all validation rules (optionally `?file=name.xhtml`) |
| `GET` | `/pdf/{folder}` | Serve the book PDF |
| `GET` | `/pdf/{folder}/page?file=name.xhtml` | Detect the PDF page matching a chapter |
| `GET` | `/pdf/{folder}/render?page=N` | Render a PDF page to PNG |

All error responses use a consistent format:
```json
{ "status": false, "message": "..." }
```

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

Rules are defined as JSON and loaded at runtime. Each rule specifies which function to call and which files to target:

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

To disable a rule without deleting it, set `"enabled": false`.

---

## Adding a New Validation Rule

1. Add a function to `backend/services/validate_service.py`:

```python
def validate_my_rule(file_details):
    issues = []
    # ... inspection logic ...
    issues.append({
        "type": "my_issue_type",
        "message": "Description of the problem",
        "category": "Error"   # or "Warning"
    })
    return {"issues_count": len(issues), "issues": issues}
```

2. Register it in `backend/rules/rules.json`:

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

The backend picks up the function by name dynamically — no other changes needed.
