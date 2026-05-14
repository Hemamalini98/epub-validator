"""PDF extraction: paragraphs, fonts (italic flag), colors, page boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

try:
    import fitz  # PyMuPDF
    _HAVE_FITZ = True
except ImportError:  # pragma: no cover
    _HAVE_FITZ = False


@dataclass
class PdfSpan:
    text: str
    font: str
    size: float
    flags: int     # bit2=italic, bit4=bold, bit0=superscript (PyMuPDF)
    color: int     # rgb int
    bbox: Tuple[float, float, float, float]


@dataclass
class PdfLine:
    text: str
    spans: List[PdfSpan]
    bbox: Tuple[float, float, float, float]


@dataclass
class PdfParagraph:
    text: str
    page: int
    bbox: Tuple[float, float, float, float]
    italic_words: Set[str] = field(default_factory=set)
    bold_words: Set[str] = field(default_factory=set)
    colors: Set[int] = field(default_factory=set)
    alignment: str = "left"           # left/center/right/justify (heuristic)
    has_hanging_indent: bool = False  # heuristic


@dataclass
class PdfPage:
    page_number: int     # 1-based physical page index
    label: Optional[str] # logical page label if available (e.g., "iii", "5")
    width: float
    height: float
    paragraphs: List[PdfParagraph] = field(default_factory=list)


@dataclass
class PdfDoc:
    path: str
    page_count: int
    pages: List[PdfPage]
    paragraphs: List[PdfParagraph]
    italic_words_global: Set[str] = field(default_factory=set)
    bold_words_global: Set[str] = field(default_factory=set)
    plain_words_global: Set[str] = field(default_factory=set)  # words seen in plain (non-italic) runs
    colors_global: Set[int] = field(default_factory=set)
    max_logical_page: Optional[str] = None

    def always_italic_words(self) -> Set[str]:
        """Words italic in PDF that never appear in a plain (non-italic) run."""
        return self.italic_words_global - self.plain_words_global


# PyMuPDF span flag bits.
_FLAG_ITALIC = 1 << 1   # 2
_FLAG_BOLD = 1 << 4     # 16
_FLAG_SERIF = 1 << 2    # 4 (not used)


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']{2,}")


class PdfParser:
    """Extract structured text + style cues from a PDF."""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path

    def parse(self, max_pages: Optional[int] = None) -> PdfDoc:
        if not _HAVE_FITZ:
            raise RuntimeError("PyMuPDF (fitz) is required. pip install PyMuPDF")

        doc = fitz.open(self.pdf_path)
        pages: List[PdfPage] = []
        all_paras: List[PdfParagraph] = []
        global_italic: Set[str] = set()
        global_bold: Set[str] = set()
        global_plain: Set[str] = set()
        global_colors: Set[int] = set()
        page_labels = self._page_labels(doc)
        max_label: Optional[str] = None

        n = doc.page_count if max_pages is None else min(doc.page_count, max_pages)
        for pno in range(n):
            page = doc.load_page(pno)
            label = page_labels.get(pno)
            p = self._parse_page(page, pno + 1, label)
            pages.append(p)
            all_paras.extend(p.paragraphs)
            for para in p.paragraphs:
                global_italic.update(para.italic_words)
                global_bold.update(para.bold_words)
                global_colors.update(para.colors)
                # also collect plain (non-italic) words to refute false italics
                for w in _WORD_RE.findall(para.text):
                    wl = w.lower()
                    if wl not in para.italic_words:
                        global_plain.add(wl)
            if label and label.isdigit():
                if max_label is None or int(label) > int(max_label):
                    max_label = label

        doc.close()

        return PdfDoc(
            path=self.pdf_path,
            page_count=n,
            pages=pages,
            paragraphs=all_paras,
            italic_words_global=global_italic,
            bold_words_global=global_bold,
            plain_words_global=global_plain,
            colors_global=global_colors,
            max_logical_page=max_label,
        )

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #
    def _page_labels(self, doc) -> Dict[int, str]:  # type: ignore[no-untyped-def]
        """Best-effort: return {page_index_0based: logical label}. Empty if absent."""
        try:
            labels = doc.get_page_labels()  # PyMuPDF >=1.21
        except Exception:
            labels = []
        out: Dict[int, str] = {}
        if not labels:
            # Fall back: try to render label per page (slower but reliable).
            for i in range(doc.page_count):
                try:
                    lab = doc.load_page(i).get_label()
                    if lab:
                        out[i] = lab
                except Exception:
                    continue
            return out
        # labels is a list of dicts: [{startpage,style,prefix,firstpagenum},...]
        for i in range(doc.page_count):
            for spec in labels:
                start = spec.get("startpage", 0)
                if i >= start:
                    label = self._compose_label(spec, i - start)
                    out[i] = label
        return out

    @staticmethod
    def _compose_label(spec: Dict, offset: int) -> str:
        first = spec.get("firstpagenum", 1)
        prefix = spec.get("prefix", "") or ""
        style = (spec.get("style") or "D").upper()
        n = first + offset
        if style == "D":
            return f"{prefix}{n}"
        if style == "R":
            return f"{prefix}{_to_roman(n).upper()}"
        if style == "r":
            return f"{prefix}{_to_roman(n).lower()}"
        return f"{prefix}{n}"

    def _parse_page(self, page, pno: int, label: Optional[str]) -> PdfPage:  # type: ignore[no-untyped-def]
        rect = page.rect
        width, height = rect.width, rect.height
        out = PdfPage(page_number=pno, label=label, width=width, height=height)

        d = page.get_text("dict")
        blocks = d.get("blocks", [])
        for blk in blocks:
            if blk.get("type") != 0:  # skip images
                continue
            lines: List[PdfLine] = []
            for ln in blk.get("lines", []):
                spans: List[PdfSpan] = []
                for sp in ln.get("spans", []):
                    spans.append(PdfSpan(
                        text=sp.get("text", ""),
                        font=sp.get("font", ""),
                        size=float(sp.get("size", 0.0)),
                        flags=int(sp.get("flags", 0)),
                        color=int(sp.get("color", 0)),
                        bbox=tuple(sp.get("bbox", (0, 0, 0, 0))),
                    ))
                if not spans:
                    continue
                line_text = "".join(s.text for s in spans)
                lines.append(PdfLine(
                    text=line_text,
                    spans=spans,
                    bbox=tuple(ln.get("bbox", (0, 0, 0, 0))),
                ))
            if not lines:
                continue

            # Merge consecutive lines into a paragraph (PyMuPDF blocks ~ paragraphs).
            text = " ".join(l.text for l in lines).strip()
            text = re.sub(r"\s+", " ", text)
            if not text:
                continue

            italic_words: Set[str] = set()
            bold_words: Set[str] = set()
            colors: Set[int] = set()
            for ln in lines:
                for sp in ln.spans:
                    if sp.color != 0:
                        colors.add(sp.color)
                    # Identify italic and bold from flags or font name.
                    italic = bool(sp.flags & _FLAG_ITALIC) or "italic" in sp.font.lower() or "oblique" in sp.font.lower()
                    bold = bool(sp.flags & _FLAG_BOLD) or "bold" in sp.font.lower()
                    if italic or bold:
                        for w in _WORD_RE.findall(sp.text):
                            if italic:
                                italic_words.add(w.lower())
                            if bold:
                                bold_words.add(w.lower())

            alignment = self._infer_alignment(lines, width)
            hanging = self._infer_hanging_indent(lines)

            bbox = tuple(blk.get("bbox", (0, 0, 0, 0)))
            out.paragraphs.append(PdfParagraph(
                text=text,
                page=pno,
                bbox=bbox,
                italic_words=italic_words,
                bold_words=bold_words,
                colors=colors,
                alignment=alignment,
                has_hanging_indent=hanging,
            ))
        return out

    @staticmethod
    def _infer_alignment(lines: List[PdfLine], page_width: float) -> str:
        if not lines:
            return "left"
        lefts = [l.bbox[0] for l in lines]
        rights = [l.bbox[2] for l in lines]
        left_margin = min(lefts)
        right_margin = max(rights)
        block_width = right_margin - left_margin
        page_centre = page_width / 2.0
        block_centre = (left_margin + right_margin) / 2.0

        # Centered: block centre near page centre, narrow block
        if abs(block_centre - page_centre) < 30 and block_width < page_width * 0.7:
            return "center"
        # Right aligned: rights consistent, lefts vary
        if max(rights) - min(rights) < 5 and max(lefts) - min(lefts) > 30:
            return "right"
        # Justify: most lines reach near right margin (within 10pt) — multi-line only
        if len(lines) >= 2:
            justified = sum(1 for r in rights if right_margin - r < 10)
            if justified >= len(lines) - 1:
                return "justify"
        return "left"

    @staticmethod
    def _infer_hanging_indent(lines: List[PdfLine]) -> bool:
        if len(lines) < 2:
            return False
        first_left = lines[0].bbox[0]
        rest_lefts = [l.bbox[0] for l in lines[1:]]
        # hanging: first line indented LESS than subsequent lines (i.e. continuation lines indented more)
        # OR first line begins farther left and continuations are flush further right by >5pt
        avg_rest = sum(rest_lefts) / len(rest_lefts)
        return (avg_rest - first_left) > 8


def _to_roman(n: int) -> str:
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
            (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = ""
    for v, sym in vals:
        while n >= v:
            out += sym
            n -= v
    return out
