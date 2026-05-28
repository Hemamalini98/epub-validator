import os
import pymupdf as fitz
from bs4 import BeautifulSoup

UPLOAD_DIR = "uploads"
EXTRACT_DIR = "extract"


def _find_xhtml_path(folder_name: str, xhtml_filename: str) -> str | None:
    epub_folder = os.path.join(UPLOAD_DIR, folder_name, EXTRACT_DIR, "epub")
    for root, _, files in os.walk(epub_folder):
        if xhtml_filename in files:
            return os.path.join(root, xhtml_filename)
    return None


def _extract_first_pagebreak_label(xhtml_path: str) -> str | None:
    """Return the printed page label of the first epub pagebreak marker in
    the XHTML, or None if there is no marker."""
    with open(xhtml_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    candidates = soup.find_all(attrs={"role": "doc-pagebreak"})
    if not candidates:
        # Fallback: any element with epub:type containing "pagebreak"
        candidates = [
            el for el in soup.find_all(True)
            if "pagebreak" in (el.get("epub:type") or "").lower()
        ]

    for el in candidates:
        label = el.get("title") or el.get("aria-label")
        if label:
            return str(label).strip()
    return None


def _extract_heading(xhtml_path: str) -> str | None:

    with open(xhtml_path, "r", encoding="utf-8") as f:

        soup = BeautifulSoup(
            f.read(),
            "html.parser"
        )

    for tag in ["h1", "h2", "h3", "h4"]:

        el = soup.find(tag)

        if el:

            text = el.get_text()

            if text:
                return text

    return None


def _pdf_path(folder_name: str) -> str:
    return os.path.join(UPLOAD_DIR, folder_name, EXTRACT_DIR, f"{folder_name}.pdf")


# def find_pdf_page(folder_name: str, xhtml_filename: str) -> dict:
#     """Return {page, total_pages} for the PDF page matching the XHTML chapter."""
#     pdf_file = _pdf_path(folder_name)
#     if not os.path.exists(pdf_file):
#         return {"page": 1, "total_pages": 1}

#     doc = fitz.open(pdf_file)
#     total = len(doc)

#     xhtml_path = _find_xhtml_path(folder_name, xhtml_filename)
#     if not xhtml_path:
#         doc.close()
#         return {"page": 1, "total_pages": total}

#     heading = _extract_heading(xhtml_path)
#     if not heading:
#         doc.close()
#         return {"page": 1, "total_pages": total}

#     heading_norm = " ".join(heading.lower().split())
#     heading_words = [w for w in heading_norm.split() if len(w) > 2]

#     best_page = 1
#     best_score = 0.0

#     for i in range(total):
#         page_text = " ".join(doc[i].get_text("text").lower().split())

#         # Exact match — done
#         if heading_norm in page_text:
#             doc.close()
#             return {"page": i + 1, "total_pages": total}

#         # Word-overlap score
#         if heading_words:
#             score = sum(1 for w in heading_words if w in page_text) / len(heading_words)
#             if score > best_score:
#                 best_score = score
#                 best_page = i + 1

#     doc.close()
#     return {"page": best_page, "total_pages": total}




import os
import re
# import fitz


def normalize_pdf_text(text):

    text = re.sub(
        r"[\x00-\x1F\x7F]",
        "",
        text
    )

    text = " ".join(
        text.split()
    )

    # remove roman numerals at beginning
    text = re.sub(
        r"^[ivxlcdm]+\s+",
        "",
        text,
        flags=re.IGNORECASE
    )

    return text.strip().lower()


def find_pdf_page(folder_name: str, xhtml_filename: str) -> dict:

    pdf_file = _pdf_path(folder_name)

    if not os.path.exists(pdf_file):

        return {
            "page": 1,
            "total_pages": 1
        }

    doc = fitz.open(pdf_file)

    total = len(doc)

    xhtml_path = _find_xhtml_path(
        folder_name,
        xhtml_filename
    )

    if not xhtml_path:

        doc.close()

        return {
            "page": 1,
            "total_pages": total
        }

    # Prefer EPUB pagebreak markers → PDF page labels. Falls back to heading
    # text matching when the XHTML has no marker or the label is not in the PDF.
    label = _extract_first_pagebreak_label(xhtml_path)
    if label:
        try:
            indices = doc.get_page_numbers(label)
        except Exception:
            indices = []
        if indices:
            page_num = indices[0] + 1
            doc.close()
            return {"page": page_num, "total_pages": total}

    heading = _extract_heading(xhtml_path)

    if not heading:

        doc.close()

        return {
            "page": 1,
            "total_pages": total
        }

    heading_norm = normalize_pdf_text(
        heading
    )

    heading_words = [
        w
        for w in heading_norm.split()
        if len(w) > 2
    ]

    best_page = 1
    best_score = 0.0

    # =====================================
    # LOOP PDF PAGES
    # =====================================

    for i in range(total):

        page = doc[i]

        blocks = page.get_text(
            "blocks"
        )

        # =====================================
        # CHECK TOP BLOCKS FIRST
        # =====================================

        for block in blocks[:2]:

            block_text = normalize_pdf_text(
                block[4]
            )

            # exact heading block match
            if heading_norm == block_text:

                doc.close()

                return {
                    "page": i + 1,
                    "total_pages": total
                }

            # heading inside block
            if heading_norm in block_text:

                doc.close()

                return {
                    "page": i + 1,
                    "total_pages": total
                }

        # =====================================
        # FALLBACK FULL PAGE SEARCH
        # =====================================

        page_text = normalize_pdf_text(
            page.get_text("text")
        )

        # skip TOC pages for normal chapters
        if (
            "contents" not in heading_norm
            and "table of contents" not in heading_norm
        ):

            if (
                "table of contents" in page_text
                or "contents" in page_text
            ):
                continue

        # =====================================
        # WORD SCORE
        # =====================================

        if heading_words:

            score = sum(
                1
                for w in heading_words
                if w in page_text
            ) / len(heading_words)

            if score > best_score:

                best_score = score
                best_page = i + 1

    doc.close()

    return {
        "page": best_page,
        "total_pages": total
    }

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
