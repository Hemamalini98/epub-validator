import glob
import os
import pymupdf as fitz
from bs4 import BeautifulSoup


UPLOAD_DIR = "uploads"
EXTRACT_DIR = "extract"


def _check_chapter_cache(folder_name: str, xhtml_filename: str):
    """Look for a previously cut chapter PDF named ``{stem}_pg-{start}-{end}.pdf``.

    Returns ``(path, start, end)`` on hit, ``None`` on miss.
    """
    stem        = os.path.splitext(xhtml_filename)[0]
    extract_dir = os.path.join(UPLOAD_DIR, folder_name, EXTRACT_DIR)
    matches     = glob.glob(os.path.join(extract_dir, f"{stem}_pg-*-*.pdf"))
    if not matches:
        return None
    path  = matches[0]
    fname = os.path.basename(path)                      # 08_Contents_pg-42-45.pdf
    pg    = fname[len(stem) + 4:-4]                     # "42-45"
    parts = pg.split("-")
    if len(parts) == 2:
        try:
            return path, int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return None


def _find_xhtml_path(folder_name: str, xhtml_filename: str) -> str | None:
    epub_folder = os.path.join(UPLOAD_DIR, folder_name, EXTRACT_DIR, "epub")
    for root, _, files in os.walk(epub_folder):
        if xhtml_filename in files:
            return os.path.join(root, xhtml_filename)
    return None


def _extract_pagebreaks(xhtml_path: str) -> list[str]:
    """Return sorted list of page numbers from epub:type="pagebreak" spans."""
    with open(xhtml_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    pages = []
    for span in soup.find_all("span", {"epub:type": "pagebreak"}):
        if span.get("epub:type") == "pagebreak" or span.get("role") == "doc-pagebreak":
            label = span.get("aria-label") or span.get("id", "")
            # id may be "page_14" — strip prefix
            label = label.replace("page_", "").strip()
            try:
                pages.append(str(label))
            except ValueError:
                pass
    return pages

def _pdf_path(folder_name: str) -> str:
    return os.path.join(UPLOAD_DIR, folder_name, EXTRACT_DIR, f"{folder_name}.pdf")

def find_pdf_page(folder_name: str, xhtml_filename: str) -> dict:
    pdf_file = _pdf_path(folder_name)

    # ── Fast path: page range already encoded in cached filename ────────────
    cached = _check_chapter_cache(folder_name, xhtml_filename)
    if cached:
        _, start, end = cached
        total = len(fitz.open(pdf_file)) if os.path.exists(pdf_file) else end
        return {"page": start, "end_page": end, "total_pages": total}

    # ── Slow path: parse XHTML pagebreaks and scan PDF labels ───────────────
    total = 1
    if os.path.exists(pdf_file):
        doc = fitz.open(pdf_file)
        total = len(doc)

        xhtml_path = _find_xhtml_path(folder_name, xhtml_filename)
        if not xhtml_path:
            return {"page": 1, "end_page": 1, "total_pages": total}

        pages = _extract_pagebreaks(xhtml_path)


        start_page = None
        end_page = None

        if pages:

            for page in doc:

                label = page.get_label()

                if label == pages[0]:
                    start_page = page.number + 1

                if label == pages[-1]:
                    end_page = page.number + 1

            doc.close()

            if start_page is not None and end_page is not None:

                return {
                    "page": start_page,
                    "end_page": end_page,
                    "total_pages": total
                }

            return {
                "page": 1,
                "end_page": total,
                "total_pages": total
            }

        return {
                "page": 1,
                "end_page": total,
                "total_pages": total
            }


            

def get_chapter_pdf(folder_name: str, xhtml_filename: str) -> str:
    """Return path to a chapter-scoped PDF, cutting and caching on first call.

    Filename format: ``{stem}_pg-{start}-{end}.pdf``
    Cache check is a single glob — no XHTML read, no PDF label scan.
    """
    # ── Cache hit ────────────────────────────────────────────────────────────
    cached = _check_chapter_cache(folder_name, xhtml_filename)
    if cached:
        return cached[0]

    # ── Resolve page range (slow path, runs only once per chapter) ───────────
    full_pdf = _pdf_path(folder_name)
    if not os.path.exists(full_pdf):
        raise FileNotFoundError("Full PDF not found")

    info  = find_pdf_page(folder_name, xhtml_filename)
    start = info["page"]
    end   = info["end_page"]

    # Full-book chapter — serve original PDF, save a zero-byte marker so the
    # cache check succeeds on the next call without re-running detection.
    stem        = os.path.splitext(xhtml_filename)[0]
    extract_dir = os.path.join(UPLOAD_DIR, folder_name, EXTRACT_DIR)
    if start == 1 and end == info["total_pages"]:
        marker = os.path.join(extract_dir, f"{stem}_pg-{start}-{end}.pdf")
        open(marker, "wb").close()          # zero-byte marker
        return full_pdf

    # ── Cut and save ─────────────────────────────────────────────────────────
    chapter_pdf_path = os.path.join(extract_dir, f"{stem}_pg-{start}-{end}.pdf")
    src = fitz.open(full_pdf)
    out = fitz.open()
    out.insert_pdf(src, from_page=start - 1, to_page=end - 1)
    out.save(chapter_pdf_path)
    out.close()
    src.close()

    return chapter_pdf_path


def render_pdf_page(folder_name: str, page: int) -> bytes:
    """Render a single PDF page to PNG bytes at 2× resolution."""
    pdf_file = _pdf_path(folder_name)
    if not os.path.exists(pdf_file):
        raise FileNotFoundError("PDF not found")

    doc = fitz.open(pdf_file)
    if page < 1 or page > len(doc):
        page = 1

    pix = doc[page - 1].get_pixmap(matrix=fitz.Matrix(2, 2))
    data = pix.tobytes("png")
    doc.close()
    return data
