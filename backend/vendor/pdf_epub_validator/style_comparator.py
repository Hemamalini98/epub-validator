"""Style-level comparison between EPUB XHTML and PDF text.

Each check produces zero or more Issue records describing FAIL / PARTIAL findings.
Checks are intentionally heuristic — they aim for high-signal flags an
editor can act on, not pixel-perfect equivalence."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set, Tuple

from PIL import Image

from .epub_extractor import EpubBundle, XhtmlDoc, CssRule, line_number_of, clean_inline_text
from .pdf_parser import PdfDoc, PdfParagraph
from .report_generator import Issue, Status


# ---------------------------------------------------------------------- #
# CSS helpers                                                            #
# ---------------------------------------------------------------------- #


def build_class_styles(css_rules: List[CssRule]) -> Dict[str, Dict[str, str]]:
    """Flatten CSS rules into {class_name: merged declarations}."""
    out: Dict[str, Dict[str, str]] = defaultdict(dict)
    for r in css_rules:
        m = re.findall(r"\.([A-Za-z_][\w\-]*)", r.selector)
        if not m:
            continue
        for cls in m:
            for k, v in r.declarations.items():
                out[cls][k] = v
    return out


def merge_props(classes: Iterable[str], styles: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    """Compose effective declarations for an element with given class list."""
    merged: Dict[str, str] = {}
    for cls in classes:
        merged.update(styles.get(cls, {}))
    return merged


# Common stopwords we never flag for italic/case checks.
_STOPWORDS = {
    "the", "and", "but", "for", "with", "from", "this", "that", "these", "those",
    "into", "onto", "over", "under", "after", "before", "between", "during",
    "of", "in", "on", "at", "to", "by", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "not", "no", "so", "or", "if", "then",
}


def _words(text: str) -> List[str]:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z\-']{2,}", text)]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


# ---------------------------------------------------------------------- #
# StyleComparator                                                        #
# ---------------------------------------------------------------------- #


class StyleComparator:
    """Run every style-related check and return Issues."""

    def __init__(self, epub: EpubBundle, pdf: PdfDoc):
        self.epub = epub
        self.pdf = pdf
        self.class_styles = build_class_styles(epub.css_rules)

        # Index PDF paragraphs by a normalised lookup key (first ~80 chars).
        self._pdf_by_key: Dict[str, PdfParagraph] = {}
        for p in pdf.paragraphs:
            key = _normalize(p.text)[:80]
            if key:
                self._pdf_by_key.setdefault(key, p)

        # Index of italic words globally for fast lookup. Only words that are
        # *always* italic in PDF — otherwise we'd flag every appearance of
        # common words like "case" that happen to be italic in a citation.
        self._pdf_italics = set(pdf.always_italic_words())

    # ------------------------------------------------------------------ #
    # Master entrypoint                                                  #
    # ------------------------------------------------------------------ #
    def run_all(self) -> List[Issue]:
        issues: List[Issue] = []
        issues += self.check_para_splitting()
        issues += self.check_italic_missing()
        issues += self.check_alignment()
        issues += self.check_hanging_indent()
        issues += self.check_pagebreak_markers()
        issues += self.check_incorrect_case()
        issues += self.check_additional_indentation()
        issues += self.check_line_space()
        issues += self.check_additional_blockquote()
        issues += self.check_cover_image()
        issues += self.check_body_images()
        issues += self.check_color_missing()
        issues += self.check_max_page()
        return issues

    # ------------------------------------------------------------------ #
    # 1. Para splitting                                                  #
    # ------------------------------------------------------------------ #
    def check_para_splitting(self) -> List[Issue]:
        """A <p> that ends mid-clause and is followed by a <p> that continues
        in lowercase is the signature of a wrongly-split paragraph.

        We require the previous paragraph to end without any terminal
        punctuation (including commas, colons, semicolons — those legitimately
        end an item in a list) and to be a substantive length, so address
        blocks and list items don't trip the rule."""
        out: List[Issue] = []
        # A para that ends "properly" — sentence terminator, list-item comma,
        # colon (intro to following block), semicolon, dash, etc.
        proper_end = re.compile(r"[\.\!\?\"\'\)\]:;,—–-]\s*$")
        flagged = 0
        for doc in self._content_docs():
            ps = doc.soup.find_all("p")
            for i in range(len(ps) - 1):
                a, b = ps[i], ps[i + 1]
                ta = clean_inline_text(a)
                tb = clean_inline_text(b)
                if not ta or not tb or len(ta) < 200:
                    continue
                if a.find(["h1", "h2", "h3", "h4", "h5", "h6"]):
                    continue
                if proper_end.search(ta):
                    continue
                first = tb.lstrip(" \"'“‘")
                if not first or not first[0].islower():
                    continue
                # Skip if next paragraph is itself a list item — "(i)", "(iv)",
                # "(bb)", "(a)" — which are valid as standalone paragraphs.
                if re.match(r"^\(\s*[ivxlcdm]+\s*\)|^\([a-z]{1,2}\)|^\(\s*\d+\s*\)", first, re.I):
                    continue
                # Skip common conjunction openings that just look like splits.
                if re.match(r"^(see|e\.g|i\.e|cf\.|but\b|and\b|or\b|whereas\b)", first, re.I):
                    continue
                snippet = ta[-60:] + " ⏎ " + tb[:60]
                out.append(Issue(
                    name="Para Splitting",
                    status=Status.FAIL,
                    file_path=doc.rel_path,
                    line_number=line_number_of(doc, ta[-40:]),
                    snippet=snippet,
                    detail="Paragraph appears split: previous <p> ends mid-clause and next <p> starts lowercase.",
                    category="Para Splitting",
                ))
                flagged += 1
                if flagged >= 30:
                    out.append(Issue(name="Para Splitting", status=Status.PARTIAL,
                                     detail="Stopped after 30 findings.",
                                     category="Para Splitting"))
                    return out
        if not out:
            out.append(Issue(name="Para Splitting", status=Status.PASS,
                             detail="No suspicious paragraph splits detected.",
                             category="Para Splitting"))
        return out

    # ------------------------------------------------------------------ #
    # 2. Italic missing                                                  #
    # ------------------------------------------------------------------ #
    def check_italic_missing(self) -> List[Issue]:
        """If PDF marks a word italic but the same word in EPUB is not inside
        <i>/<em>/italic-class, flag it."""
        out: List[Issue] = []
        if not self._pdf_italics:
            return [Issue(name="Italic Missing", status=Status.SKIP,
                          detail="No italic spans detected in PDF.",
                          category="Italic Missing")]

        italic_classes = {
            cls for cls, decls in self.class_styles.items()
            if (decls.get("font-style") or "").lower() == "italic"
        }
        hidden_classes = {
            cls for cls, decls in self.class_styles.items()
            if (decls.get("display") or "").lower() == "none"
            or (decls.get("visibility") or "").lower() == "hidden"
        }

        # Cap candidate set so we don't drown the report. Require ≥4 letters
        # and not a stopword.
        candidates = [w for w in self._pdf_italics if w not in _STOPWORDS and len(w) >= 4]
        candidates = sorted(set(candidates))[:200]
        word_res = {w: re.compile(rf"(?<![A-Za-z\-]){re.escape(w)}(?![A-Za-z\-])") for w in candidates}

        flagged = 0
        for doc in self._content_docs():
            text_all = self._visible_text(doc, hidden_classes).lower()
            italic_text_lower = self._collect_italic_text(doc, italic_classes).lower()
            for w in candidates:
                # Whole-word match, not substring (avoid "bolling" matching
                # "Bollinger" in the EPUB text).
                if not word_res[w].search(text_all):
                    continue
                if word_res[w].search(italic_text_lower):
                    continue
                # Word appears in EPUB but not inside any italic context.
                snippet = self._context_snippet(doc, w)
                out.append(Issue(
                    name="Italic Missing",
                    status=Status.FAIL,
                    file_path=doc.rel_path,
                    snippet=snippet,
                    detail=f"Word '{w}' is italic in PDF but not wrapped in <i>/<em> in EPUB.",
                    category="Italic Missing",
                ))
                flagged += 1
                if flagged >= 50:  # report cap
                    out.append(Issue(name="Italic Missing", status=Status.PARTIAL,
                                     detail=f"Stopped after 50 findings; more may exist.",
                                     category="Italic Missing"))
                    return out
        if flagged == 0:
            out.append(Issue(name="Italic Missing", status=Status.PASS,
                             detail="All sampled PDF-italic words are italicised in EPUB.",
                             category="Italic Missing"))
        return out

    def _visible_text(self, doc: XhtmlDoc, hidden_classes: Set[str]) -> str:
        """Return the chapter text excluding subtrees hidden via display:none
        / visibility:hidden (CSS class or inline style). Accessibility alt-text
        in <div class="hidden"> blocks shouldn't seed style-parity findings."""
        from bs4 import NavigableString, Tag

        def is_hidden(tag: Tag) -> bool:
            cl = tag.get("class") or []
            if isinstance(cl, str):
                cl = cl.split()
            if hidden_classes and any(c in hidden_classes for c in cl):
                return True
            style = (tag.get("style") or "").lower().replace(" ", "")
            return "display:none" in style or "visibility:hidden" in style

        parts: List[str] = []

        def walk(node):
            if isinstance(node, NavigableString):
                s = str(node).strip()
                if s:
                    parts.append(s)
                return
            if isinstance(node, Tag):
                if is_hidden(node):
                    return
                for child in node.children:
                    walk(child)

        walk(doc.soup)
        return " ".join(parts)

    def _collect_italic_text(self, doc: XhtmlDoc, italic_classes: Set[str]) -> str:
        parts: List[str] = []
        for tag in doc.soup.find_all(["i", "em"]):
            parts.append(tag.get_text(" ", strip=True))
        if italic_classes:
            for tag in doc.soup.find_all(True):
                cl = tag.get("class") or []
                if isinstance(cl, str):
                    cl = cl.split()
                if any(c in italic_classes for c in cl):
                    parts.append(tag.get_text(" ", strip=True))
        # Inline style
        for tag in doc.soup.find_all(style=True):
            if "italic" in (tag.get("style") or "").lower():
                parts.append(tag.get_text(" ", strip=True))
        return " ".join(parts)

    def _context_snippet(self, doc: XhtmlDoc, word: str) -> str:
        for p in doc.soup.find_all(["p", "li", "h1", "h2", "h3"]):
            t = p.get_text(" ", strip=True)
            if word in t.lower():
                idx = t.lower().find(word)
                lo = max(0, idx - 30)
                hi = min(len(t), idx + len(word) + 30)
                return "…" + t[lo:hi] + "…"
        return ""

    # ------------------------------------------------------------------ #
    # 3. Incorrect alignment                                             #
    # ------------------------------------------------------------------ #
    def check_alignment(self) -> List[Issue]:
        out: List[Issue] = []
        flagged = 0
        for doc in self._content_docs():
            for p in doc.soup.find_all("p"):
                text = clean_inline_text(p)
                if len(text) < 40:
                    continue
                epub_align = self._effective_alignment(p)
                pdf_para = self._match_pdf_para(text)
                if not pdf_para:
                    continue
                pdf_align = pdf_para.alignment
                if pdf_align == epub_align:
                    continue
                # Treat justify <-> left as same in flowing prose (reflowable EPUB).
                if {pdf_align, epub_align} <= {"left", "justify"}:
                    continue
                out.append(Issue(
                    name="Incorrect Alignment",
                    status=Status.FAIL,
                    file_path=doc.rel_path,
                    line_number=line_number_of(doc, text[:40]),
                    snippet=text[:120],
                    detail=f"PDF alignment '{pdf_align}', EPUB alignment '{epub_align}'.",
                    pdf_context=f"page {pdf_para.page}",
                    category="Incorrect Alignment",
                ))
                flagged += 1
                if flagged >= 30:
                    out.append(Issue(name="Incorrect Alignment", status=Status.PARTIAL,
                                     detail="Stopped after 30 findings.",
                                     category="Incorrect Alignment"))
                    return out
        if flagged == 0:
            out.append(Issue(name="Incorrect Alignment", status=Status.PASS,
                             detail="No alignment mismatches detected on matched paragraphs.",
                             category="Incorrect Alignment"))
        return out

    def _effective_alignment(self, tag) -> str:
        """Resolve text-align for a tag via class + inline style."""
        # inline style first
        style = (tag.get("style") or "")
        m = re.search(r"text-align\s*:\s*([a-z]+)", style, re.I)
        if m:
            return m.group(1).lower()
        for cls in (tag.get("class") or []):
            decls = self.class_styles.get(cls) or {}
            if "text-align" in decls:
                return decls["text-align"].lower()
        return "left"  # CSS default

    # ------------------------------------------------------------------ #
    # 4. Hanging indent                                                  #
    # ------------------------------------------------------------------ #
    def check_hanging_indent(self) -> List[Issue]:
        """Find PDF paragraphs with hanging indent that look flush-left in EPUB."""
        out: List[Issue] = []
        flagged = 0

        # Determine which CSS classes provide a hanging indent.
        hanging_classes = self._classes_with_hanging()

        for doc in self._content_docs():
            for p in doc.soup.find_all("p"):
                text = clean_inline_text(p)
                if len(text) < 40:
                    continue
                pdf_para = self._match_pdf_para(text)
                if not pdf_para or not pdf_para.has_hanging_indent:
                    continue
                cls = set(p.get("class") or [])
                if cls & hanging_classes:
                    continue
                # inline style check
                style = (p.get("style") or "")
                if "text-indent" in style and "-" in style:
                    continue
                out.append(Issue(
                    name="Hanging Alignment Missing",
                    status=Status.FAIL,
                    file_path=doc.rel_path,
                    line_number=line_number_of(doc, text[:40]),
                    snippet=text[:120],
                    detail="PDF has hanging indent; EPUB paragraph has no hanging-indent style.",
                    pdf_context=f"page {pdf_para.page}",
                    category="Hanging Alignment Missing",
                ))
                flagged += 1
                if flagged >= 30:
                    out.append(Issue(name="Hanging Alignment Missing", status=Status.PARTIAL,
                                     detail="Stopped after 30 findings.",
                                     category="Hanging Alignment Missing"))
                    return out
        if flagged == 0:
            out.append(Issue(name="Hanging Alignment Missing", status=Status.PASS,
                             detail="No missing hanging indents detected.",
                             category="Hanging Alignment Missing"))
        return out

    def _classes_with_hanging(self) -> Set[str]:
        hanging: Set[str] = set()
        for cls, decls in self.class_styles.items():
            ti = decls.get("text-indent", "")
            ml = decls.get("margin-left", "")
            pl = decls.get("padding-left", "")
            if ti.startswith("-"):
                hanging.add(cls)
            elif (ml or pl) and ti and not ti.startswith("0"):
                # positive margin + non-zero text-indent — likely hanging combo
                hanging.add(cls)
        return hanging

    # ------------------------------------------------------------------ #
    # 5. Page-break markers                                              #
    # ------------------------------------------------------------------ #
    def check_pagebreak_markers(self) -> List[Issue]:
        out: List[Issue] = []
        total_pb = 0
        for doc in self._content_docs():
            # epub:type="pagebreak" or role="doc-pagebreak"
            pbs = doc.soup.find_all(attrs={"epub:type": "pagebreak"})
            pbs += doc.soup.find_all(attrs={"role": "doc-pagebreak"})
            # dedupe by id (lxml-xml leaves both)
            seen = set()
            uniq = []
            for n in pbs:
                key = n.get("id") or id(n)
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(n)
            total_pb += len(uniq)

        # Compare with PDF page count.
        if total_pb == 0 and self.pdf.page_count > 0:
            out.append(Issue(
                name="Page Number Tag Missing",
                status=Status.FAIL,
                detail=f"No epub:type='pagebreak' markers found across XHTML. PDF has {self.pdf.page_count} pages.",
                category="Page Number Tag Missing",
            ))
            return out

        if total_pb < self.pdf.page_count * 0.7:
            out.append(Issue(
                name="Page Number Tag Missing",
                status=Status.PARTIAL,
                detail=(f"Found {total_pb} pagebreak markers but PDF has "
                        f"{self.pdf.page_count} pages — coverage looks incomplete."),
                category="Page Number Tag Missing",
            ))
            return out

        # Front-matter specific: look at the first few spine docs and ensure
        # at least one pagebreak appears.
        fm_docs = [d for d in self._content_docs() if any(
            tag in d.rel_path.lower() for tag in
            ("title", "copyright", "preface", "ack", "foreword", "fm")
        )]
        missing_fm = []
        for d in fm_docs:
            if not d.soup.find_all(attrs={"epub:type": "pagebreak"}):
                missing_fm.append(d.rel_path)
        if missing_fm:
            out.append(Issue(
                name="Page Number Tag Missing in FM",
                status=Status.PARTIAL,
                detail=f"Front-matter files without pagebreak markers: {len(missing_fm)}",
                snippet=", ".join(missing_fm[:5]),
                category="Page Number Tag Missing",
            ))
        if not out:
            out.append(Issue(name="Page Number Tag Missing", status=Status.PASS,
                             detail=f"{total_pb} pagebreak markers — good coverage.",
                             category="Page Number Tag Missing"))
        return out

    # ------------------------------------------------------------------ #
    # 6. Incorrect case                                                  #
    # ------------------------------------------------------------------ #
    def check_incorrect_case(self) -> List[Issue]:
        """For paragraphs that match PDF text by lowercase prefix, compare
        original casing. Differences ⇒ Incorrect Case."""
        out: List[Issue] = []
        flagged = 0
        for doc in self._content_docs():
            for p in doc.soup.find_all("p"):
                etxt = clean_inline_text(p)
                if len(etxt) < 40:
                    continue
                pdf_para = self._match_pdf_para(etxt)
                if not pdf_para:
                    continue
                # Tokenise letter words from both, compare aligned positions.
                ew = _words(etxt)[:30]
                pw = _words(pdf_para.text)[:30]
                if not ew or not pw:
                    continue
                length = min(len(ew), len(pw))
                diffs = [
                    (pw[i], ew[i]) for i in range(length)
                    if pw[i].lower() == ew[i].lower() and pw[i] != ew[i]
                    and not (pw[i].isupper() and ew[i] != ew[i].upper())  # ALL-CAPS in PDF often = small-caps in EPUB, skip
                ]
                if not diffs:
                    continue
                detail = "; ".join(f"PDF '{a}' vs EPUB '{b}'" for a, b in diffs[:5])
                out.append(Issue(
                    name="Incorrect Case",
                    status=Status.FAIL,
                    file_path=doc.rel_path,
                    line_number=line_number_of(doc, etxt[:40]),
                    snippet=etxt[:120],
                    detail=detail,
                    pdf_context=f"page {pdf_para.page}",
                    category="Incorrect Case",
                ))
                flagged += 1
                if flagged >= 30:
                    out.append(Issue(name="Incorrect Case", status=Status.PARTIAL,
                                     detail="Stopped after 30 findings.",
                                     category="Incorrect Case"))
                    return out
        if flagged == 0:
            out.append(Issue(name="Incorrect Case", status=Status.PASS,
                             detail="No case mismatches detected on matched paragraphs.",
                             category="Incorrect Case"))
        return out

    # ------------------------------------------------------------------ #
    # 7. Additional indentation                                          #
    # ------------------------------------------------------------------ #
    def check_additional_indentation(self) -> List[Issue]:
        """CSS classes with unusually large margin-left or text-indent that
        are applied to body text paragraphs."""
        out: List[Issue] = []
        suspicious_classes = set()
        for cls, decls in self.class_styles.items():
            for prop in ("margin-left", "text-indent", "padding-left"):
                val = decls.get(prop, "")
                pts = _length_to_em(val)
                if pts is not None and pts >= 4:  # >= 4em is suspicious for body
                    suspicious_classes.add((cls, prop, val))

        if not suspicious_classes:
            out.append(Issue(name="Additional Indentation", status=Status.PASS,
                             detail="No CSS classes with unusually large indentation.",
                             category="Additional Indentation"))
            return out

        # Surface up to 10 instances in the actual XHTML
        flagged = 0
        cls_lookup = {c for c, _, _ in suspicious_classes}
        for doc in self._content_docs():
            for tag in doc.soup.find_all(class_=True):
                if not (set(tag.get("class") or []) & cls_lookup):
                    continue
                if tag.name not in ("p", "div", "li"):
                    continue
                used = set(tag.get("class") or []) & cls_lookup
                relevant = [(c, p, v) for c, p, v in suspicious_classes if c in used]
                detail = "; ".join(f".{c} {p}={v}" for c, p, v in relevant[:3])
                snippet = (tag.get_text(" ", strip=True) or "")[:120]
                out.append(Issue(
                    name="Additional Indentation",
                    status=Status.PARTIAL,
                    file_path=doc.rel_path,
                    line_number=line_number_of(doc, snippet[:40]) if snippet else None,
                    snippet=snippet,
                    detail=detail,
                    category="Additional Indentation",
                ))
                flagged += 1
                if flagged >= 10:
                    return out
        return out

    # ------------------------------------------------------------------ #
    # 8. Line space missing                                              #
    # ------------------------------------------------------------------ #
    def check_line_space(self) -> List[Issue]:
        """Body-text classes with margin-top/margin-bottom set to 0."""
        out: List[Issue] = []
        zero_margin_classes: List[str] = []
        for cls, decls in self.class_styles.items():
            mt = decls.get("margin-top", "").strip()
            mb = decls.get("margin-bottom", "").strip()
            mg = decls.get("margin", "").strip()
            zeroish = lambda v: v in ("", "0", "0pt", "0px", "0em", "0rem")
            if zeroish(mt) and zeroish(mb) and (zeroish(mg) or re.match(r"^0\D", mg or "0")):
                # also require the class to actually be applied to <p>
                zero_margin_classes.append(cls)

        # Are any of these classes used on <p> elements?
        flagged = 0
        zclass_set = set(zero_margin_classes)
        for doc in self._content_docs():
            for p in doc.soup.find_all("p"):
                cls = set(p.get("class") or [])
                if not (cls & zclass_set):
                    continue
                text = (p.get_text() or "").strip()
                if len(text) < 40:
                    continue
                out.append(Issue(
                    name="Line Space Missing",
                    status=Status.PARTIAL,
                    file_path=doc.rel_path,
                    line_number=line_number_of(doc, text[:40]),
                    snippet=text[:120],
                    detail=f"<p class='{' '.join(p.get('class', []))}'> uses class(es) with zero top/bottom margin.",
                    category="Line Space Missing",
                ))
                flagged += 1
                if flagged >= 15:
                    return out
        if flagged == 0:
            out.append(Issue(name="Line Space Missing", status=Status.PASS,
                             detail="Paragraph classes carry non-zero vertical spacing.",
                             category="Line Space Missing"))
        return out

    # ------------------------------------------------------------------ #
    # 9. Additional blockquote                                           #
    # ------------------------------------------------------------------ #
    def check_additional_blockquote(self) -> List[Issue]:
        """Flag <blockquote> whose first matching PDF paragraph isn't visibly
        indented/quoted (heuristic: PDF para alignment is plain 'left' and no
        leading quote mark)."""
        out: List[Issue] = []
        flagged = 0
        for doc in self._content_docs():
            for bq in doc.soup.find_all("blockquote"):
                text = (bq.get_text() or "").strip()
                if len(text) < 30:
                    continue
                pdf_para = self._match_pdf_para(text)
                if not pdf_para:
                    continue
                # Quoted PDF text typically: indented left margin OR starts with quote char
                first_char = text.lstrip()[:1]
                if first_char in ("“", '"', "‘", "'"):
                    continue
                # If PDF paragraph isn't centred/justified differently, likely no real quote
                if pdf_para.alignment in ("justify", "left"):
                    # check if its bbox is significantly indented vs page width
                    bbox = pdf_para.bbox
                    page = self.pdf.pages[pdf_para.page - 1] if pdf_para.page <= len(self.pdf.pages) else None
                    indented = False
                    if page:
                        indented = (bbox[0] - 0) > page.width * 0.12
                    if not indented:
                        out.append(Issue(
                            name="Additional Block Quote",
                            status=Status.FAIL,
                            file_path=doc.rel_path,
                            line_number=line_number_of(doc, text[:40]),
                            snippet=text[:120],
                            detail="<blockquote> wraps text that does not appear quoted/indented in PDF.",
                            pdf_context=f"page {pdf_para.page}",
                            category="Additional Block Quote",
                        ))
                        flagged += 1
                        if flagged >= 15:
                            return out
        if flagged == 0:
            out.append(Issue(name="Additional Block Quote", status=Status.PASS,
                             detail="No unnecessary blockquotes detected.",
                             category="Additional Block Quote"))
        return out

    # ------------------------------------------------------------------ #
    # 10. Cover image size                                               #
    # ------------------------------------------------------------------ #
    def check_cover_image(self) -> List[Issue]:
        out: List[Issue] = []
        cover_path: Optional[str] = None
        # locate via manifest
        for mid, meta in self.epub.manifest.items():
            props = (meta.get("properties") or "").lower()
            if "cover-image" in props:
                cover_path = os.path.normpath(os.path.join(
                    os.path.dirname(self.epub.opf_path or ""), meta.get("href", "")
                ))
                break
        if not cover_path or not os.path.isfile(cover_path):
            # fallback: any image with 'cover' in name
            for img in self.epub.image_files:
                if "cover" in os.path.basename(img).lower():
                    cover_path = img
                    break
        if not cover_path or not os.path.isfile(cover_path):
            return [Issue(name="Cover Image Size Incorrect", status=Status.SKIP,
                          detail="No cover image found.",
                          category="Cover Image Size Incorrect")]
        try:
            with Image.open(cover_path) as img:
                w, h = img.size
        except Exception as e:  # noqa: BLE001
            return [Issue(name="Cover Image Size Incorrect", status=Status.SKIP,
                          detail=f"Could not read cover image: {e}",
                          category="Cover Image Size Incorrect")]

        # Industry guidance: minimum 1400 px on the shorter side, 1600x2400 typical.
        # Aspect ratio between 1.5 and 1.7 (Kindle), 1.5 (KDP), 1.45-1.6 generally.
        problems: List[str] = []
        if min(w, h) < 1400:
            problems.append(f"shortest side {min(w, h)}px < 1400")
        aspect = h / w if w else 0
        if aspect < 1.4 or aspect > 1.8:
            problems.append(f"aspect ratio {aspect:.2f} outside 1.4–1.8")
        status = Status.FAIL if problems else Status.PASS
        return [Issue(
            name="Cover Image Size Incorrect",
            status=status,
            file_path=os.path.relpath(cover_path, self.epub.root),
            detail=("; ".join(problems) if problems
                    else f"Cover OK ({w}×{h}, aspect {aspect:.2f})."),
            category="Cover Image Size Incorrect",
        )]

    # ------------------------------------------------------------------ #
    # 11. Body image size / centering                                    #
    # ------------------------------------------------------------------ #
    def check_body_images(self) -> List[Issue]:
        out: List[Issue] = []
        flagged = 0
        for doc in self._content_docs():
            for img in doc.soup.find_all("img"):
                parent = img.parent
                if parent and parent.name == "figure":
                    parent_align = self._effective_alignment(parent)
                else:
                    parent_align = self._effective_alignment(parent) if parent else "left"
                # check inline style/width
                w_attr = img.get("width")
                style = (img.get("style") or "")
                css_w = re.search(r"width\s*:\s*([\d.]+)(%|px|em)", style)
                centered = False
                if parent_align == "center":
                    centered = True
                # margin: 0 auto pattern
                for cls in (img.get("class") or []):
                    decls = self.class_styles.get(cls, {})
                    if (decls.get("display") == "block" and "auto" in decls.get("margin", "")) or \
                            decls.get("text-align") == "center":
                        centered = True
                # width: 100% inflates if intrinsic is small — flag <100% body image w/o centering
                if not centered:
                    out.append(Issue(
                        name="Body Image Centering",
                        status=Status.FAIL,
                        file_path=doc.rel_path,
                        line_number=line_number_of(doc, img.get("src", "")),
                        snippet=str(img)[:160],
                        detail="Image not centered (no text-align:center / margin:auto / parent center).",
                        category="Body Image Size / Centering",
                    ))
                    flagged += 1
                # width missing entirely
                if not w_attr and not css_w:
                    out.append(Issue(
                        name="Body Image Width",
                        status=Status.PARTIAL,
                        file_path=doc.rel_path,
                        snippet=str(img)[:160],
                        detail="Image has no width attribute or CSS width — sizing may be incorrect.",
                        category="Body Image Size / Centering",
                    ))
                    flagged += 1
                if flagged >= 30:
                    out.append(Issue(name="Body Image", status=Status.PARTIAL,
                                     detail="Stopped after 30 findings.",
                                     category="Body Image Size / Centering"))
                    return out
        if flagged == 0:
            out.append(Issue(name="Body Image Size / Centering", status=Status.PASS,
                             detail="All body images have centering + sizing attributes.",
                             category="Body Image Size / Centering"))
        return out

    # ------------------------------------------------------------------ #
    # 12. Color missing                                                  #
    # ------------------------------------------------------------------ #
    def check_color_missing(self) -> List[Issue]:
        out: List[Issue] = []
        # Collect colors used in EPUB CSS
        css_colors: Set[str] = set()
        color_re = re.compile(r"#[0-9a-fA-F]{3,6}|rgb\([^)]+\)|rgba\([^)]+\)")
        for r in self.epub.css_rules:
            for prop in ("color", "background-color", "border-color", "border", "background"):
                val = r.declarations.get(prop, "")
                for m in color_re.findall(val):
                    css_colors.add(m.lower())

        # Convert pdf int colors to hex
        pdf_hex: Set[str] = set()
        for c in self.pdf.colors_global:
            if c == 0:
                continue
            pdf_hex.add(f"#{c:06x}")

        if not pdf_hex:
            out.append(Issue(name="Color Missing", status=Status.SKIP,
                             detail="No non-black coloured text detected in PDF.",
                             category="Color Missing"))
            return out

        # Are any of the PDF colors absent from EPUB CSS?
        missing = []
        css_norm = {c.replace("#", "").lower() for c in css_colors if c.startswith("#")}
        for ph in pdf_hex:
            key = ph.replace("#", "")
            if key not in css_norm:
                # Also tolerate "near match" — if any css color within 24 levels per channel
                if not _near_color(ph, css_colors):
                    missing.append(ph)
        if missing:
            return [Issue(
                name="Color Missing",
                status=Status.FAIL,
                detail=f"PDF colours absent from EPUB CSS: {', '.join(sorted(missing)[:12])}",
                category="Color Missing",
            )]
        return [Issue(name="Color Missing", status=Status.PASS,
                      detail=f"{len(pdf_hex)} PDF colour(s) all represented in EPUB CSS.",
                      category="Color Missing")]

    # ------------------------------------------------------------------ #
    # 13. Max page check                                                 #
    # ------------------------------------------------------------------ #
    def check_max_page(self) -> List[Issue]:
        # In nav.xhtml there is often a page-list with the final page number.
        nav = self.epub.nav_doc
        if not nav:
            return [Issue(name="Max Page Incorrect", status=Status.SKIP,
                          detail="No nav.xhtml.",
                          category="Max Page Incorrect")]
        page_list = nav.soup.find(attrs={"epub:type": "page-list"})
        if not page_list:
            return [Issue(name="Max Page Incorrect", status=Status.PARTIAL,
                          detail="No epub:type='page-list' in nav.xhtml.",
                          category="Max Page Incorrect")]
        anchors = page_list.find_all("a")
        if not anchors:
            return [Issue(name="Max Page Incorrect", status=Status.FAIL,
                          file_path=nav.rel_path,
                          detail="page-list contains no entries.",
                          category="Max Page Incorrect")]
        numeric = [a.get_text(strip=True) for a in anchors if a.get_text(strip=True).isdigit()]
        if not numeric:
            return [Issue(name="Max Page Incorrect", status=Status.PARTIAL,
                          file_path=nav.rel_path,
                          detail="page-list has no numeric entries.",
                          category="Max Page Incorrect")]
        max_nav = max(int(n) for n in numeric)
        if self.pdf.max_logical_page and self.pdf.max_logical_page.isdigit():
            max_pdf = int(self.pdf.max_logical_page)
            if max_nav != max_pdf:
                return [Issue(
                    name="Max Page Incorrect",
                    status=Status.FAIL,
                    file_path=nav.rel_path,
                    detail=f"Max page in nav={max_nav}, in PDF labels={max_pdf}.",
                    category="Max Page Incorrect",
                )]
        return [Issue(name="Max Page Incorrect", status=Status.PASS,
                      file_path=nav.rel_path,
                      detail=f"Max page in nav={max_nav} matches PDF.",
                      category="Max Page Incorrect")]

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #
    def _content_docs(self) -> List[XhtmlDoc]:
        """All XHTML docs except nav.xhtml."""
        return [
            d for d in self.epub.xhtml_docs
            if not self.epub.nav_path or os.path.normpath(d.abs_path) != os.path.normpath(self.epub.nav_path)
        ]

    def _match_pdf_para(self, epub_text: str) -> Optional[PdfParagraph]:
        key = _normalize(epub_text)[:80]
        if not key:
            return None
        if key in self._pdf_by_key:
            return self._pdf_by_key[key]
        # Try a sliding shorter key
        short = key[:50]
        for k, p in self._pdf_by_key.items():
            if k.startswith(short):
                return p
        return None


# ---------------------------------------------------------------------- #
# Helpers                                                                #
# ---------------------------------------------------------------------- #


def _length_to_em(val: str) -> Optional[float]:
    if not val:
        return None
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*(em|rem|px|pt|%)?\s*$", val)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "em").lower()
    if unit in ("em", "rem"):
        return num
    if unit == "%":
        return num / 100.0
    if unit == "px":
        return num / 16.0
    if unit == "pt":
        return num / 12.0
    return num


def _near_color(target_hex: str, css_colors: Set[str]) -> bool:
    """Return True if any css color is within 24 per channel of target."""
    th = target_hex.lstrip("#")
    if len(th) != 6:
        return False
    try:
        tr, tg, tb = int(th[0:2], 16), int(th[2:4], 16), int(th[4:6], 16)
    except ValueError:
        return False
    for c in css_colors:
        if not c.startswith("#"):
            continue
        ch = c.lstrip("#")
        if len(ch) == 3:
            ch = "".join(x * 2 for x in ch)
        if len(ch) != 6:
            continue
        try:
            cr, cg, cb = int(ch[0:2], 16), int(ch[2:4], 16), int(ch[4:6], 16)
        except ValueError:
            continue
        if abs(cr - tr) <= 24 and abs(cg - tg) <= 24 and abs(cb - tb) <= 24:
            return True
    return False
