"""Link checks: broken anchors and expected-but-missing hyperlinks."""

from __future__ import annotations

import os
import re
from typing import Dict, List, Set, Tuple

from .epub_extractor import EpubBundle, XhtmlDoc, line_number_of
from .report_generator import Issue, Status


# Patterns we treat as "this looks like it should be a link" when not wrapped in <a>.
_REFERENCE_PATTERNS = [
    re.compile(r"\bsee\s+Chapter\s+\d+\b", re.I),
    re.compile(r"\bsee\s+Section\s+[IVXLCDM\d]+\b"),
    re.compile(r"\bsee\s+Appendix\s+[A-Z]\b"),
    re.compile(r"\bFigure\s+\d+(?:[.\-]\d+)?\b"),
    re.compile(r"\bTable\s+\d+(?:[.\-]\d+)?\b"),
    re.compile(r"\(p{1,2}\.\s*\d{1,4}\b"),       # "(p. 45" / "(pp. 45-46"
]


class LinkChecker:
    def __init__(self, epub: EpubBundle):
        self.epub = epub
        self._id_index: Dict[str, Set[str]] = {}  # rel_path -> {ids}
        self._build_id_index()

    def _build_id_index(self) -> None:
        for d in self.epub.xhtml_docs:
            ids: Set[str] = set()
            for tag in d.soup.find_all(attrs={"id": True}):
                ids.add(tag.get("id"))
            self._id_index[os.path.normpath(d.rel_path)] = ids

    def run_all(self) -> List[Issue]:
        out: List[Issue] = []
        out += self.check_broken_links()
        out += self.check_missing_links()
        return out

    # ------------------------------------------------------------------ #
    # Broken anchors                                                     #
    # ------------------------------------------------------------------ #
    def check_broken_links(self) -> List[Issue]:
        problems: List[Issue] = []
        for d in self.epub.xhtml_docs:
            for a in d.soup.find_all("a"):
                href = a.get("href")
                if not href:
                    continue
                if re.match(r"^[a-z]+:", href) or href.startswith("mailto:"):
                    continue  # external
                # resolve to file#anchor
                if "#" in href:
                    file_part, anchor = href.split("#", 1)
                else:
                    file_part, anchor = href, ""

                if file_part:
                    target_rel = os.path.normpath(os.path.join(os.path.dirname(d.rel_path), file_part))
                else:
                    target_rel = os.path.normpath(d.rel_path)

                if target_rel not in self._id_index:
                    problems.append(Issue(
                        name="Broken Links",
                        status=Status.FAIL,
                        file_path=d.rel_path,
                        line_number=line_number_of(d, f'href="{href}"'),
                        snippet=str(a)[:160],
                        detail=f"Link target file '{target_rel}' does not exist in EPUB.",
                        category="Broken Links",
                    ))
                elif anchor and anchor not in self._id_index[target_rel]:
                    problems.append(Issue(
                        name="Broken Links",
                        status=Status.FAIL,
                        file_path=d.rel_path,
                        line_number=line_number_of(d, f'href="{href}"'),
                        snippet=str(a)[:160],
                        detail=f"Anchor #{anchor} not found in '{target_rel}'.",
                        category="Broken Links",
                    ))
        if not problems:
            return [Issue(name="Broken Links", status=Status.PASS,
                          detail="All internal anchors resolve.",
                          category="Broken Links")]
        return problems

    # ------------------------------------------------------------------ #
    # Missing links (text that *should* be linked)                       #
    # ------------------------------------------------------------------ #
    def check_missing_links(self) -> List[Issue]:
        out: List[Issue] = []
        for d in self.epub.xhtml_docs:
            for p in d.soup.find_all(["p", "li"]):
                # If the element has any <a>, assume the relevant refs there are
                # already linked. Only worry about un-linked occurrences elsewhere.
                linked_text = " ".join(a.get_text(" ", strip=True) for a in p.find_all("a"))
                text = p.get_text(" ", strip=True)
                if not text:
                    continue
                for pat in _REFERENCE_PATTERNS:
                    for m in pat.finditer(text):
                        snippet = m.group(0)
                        if snippet in linked_text:
                            continue
                        out.append(Issue(
                            name="Link Missing",
                            status=Status.PARTIAL,
                            file_path=d.rel_path,
                            line_number=line_number_of(d, snippet),
                            snippet=f"…{text[max(0, m.start()-25):m.end()+25]}…",
                            detail=f"Reference '{snippet}' appears without a hyperlink.",
                            category="Link Missing",
                        ))
        if not out:
            out.append(Issue(name="Link Missing", status=Status.PASS,
                             detail="No obvious unlinked references detected.",
                             category="Link Missing"))
        return out
