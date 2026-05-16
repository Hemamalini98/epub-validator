"""EPUB extraction: unzip, locate parts, parse XHTML + CSS."""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cssutils
from bs4 import BeautifulSoup

# Silence cssutils warnings on malformed CSS in samples.
cssutils.log.setLevel("CRITICAL")


@dataclass
class XhtmlDoc:
    rel_path: str          # path relative to EPUB root, e.g. "OEBPS/xhtml/13_Chapter01.xhtml"
    abs_path: str          # absolute path on disk
    raw: str               # original XHTML source
    soup: BeautifulSoup    # parsed tree (lxml-xml)
    lines: List[str] = field(default_factory=list)  # raw split for line number lookup


@dataclass
class CssRule:
    selector: str
    declarations: Dict[str, str]   # property -> value


@dataclass
class EpubBundle:
    root: str                                  # extraction root dir
    opf_path: Optional[str]
    nav_path: Optional[str]
    nav_doc: Optional[XhtmlDoc]
    spine_order: List[str]                     # rel paths in reading order
    xhtml_docs: List[XhtmlDoc]
    css_rules: List[CssRule]
    css_files: List[str]
    image_files: List[str]
    manifest: Dict[str, Dict[str, str]]        # id -> {href, media-type, properties}


class EpubExtractor:
    """Unpacks an EPUB and exposes parsed XHTML and CSS."""

    def __init__(self, epub_path: str = ""):
        self.epub_path = epub_path
        self._tmp_dir: Optional[str] = None

    def __enter__(self) -> "EpubExtractor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    # ------------------------------------------------------------------ #
    # Extraction                                                         #
    # ------------------------------------------------------------------ #
    def extract(self, dest: Optional[str] = None) -> EpubBundle:
        """Unzip and parse the EPUB. Returns a fully populated bundle."""
        if dest is None:
            dest = tempfile.mkdtemp(prefix="epub_")
            self._tmp_dir = dest
        os.makedirs(dest, exist_ok=True)

        with zipfile.ZipFile(self.epub_path, "r") as zf:
            zf.extractall(dest)

        return self._parse_extracted(dest)

    def parse_dir(self, dest: str) -> EpubBundle:
        """Parse an already-extracted EPUB directory without unzipping."""
        return self._parse_extracted(dest)

    def _parse_extracted(self, dest: str) -> EpubBundle:
        """Build an EpubBundle from an already-extracted directory."""
        opf_path = self._find_opf(dest)
        manifest, spine_order, opf_root = self._parse_opf(opf_path) if opf_path else ({}, [], dest)
        nav_path = self._find_nav(dest, manifest, opf_root)

        xhtml_paths = self._collect_xhtml(dest)
        xhtml_docs: List[XhtmlDoc] = []
        for ap in xhtml_paths:
            try:
                doc = self._parse_xhtml(ap, dest)
                xhtml_docs.append(doc)
            except Exception as e:  # noqa: BLE001
                # tolerate malformed files but record them
                xhtml_docs.append(XhtmlDoc(
                    rel_path=os.path.relpath(ap, dest),
                    abs_path=ap,
                    raw=f"<!-- parse error: {e} -->",
                    soup=BeautifulSoup("", "lxml-xml"),
                ))

        css_files = self._collect_css(dest)
        css_rules = self._parse_all_css(css_files)
        image_files = self._collect_images(dest)
        nav_norm = os.path.normcase(os.path.abspath(nav_path)) if nav_path else None
        nav_doc = next((d for d in xhtml_docs if nav_norm and os.path.normcase(os.path.abspath(d.abs_path)) == nav_norm), None)

        return EpubBundle(
            root=dest,
            opf_path=opf_path,
            nav_path=nav_path,
            nav_doc=nav_doc,
            spine_order=spine_order,
            xhtml_docs=xhtml_docs,
            css_rules=css_rules,
            css_files=css_files,
            image_files=image_files,
            manifest=manifest,
        )

    def cleanup(self) -> None:
        if self._tmp_dir and os.path.isdir(self._tmp_dir):
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #
    def _find_opf(self, root: str) -> Optional[str]:
        # First, try META-INF/container.xml for the rootfile path
        container = self._first_match(root, "container.xml")
        if container:
            try:
                txt = Path(container).read_text(encoding="utf-8", errors="replace")
                m = re.search(r'rootfile[^>]*full-path="([^"]+)"', txt)
                if m:
                    rel = m.group(1)
                    # rel is relative to EPUB top-level; the zip extracts into root,
                    # but if there's a single subdir wrapping everything, look both places
                    candidate = os.path.join(root, rel)
                    if os.path.isfile(candidate):
                        return candidate
                    # Try with each immediate subdir prepended
                    for d in os.listdir(root):
                        p = os.path.join(root, d, rel)
                        if os.path.isfile(p):
                            return p
            except Exception:  # noqa: BLE001
                pass
        # Fallback: glob
        for r, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith(".opf"):
                    return os.path.join(r, f)
        return None

    def _parse_opf(self, opf_path: str) -> Tuple[Dict[str, Dict[str, str]], List[str], str]:
        text = Path(opf_path).read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(text, "lxml-xml")
        manifest: Dict[str, Dict[str, str]] = {}
        for item in soup.find_all("item"):
            mid = item.get("id")
            if not mid:
                continue
            manifest[mid] = {
                "href": item.get("href", ""),
                "media-type": item.get("media-type", ""),
                "properties": item.get("properties", ""),
            }

        spine_order: List[str] = []
        opf_dir = os.path.dirname(opf_path)
        for itref in soup.find_all("itemref"):
            idref = itref.get("idref")
            if idref and idref in manifest:
                spine_order.append(os.path.normpath(os.path.join(opf_dir, manifest[idref]["href"])))

        return manifest, spine_order, opf_dir

    def _find_nav(self, root: str, manifest: Dict[str, Dict[str, str]], opf_dir: str) -> Optional[str]:
        # Preferred: manifest entry with properties containing 'nav'
        for mid, meta in manifest.items():
            if "nav" in (meta.get("properties") or ""):
                return os.path.normpath(os.path.join(opf_dir, meta["href"]))
        # Fallback: any file named nav.xhtml
        for r, _, files in os.walk(root):
            for f in files:
                if f.lower() == "nav.xhtml":
                    return os.path.join(r, f)
        return None

    def _collect_xhtml(self, root: str) -> List[str]:
        out: List[str] = []
        for r, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith((".xhtml", ".html", ".htm")):
                    out.append(os.path.join(r, f))
        out.sort()
        return out

    def _collect_css(self, root: str) -> List[str]:
        out: List[str] = []
        for r, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith(".css"):
                    out.append(os.path.join(r, f))
        return out

    def _collect_images(self, root: str) -> List[str]:
        exts = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")
        out: List[str] = []
        for r, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith(exts):
                    out.append(os.path.join(r, f))
        return out

    def _parse_xhtml(self, abs_path: str, root: str) -> XhtmlDoc:
        text = Path(abs_path).read_text(encoding="utf-8", errors="replace")
        # lxml-xml preserves epub:type and case sensitivity better than html.parser
        try:
            soup = BeautifulSoup(text, "lxml-xml")
            # if root has no children (mis-parse on entities) fall back to lxml html
            if not list(soup.children):
                raise ValueError("empty xml parse")
        except Exception:
            soup = BeautifulSoup(text, "lxml")
        return XhtmlDoc(
            rel_path=os.path.relpath(abs_path, root),
            abs_path=abs_path,
            raw=text,
            soup=soup,
            lines=text.splitlines(),
        )

    def _parse_all_css(self, css_files: List[str]) -> List[CssRule]:
        rules: List[CssRule] = []
        for f in css_files:
            try:
                txt = Path(f).read_text(encoding="utf-8", errors="replace")
                sheet = cssutils.parseString(txt)
                for rule in sheet.cssRules:
                    if rule.type != rule.STYLE_RULE:
                        continue
                    decls: Dict[str, str] = {}
                    for prop in rule.style:
                        decls[prop.name.lower().strip()] = prop.value.strip()
                    # one CssRule per selector in the list
                    for sel in [s.strip() for s in rule.selectorText.split(",")]:
                        rules.append(CssRule(selector=sel, declarations=decls))
            except Exception:  # noqa: BLE001
                continue
        return rules

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _first_match(self, root: str, name: str) -> Optional[str]:
        for r, _, files in os.walk(root):
            for f in files:
                if f.lower() == name.lower():
                    return os.path.join(r, f)
        return None


def clean_inline_text(tag) -> str:
    """Concatenate descendant text nodes without inserting separators.

    Adjacent inline elements like <small> or <span> used for small-caps
    must not introduce spurious whitespace; ``get_text(" ")`` would turn
    ``C<small>HAPTER</small>`` into ``C HAPTER``. <br> is replaced with a
    single space so multi-line headings collapse cleanly.
    """
    if tag is None:
        return ""
    parts: List[str] = []
    try:
        descendants = tag.descendants
    except AttributeError:
        return str(tag)
    for d in descendants:
        if isinstance(d, str):
            parts.append(str(d))
            continue
        if getattr(d, "name", None) == "br":
            parts.append(" ")
    txt = "".join(parts)
    return re.sub(r"\s+", " ", txt).strip()


def line_number_of(doc: XhtmlDoc, needle: str) -> Optional[int]:
    """Find first line in raw source containing `needle`. 1-based. None if absent."""
    if not needle:
        return None
    needle = needle.strip()
    if not needle:
        return None
    short = needle[:80]
    for i, line in enumerate(doc.lines, 1):
        if short and short in line:
            return i
    return None
