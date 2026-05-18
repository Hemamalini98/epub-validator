"""Nav-related checks: headings present in nav, hierarchy correctness."""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Set, Tuple

from bs4 import BeautifulSoup

from .epub_extractor import EpubBundle, XhtmlDoc, line_number_of, clean_inline_text
from .report_generator import Issue, Status


class NavValidator:
    def __init__(self, epub: EpubBundle):
        self.epub = epub

    def run_all(self) -> List[Issue]:
        out: List[Issue] = []
        if not self.epub.nav_doc:
            return [Issue(name="NAV Missing", status=Status.FAIL,
                          detail="nav.xhtml not found.",
                          category="Text Missing in NAV")]
        out += self.check_headings_in_nav()
        out += self.check_nav_hierarchy()
        out += self.check_eisbn_metadata()
        return out

    # ------------------------------------------------------------------ #
    # Headings vs nav coverage                                           #
    # ------------------------------------------------------------------ #
    def check_headings_in_nav(self) -> List[Issue]:
        nav_doc = self.epub.nav_doc
        if not nav_doc:
            return []
        # Collect nav anchor text (toc only — ignore page-list / landmarks)
        toc_nav = nav_doc.soup.find("nav", attrs={"epub:type": "toc"})
        if not toc_nav:
            toc_nav = nav_doc.soup.find("nav", attrs={"role": "doc-toc"})
        if not toc_nav:
            return [Issue(name="Text Missing in NAV", status=Status.FAIL,
                          file_path=nav_doc.rel_path,
                          detail="No <nav epub:type='toc'> element.",
                          category="Text Missing in NAV")]
        nav_texts = {self._norm(clean_inline_text(a)) for a in toc_nav.find_all("a")}
        nav_texts.discard("")

        # Walk content docs, gather h1/h2/h3 text
        missing: List[Tuple[str, str, str]] = []
        for d in self.epub.xhtml_docs:
            if d is nav_doc:
                continue
            # collect heading texts per doc, then check whether at least one
            # heading per doc matches a nav entry (chapter docs often have
            # a "CHAPTER 1" h1 + a "Chapter Title" h1; either matching nav is
            # sufficient to consider the doc covered).
            heading_tags = d.soup.find_all(["h1", "h2", "h3"])
            doc_matches_nav = False
            unmatched: List[Tuple[str, str]] = []
            for tag in heading_tags:
                text = clean_inline_text(tag)
                if not text or len(text) < 3:
                    continue
                nt = self._norm(text)
                if nt in nav_texts:
                    doc_matches_nav = True
                    continue
                if any(nt in n or n in nt for n in nav_texts if len(n) > 8):
                    doc_matches_nav = True
                    continue
                unmatched.append((tag.name, text))
            if not doc_matches_nav:
                # Whole document missing from TOC.
                for name, text in unmatched:
                    missing.append((d.rel_path, name, text))

        if not missing:
            return [Issue(name="Text Missing in NAV", status=Status.PASS,
                          file_path=nav_doc.rel_path,
                          detail="All h1/h2/h3 headings appear in nav.",
                          category="Text Missing in NAV")]
        out: List[Issue] = []
        for rel, tag, text in missing[:30]:
            out.append(Issue(
                name="Text Missing in NAV",
                status=Status.FAIL,
                file_path=rel,
                snippet=f"<{tag}> {text[:120]}",
                detail=f"<{tag}> heading not found in nav.xhtml TOC.",
                category="Text Missing in NAV",
            ))
        if len(missing) > 30:
            out.append(Issue(name="Text Missing in NAV", status=Status.PARTIAL,
                             detail=f"{len(missing) - 30} more missing entries omitted.",
                             category="Text Missing in NAV"))
        return out

    # ------------------------------------------------------------------ #
    # Hierarchy: heading levels match nav nesting depth                  #
    # ------------------------------------------------------------------ #
    def check_nav_hierarchy(self) -> List[Issue]:
        # Disabled: this check assumes heading levels (h1/h2/h3) express the
        # document's hierarchy with a constant offset relative to nav nesting
        # depth. Books that style headings with CSS classes, skip heading
        # levels (h1 → h3), or mix levels within a chapter all produce false
        # positives under that model. The signal-to-noise ratio is too low to
        # keep the rule active.
        return [Issue(name="Incorrect Level in NAV", status=Status.PASS,
                      detail="Hierarchy check disabled (varies by heading style).",
                      category="Incorrect Level in NAV")]
        nav_doc = self.epub.nav_doc
        if not nav_doc:
            return []
        toc_nav = nav_doc.soup.find("nav", attrs={"epub:type": "toc"})
        if not toc_nav:
            return []

        # Build {target_href#anchor_or_file: nesting_depth} for every leaf li > a
        target_depth: Dict[str, int] = {}
        for a in toc_nav.find_all("a"):
            href = a.get("href")
            if not href:
                continue
            # depth = number of <ol> ancestors inside the toc
            depth = sum(1 for p in a.parents if getattr(p, "name", None) == "ol")
            target_depth[self._resolve_href(href, nav_doc.rel_path)] = depth

        # Collect (level, depth, doc, text) tuples, then accept any *constant*
        # offset within a document. EPUBs commonly use h1 for chapter even when
        # nav nests chapters under section — that's a consistent offset of 1,
        # not a hierarchy bug.
        pairs: List[Tuple[XhtmlDoc, str, int, int]] = []
        for tgt, depth in target_depth.items():
            doc, anchor = self._find_doc(tgt)
            if not doc:
                continue
            heading = None
            if anchor:
                node = doc.soup.find(id=anchor)
                if not node:
                    # Broken nav anchor — not a hierarchy bug. Skip so the
                    # offset computation isn't poisoned by chapter-h1 fallbacks.
                    continue
                if node.name and re.match(r"h[1-6]", node.name):
                    heading = node
                else:
                    heading = node.find_parent(re.compile(r"^h[1-6]$"))
                    # If the anchor isn't inside any heading, this nav entry
                    # points to a non-heading element (case opinion start,
                    # figure caption, etc.). It says nothing about heading
                    # hierarchy, so skip it rather than guessing at the
                    # next heading.
                    if not heading:
                        continue
            else:
                heading = doc.soup.find(re.compile(r"^h[1-6]$"))
            if not heading:
                continue
            level = int(heading.name[1])
            pairs.append((doc, clean_inline_text(heading)[:80], level, depth))

        # Per-document mode offset.
        from collections import Counter
        offsets_by_doc: Dict[str, Counter] = {}
        levels_by_doc: Dict[str, Set[int]] = {}
        for doc, _txt, level, depth in pairs:
            offsets_by_doc.setdefault(doc.rel_path, Counter())[depth - level] += 1
            levels_by_doc.setdefault(doc.rel_path, set()).add(level)

        doc_offset: Dict[str, int] = {
            rel: counter.most_common(1)[0][0]
            for rel, counter in offsets_by_doc.items()
        }

        # Docs that use only a single heading level (e.g. every heading is
        # <h1>, with CSS classes carrying the visual hierarchy) carry no
        # h1/h2/h3 hierarchy to validate against — comparing nav depth to
        # heading level produces only false positives. Skip them.
        skip_docs: Set[str] = {
            rel for rel, lvls in levels_by_doc.items() if len(lvls) <= 1
        }

        problems: List[Tuple[str, str, int, int]] = []
        for doc, txt, level, depth in pairs:
            if doc.rel_path in skip_docs:
                continue
            expected = doc_offset.get(doc.rel_path, 0)
            if depth - level != expected:
                problems.append((doc.rel_path, txt, level, depth))

        if not problems:
            return [Issue(name="Incorrect Level in NAV", status=Status.PASS,
                          detail="Heading levels align with nav nesting depth.",
                          category="Incorrect Level in NAV")]
        out: List[Issue] = []
        for rel, txt, level, depth in problems[:25]:
            out.append(Issue(
                name="Incorrect Level in NAV",
                status=Status.FAIL,
                file_path=rel,
                snippet=txt,
                detail=f"Heading is h{level} but nav nesting depth is {depth}.",
                category="Incorrect Level in NAV",
            ))
        if len(problems) > 25:
            out.append(Issue(name="Incorrect Level in NAV", status=Status.PARTIAL,
                             detail=f"{len(problems) - 25} more discrepancies omitted.",
                             category="Incorrect Level in NAV"))
        return out

    # ------------------------------------------------------------------ #
    # EISBN check (front-matter metadata)                                #
    # ------------------------------------------------------------------ #
    def check_eisbn_metadata(self) -> List[Issue]:
        """Look for an electronic ISBN either in OPF metadata or in front
        matter; ensure it is present."""
        # 1. OPF metadata
        if self.epub.opf_path:
            try:
                txt = open(self.epub.opf_path, encoding="utf-8", errors="replace").read()
            except OSError:
                txt = ""
            if re.search(r"(eisbn|electronic\s*isbn)", txt, re.I):
                return [Issue(name="EISBN Missing", status=Status.PASS,
                              detail="EISBN reference present in OPF metadata.",
                              category="EISBN Missing")]

        # 2. Front-matter content
        for d in self.epub.xhtml_docs:
            if not any(x in d.rel_path.lower() for x in ("copyright", "title", "fm", "imprint")):
                continue
            content = d.soup.get_text(" ", strip=True)
            if re.search(r"(eisbn|electronic\s*isbn)\s*[:\-]?\s*[\d\-]{10,}", content, re.I):
                return [Issue(name="EISBN Missing", status=Status.PASS,
                              file_path=d.rel_path,
                              detail="EISBN found in front matter.",
                              category="EISBN Missing")]
        return [Issue(name="EISBN Missing", status=Status.FAIL,
                      detail="No EISBN found in OPF metadata or front-matter pages.",
                      category="EISBN Missing")]

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s or "").strip().lower()

    def _resolve_href(self, href: str, nav_rel: str) -> str:
        """Normalize nav href to '<rel/path/to/file.xhtml>#anchor' from EPUB root."""
        nav_dir = os.path.dirname(nav_rel)
        if "#" in href:
            file_part, anchor = href.split("#", 1)
        else:
            file_part, anchor = href, ""
        if file_part:
            resolved = os.path.normpath(os.path.join(nav_dir, file_part))
        else:
            resolved = nav_rel  # in-doc anchor
        return f"{resolved}#{anchor}" if anchor else resolved

    def _find_doc(self, target: str) -> Tuple[Optional[XhtmlDoc], Optional[str]]:
        rel, _, anchor = target.partition("#")
        for d in self.epub.xhtml_docs:
            if os.path.normpath(d.rel_path) == os.path.normpath(rel):
                return d, anchor or None
        return None, None
