import os
import json
import re
import fnmatch
import posixpath
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import requests
import urllib3
from urllib3 import Retry
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

RULES_FILE = "rules/rules.json"


# =====================================
# Vendored pdf-epub-validator adapters (book-scope rules)
# =====================================
#
# The CLI's LinkChecker, NavValidator, and StyleComparator are book-wide
# checks. We expose them as scope="book" rules so the rule loader calls
# them once per upload instead of once per file. The adapters convert
# CLI Issue objects -> the web app's {type, message, category, ...} shape.

from services import book_bundle_service as _bundle


_CLI_STATUS_TO_CATEGORY = {
    "FAIL": "Error",
    "PARTIAL": "Warning",
    "PASS": "Info",
    "SKIP": "Info",
}

# Issue categories that should surface as Warning even when the CLI marks
# them FAIL. These are layout/styling parity findings, not hard correctness
# bugs — they deserve attention but shouldn't fail a chapter outright.
_WARNING_OVERRIDES = {
    "body image size / centering",
    "hanging alignment missing",
    "incorrect alignment",
    "incorrect level in nav",
    "cover image size incorrect",
    "link missing",
}


def _cli_issue_to_web(issue) -> dict:
    """Convert a vendored Issue dataclass to the web app's issue dict."""
    status = getattr(issue.status, "value", str(issue.status))
    category = _CLI_STATUS_TO_CATEGORY.get(status, "Warning")
    issue_category_name = (issue.category or issue.name or "").strip().lower()
    if category == "Error" and issue_category_name in _WARNING_OVERRIDES:
        category = "Warning"
    return {
        "type": (issue.category or issue.name or "issue").lower().replace(" ", "_"),
        "rule_name": issue.name,
        "category": category,
        "status": status,
        "file_path": issue.file_path,
        "line_number": issue.line_number,
        "snippet": issue.snippet,
        "message": issue.detail or issue.name,
        "pdf_context": issue.pdf_context,
    }


def _drop_pass_issues(issues: list) -> list:
    """Filter out PASS markers so the UI only sees actionable findings."""
    return [i for i in issues if i.get("status") != "PASS"]


def validate_pdf_link_checker(book_details):
    """URL004 — broken anchors + missing-link patterns (book-scope)."""
    from vendor.pdf_epub_validator import LinkChecker

    folder = book_details["folder_name"]
    bundle = _bundle.get_epub_bundle(folder)
    if not bundle:
        return {"issues_count": 0, "issues": []}
    cli_issues = LinkChecker(bundle).run_all()
    issues = _drop_pass_issues([_cli_issue_to_web(i) for i in cli_issues])
    return {"issues_count": len(issues), "issues": issues}


def validate_nav_full(book_details):
    """NAV002 — heading coverage + nav hierarchy + EISBN (book-scope)."""
    from vendor.pdf_epub_validator import NavValidator

    folder = book_details["folder_name"]
    bundle = _bundle.get_epub_bundle(folder)
    if not bundle:
        return {"issues_count": 0, "issues": []}
    cli_issues = NavValidator(bundle).run_all()
    issues = _drop_pass_issues([_cli_issue_to_web(i) for i in cli_issues])
    return {"issues_count": len(issues), "issues": issues}


def validate_pdf_style_parity(book_details):
    """PDF001 — StyleComparator: paragraph splitting, italic/case/colour
    parity, alignment, indentation, blockquote, images, page count, etc.
    (book-scope — needs PdfDoc and EpubBundle)."""
    from vendor.pdf_epub_validator import StyleComparator

    folder = book_details["folder_name"]
    bundle = _bundle.get_epub_bundle(folder)
    pdf = _bundle.get_pdf_doc(folder)
    if not bundle or not pdf:
        return {"issues_count": 0, "issues": []}
    cli_issues = StyleComparator(bundle, pdf).run_all()
    issues = _drop_pass_issues([_cli_issue_to_web(i) for i in cli_issues])
    return {"issues_count": len(issues), "issues": issues}


# =====================================
# Book-level summary (for the UI's Book Summary card)
# =====================================

_STATUS_RANK = {"FAIL": 3, "PARTIAL": 2, "PASS": 1, "SKIP": 0}


def _is_chapter_path(file_path) -> bool:
    """A chapter-scope finding has a file_path ending in an XHTML extension."""
    if not file_path:
        return False
    return file_path.lower().endswith((".xhtml", ".html", ".htm"))


def _norm_rel(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/")).lstrip("./")


def _build_asset_to_chapters_index(bundle) -> dict:
    """Map every CSS/image/etc. asset referenced by an XHTML chapter to the
    list of chapter rel_paths that reference it.

    Used to route asset-scoped issues (e.g. a CSS rule deprecation) onto the
    chapters that actually use the asset, so the chapter popup can show them.
    """
    if not bundle:
        return {}
    index: dict = {}
    for doc in getattr(bundle, "xhtml_docs", []) or []:
        chap_rel = _norm_rel(doc.rel_path)
        chap_dir = posixpath.dirname(chap_rel)
        soup = doc.soup
        if soup is None:
            continue
        refs: list = []
        for tag in soup.find_all(["link", "img", "image", "script", "source", "a"]):
            href = (
                tag.get("href")
                or tag.get("src")
                or tag.get("xlink:href")
                or ""
            ).strip()
            if not href or href.startswith(("http://", "https://", "data:", "mailto:", "#")):
                continue
            href = href.split("#", 1)[0]
            if not href:
                continue
            refs.append(href)
        # @import statements inside inline <style> blocks
        for style in soup.find_all("style"):
            text = style.get_text() or ""
            for m in re.finditer(r"@import\s+(?:url\()?['\"]?([^'\")\s]+)", text):
                refs.append(m.group(1))
        for href in refs:
            resolved = _norm_rel(posixpath.join(chap_dir, href)) if chap_dir else _norm_rel(href)
            index.setdefault(resolved, []).append(chap_rel)
    return index


def _chapters_for_issue(issue, asset_index: dict | None) -> list:
    """Return the chapter rel_paths an issue should attach to.

    Empty list ⇒ the issue is global (book-only). Works for both dict-shaped
    web issues and CLI Issue dataclasses (uses getattr fallback).
    """
    fp = issue.get("file_path") if isinstance(issue, dict) else getattr(issue, "file_path", None)
    if _is_chapter_path(fp):
        return [fp]
    if not fp or not asset_index:
        return []
    return list(asset_index.get(_norm_rel(fp), []))


def _group_chapter_issues(issues, asset_index: dict | None = None):
    """Bucket book-scope issues by their chapter file_path.

    XHTML-pointed issues attach to that chapter directly. Issues pointing to
    a non-XHTML asset (CSS, image, etc.) attach to every chapter that
    references the asset via the asset_index. Issues without a recognizable
    chapter binding remain book-level only.
    """
    by_chapter: dict = {}
    for issue in issues:
        for chap in _chapters_for_issue(issue, asset_index):
            by_chapter.setdefault(chap, []).append(issue)
    return by_chapter


def _run_book_rules_with_pass(folder_name: str) -> list:
    """Run all book-scope rules, keeping PASS markers (used for the summary)."""
    from vendor.pdf_epub_validator import LinkChecker, NavValidator, StyleComparator

    bundle = _bundle.get_epub_bundle(folder_name)
    pdf = _bundle.get_pdf_doc(folder_name)
    all_issues = []
    if bundle:
        all_issues += LinkChecker(bundle).run_all()
        all_issues += NavValidator(bundle).run_all()
        if pdf:
            all_issues += StyleComparator(bundle, pdf).run_all()
    return all_issues


def build_book_summary(folder_name: str) -> dict:
    """Group all book-scope issues by category, picking the worst status per
    category. Each row mirrors one line of the CLI's console report.

    Chapter-bound findings still aggregate into their category row here so
    the summary reflects FAIL/PARTIAL state; per-chapter detail also lives
    on the chapter cards. Truncation markers are dropped — they carry no
    actionable signal.
    """
    cli_issues_all = _run_book_rules_with_pass(folder_name)

    def _is_truncation_marker(issue) -> bool:
        # The vendored CLI emits a PARTIAL "Stopped after N findings" issue
        # whenever a check hits its per-category cap. It carries no signal
        # the user can act on — the real findings are already on the chapter
        # cards — so drop it from the summary.
        detail = (getattr(issue, "detail", "") or "").strip()
        return detail.startswith("Stopped after ")

    cli_issues = [i for i in cli_issues_all if not _is_truncation_marker(i)]

    by_category: dict = {}
    for issue in cli_issues:
        cat = issue.category or issue.name or "Other"
        status = getattr(issue.status, "value", str(issue.status))
        bucket = by_category.setdefault(cat, {
            "check": cat,
            "status": "PASS",
            "count": 0,
            "fail": 0,
            "partial": 0,
            "pass": 0,
            "detail": "",
            "samples": [],
            "_file_counts": {},
        })
        bucket["count"] += 1
        bucket[status.lower()] = bucket.get(status.lower(), 0) + 1
        if _STATUS_RANK.get(status, 0) > _STATUS_RANK.get(bucket["status"], 0):
            bucket["status"] = status
            bucket["detail"] = issue.detail or ""
        elif not bucket["detail"] and issue.detail:
            bucket["detail"] = issue.detail
        if len(bucket["samples"]) < 3 and issue.detail:
            bucket["samples"].append({
                "status": status,
                "file_path": issue.file_path,
                "detail": issue.detail,
                "snippet": issue.snippet,
            })
        if issue.file_path and status in ("FAIL", "PARTIAL"):
            bucket["_file_counts"][issue.file_path] = (
                bucket["_file_counts"].get(issue.file_path, 0) + 1
            )

    # Sort: FAIL → PARTIAL → PASS, then by count descending within each
    order = {"FAIL": 0, "PARTIAL": 1, "PASS": 2, "SKIP": 3}
    rows = sorted(
        by_category.values(),
        key=lambda r: (order.get(r["status"], 9), -r["count"], r["check"]),
    )

    # Totals reflect category-level outcomes (one tally per check) so the
    # header pills match the row list — not the raw per-finding count.
    totals = {"PASS": 0, "FAIL": 0, "PARTIAL": 0, "SKIP": 0}
    for row in rows:
        totals[row["status"]] = totals.get(row["status"], 0) + 1

    # Flatten per-row file counts into a sorted list (most findings first).
    for row in rows:
        counts = row.pop("_file_counts", {})
        row["files"] = [
            {"file_path": fp, "count": c}
            for fp, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    return {
        "folder": folder_name,
        "totals": totals,
        "rows": rows,
    }


# =====================================
# VALIDATION FUNCTIONS
# =====================================

def validate_internal_xhtml_links(file_details):

    file_path = file_details["full_path"]

    issues = []

    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    links = soup.find_all("a", href=True)

    for link in links:

        href = link["href"].strip()

        if not href.endswith(".xhtml"):
            continue

        current_dir = os.path.dirname(file_path)

        target_file = os.path.normpath(
            os.path.join(current_dir, href)
        )

        if not os.path.exists(target_file):

            issues.append({
                "type": "missing_internal_file",
                "href": href,
                "message": "Referenced XHTML file not found",
                "category":"Error"
            })

    return {
        "issues_count": len(issues),
        "issues": issues
    }

_URL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3, connect=3, read=3, backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _check_single_url(href: str, session: requests.Session) -> dict | None:
    """Return an issue dict if the URL has a problem, else None."""
    try:
        resp = session.head(href, timeout=30, allow_redirects=True,
                            verify=False, headers=_URL_HEADERS)
        code = resp.status_code
        if code in (403, 405):
            resp = session.get(href, timeout=30, allow_redirects=True,
                               verify=False, headers=_URL_HEADERS, stream=True)
            code = resp.status_code
        if code < 400:
            return None
        if code == 404:
            sev, msg = "error", "URL not found"
        elif code == 403:
            sev, msg = "warning", "Access forbidden or bot blocked"
        elif code == 405:
            sev, msg = "warning", "Method not allowed"
        elif code >= 500:
            sev, msg = "warning", "Server error"
        else:
            sev, msg = "warning", "External URL issue"
        return {"type": "external_url_issue", "href": href,
                "status_code": code, "category": sev,
                "message": f"{msg}. Status code - {code}"}
    except requests.exceptions.Timeout:
        return {"type": "external_url_issue", "href": href,
                "category": "warning", "message": "Request timeout"}
    except requests.exceptions.ConnectionError:
        return {"type": "external_url_issue", "href": href,
                "category": "error", "message": "Connection error"}
    except Exception as e:
        return {"type": "external_url_issue", "href": href,
                "category": "error", "message": str(e)}


def validate_external_urls(file_details):
    file_path = file_details["full_path"]
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    hrefs = [
        link["href"].strip()
        for link in soup.find_all("a", href=True, class_="url")
        if link["href"].strip().startswith(("http://", "https://"))
    ]

    if not hrefs:
        return {"issues_count": 0, "issues": []}

    session = _make_session()
    issues = []

    # Check all URLs concurrently — sequential checking with 30 s timeout means
    # N URLs × 30 s worst-case per file; parallel cuts that to ~30 s total.
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_check_single_url, href, session): href
                   for href in hrefs}
        for future in as_completed(futures):
            result = future.result()
            if result:
                issues.append(result)

    return {"issues_count": len(issues), "issues": issues}

def validate_url_text_match(file_details):
    file_path = file_details["full_path"]
    issues = []
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    links = soup.find_all(
        "a",
        href=True,
        class_="url"
    )
    for link in links:
        href = link["href"].strip()
        text = link.get_text(strip=True)
        if href != text:
            issues.append({
                "type": "url_text_mismatch",
                "href": href,
                "expected_text": href,
                "actual_text": text,
                "message": "Displayed URL text does not match href",
                "category":"warning"
            })
    return {
        "issues_count": len(issues),
        "issues": issues
    }

def validate_nav_headings(file_details):
    file_path = file_details["full_path"]
    issues = []
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    nav = soup.find("nav", id="toc")
    nav_links = nav.find_all("a", href=True)
    for link in nav_links:
        href = link["href"].strip()
        nav_text = link.get_text(strip=True)
        # skip external urls
        if href.startswith("http"):
            continue
        # split file and id
        if "#" in href:
            chapter_file, target_id = href.split("#", 1)
        else:
            chapter_file = href
            target_id = None
        current_dir = os.path.dirname(file_path)
        target_file_path = os.path.normpath(
            os.path.join(current_dir, chapter_file)
        )
        # =====================================
        # FILE EXISTS
        # =====================================
        if not os.path.exists(target_file_path):
            issues.append({
                "type": "missing_file",
                "href": href,
                "message": "Referenced file not found",
                "category":"Error"
            })
            continue
        # no id skip heading check
        if not target_id:
            continue
        # =====================================
        # OPEN TARGET XHTML
        # =====================================
        with open(
            target_file_path,
            "r",
            encoding="utf-8"
        ) as chapter:
            chapter_soup = BeautifulSoup(
                chapter.read(),
                "html.parser"
            )
        target_element = chapter_soup.find(
            id=target_id
        )
        # =====================================
        # ID EXISTS
        # =====================================
        if not target_element:
            issues.append({
                "type": "missing_id",
                "href": href,
                "id": target_id,
                "message": "Target id not found",
                "category":"Error"
            })
            continue
        # =====================================
        # MOVE TO HEADING TAG
        # =====================================
        heading_tags = [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "p"
        ]
        current_element = target_element
        while current_element:
            if current_element.name in heading_tags:
                break
            current_element = current_element.parent
        # =====================================
        # HEADING TAG NOT FOUND
        # =====================================
        if not current_element:
            issues.append({
                "type": "heading_tag_not_found",
                "href": href,
                "id": target_id,
                "message": "Heading tag not found",
                "category":"Warning"
            })
            continue
        # =====================================
        # HEADING TEXT
        # =====================================
        if current_element:
            heading_text = current_element.get_text(
                separator=" ",
                strip=True
            )
            heading_text = " ".join(
                heading_text.split()
            )
        else:
            heading_text = ""
        # =====================================
        # TEXT MATCH
        # =====================================
        if nav_text.lower() != heading_text.lower():
            issues.append({
                "type": "heading_mismatch",
                "href": href,
                "expected_text": nav_text,
                "actual_text": heading_text,
                "message": "Nav text and heading text mismatch",
                "category":"Error"
            })
        elif nav_text != heading_text:
            issues.append({
                "type": "heading_mismatch",
                "href": href,
                "expected_text": nav_text,
                "actual_text": heading_text,
                "message": "Nav text and heading text case mismatch",
                "category":"Warning"
            })
    return {
        "issues_count": len(issues),
        "issues": issues
    }
# =====================================
# W3C CSS VALIDATOR
# =====================================

W3C_CSS_VALIDATOR_URL = (
    "https://jigsaw.w3.org/css-validator/validator"
)


def _call_w3c_css_validator(css_content, css_file_label):
    """
    Send css_content to W3C CSS Validator and return
    a list of issue dicts (each includes css_file key).
    Returns a list; raises on network failure so caller
    can catch and build its own error issue.
    """
    response = requests.post(
        W3C_CSS_VALIDATOR_URL,
        headers={
            "User-Agent": "PostmanRuntime/7.43.4"
        },
        files={
            "text": (None, css_content),
            "profile": (None, "css3svg"),
            "usermedium": (None, "all"),
            "type": (None, "none"),
            "warning": (None, "1"),
            "vextwarning": (None, ""),
            "lang": (None, "en"),
            "output": (None, "json")
        },
        timeout=60,
        verify=False
    )
    response.raise_for_status()
    validation = response.json().get("cssvalidation", {})

    raw_errors = validation.get("errors", [])
    raw_warnings = validation.get("warnings", [])

    # Normalise: API may return a list or nested dict
    if isinstance(raw_errors, dict):
        raw_errors = raw_errors.get("errorlist", {}).get("error", [])
        if isinstance(raw_errors, dict):
            raw_errors = [raw_errors]

    if isinstance(raw_warnings, dict):
        raw_warnings = raw_warnings.get("warninglist", {}).get("warning", [])
        if isinstance(raw_warnings, dict):
            raw_warnings = [raw_warnings]

    issues = []
    for error in raw_errors:
        issues.append({
            "type": "css_error",
            "css_file": css_file_label,
            "line": error.get("line"),
            "context": (error.get("context") or "").strip(),
            "message": (error.get("message") or "CSS error").strip(),
            "category": "Error"
        })
    for warning in raw_warnings:
        issues.append({
            "type": "css_warning",
            "css_file": css_file_label,
            "line": warning.get("line"),
            "context": (warning.get("context") or "").strip(),
            "message": (warning.get("message") or "CSS warning").strip(),
            "category": "Warning"
        })
    return issues


def validate_css_w3c(file_details):
    file_path = file_details["full_path"]
    issues = []

    # =====================================
    # DIRECT CSS FILE
    # =====================================
    if file_path.endswith(".css"):
        with open(file_path, "r", encoding="utf-8") as f:
            css_content = f.read()
        if not css_content.strip():
            return {"issues_count": 0, "issues": []}
        css_label = file_details["file_name"]
        try:
            issues = _call_w3c_css_validator(css_content, css_label)
        except requests.exceptions.Timeout:
            issues = [{
                "type": "css_validation_failed",
                "css_file": css_label,
                "message": "W3C CSS Validator request timed out",
                "category": "Warning"
            }]
        except requests.exceptions.ConnectionError:
            issues = [{
                "type": "css_validation_failed",
                "css_file": css_label,
                "message": "Could not reach W3C CSS Validator",
                "category": "Warning"
            }]
        except Exception as e:
            issues = [{
                "type": "css_validation_failed",
                "css_file": css_label,
                "message": f"CSS validation error: {str(e)}",
                "category": "Warning"
            }]
        return {"issues_count": len(issues), "issues": issues}

    # =====================================
    # XHTML: FIND LINKED CSS FILES
    # =====================================
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    css_links = soup.find_all(
        "link",
        rel=lambda r: r and "stylesheet" in r
    )

    validated_css = {}

    for link_tag in css_links:
        href = (link_tag.get("href") or "").strip()
        if not href or href.startswith("http"):
            continue

        current_dir = os.path.dirname(file_path)
        css_path = os.path.normpath(
            os.path.join(current_dir, href)
        )

        if not os.path.exists(css_path):
            issues.append({
                "type": "css_file_missing",
                "css_file": href,
                "message": f"Linked CSS file not found: {href}",
                "category": "Error"
            })
            continue

        # Use cached result if already validated in this run
        if css_path in validated_css:
            for issue in validated_css[css_path]:
                issues.append(dict(issue, css_file=href))
            continue

        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()

        if not css_content.strip():
            validated_css[css_path] = []
            continue

        try:
            css_file_issues = _call_w3c_css_validator(
                css_content, href
            )
            validated_css[css_path] = css_file_issues
            issues.extend(css_file_issues)
        except requests.exceptions.Timeout:
            issues.append({
                "type": "css_validation_failed",
                "css_file": href,
                "message": "W3C CSS Validator request timed out",
                "category": "Warning"
            })
        except requests.exceptions.ConnectionError:
            issues.append({
                "type": "css_validation_failed",
                "css_file": href,
                "message": "Could not reach W3C CSS Validator",
                "category": "Warning"
            })
        except Exception as e:
            issues.append({
                "type": "css_validation_failed",
                "css_file": href,
                "message": f"CSS validation error: {str(e)}",
                "category": "Warning"
            })

    return {
        "issues_count": len(issues),
        "issues": issues
    }


# =====================================
# PAGEBREAK POSITION
# =====================================
#
# Checks that each <span epub:type="pagebreak" title="N"> in a chapter is
# placed at the actual start of PDF page label N. Strategy: collect the
# first few word tokens that follow each marker in the chapter and confirm
# they appear as a contiguous substring inside the matching PDF page's text.
# Substring (rather than prefix) match tolerates running headers / page
# numbers that PyMuPDF surfaces at the top of the extracted page text.

_PAGEBREAK_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _pagebreak_normalize(text: str) -> str:
    if not text:
        return ""
    text = text.replace("­", "")  # soft hyphen
    return " ".join(_PAGEBREAK_WORD_RE.findall(text.lower()))


def _pagebreak_collect_segments(soup):
    """Walk the document and bucket text into segments delimited by pagebreak
    markers. Returns list of (label_or_None, text). segments[0] is the text
    before the first marker; each subsequent segment is owned by the
    preceding marker."""
    segments = []
    state = {"label": None, "parts": []}

    def flush(new_label):
        segments.append((state["label"], "".join(state["parts"])))
        state["label"] = new_label
        state["parts"] = []

    def is_pagebreak(el) -> str | None:
        if not getattr(el, "name", None):
            return None
        if el.get("role") == "doc-pagebreak":
            return (el.get("title") or el.get("aria-label") or "").strip() or None
        if "pagebreak" in (el.get("epub:type") or "").lower():
            return (el.get("title") or el.get("aria-label") or "").strip() or None
        return None

    def walk(node):
        for child in getattr(node, "children", []):
            label = is_pagebreak(child)
            if label is not None:
                flush(label)
                walk(child)
            elif getattr(child, "name", None):
                walk(child)
            else:
                state["parts"].append(str(child))

    walk(soup.body or soup)
    segments.append((state["label"], "".join(state["parts"])))
    return segments


def validate_pagebreak_positions(file_details):
    from services.pdf_service import _pdf_path
    import pymupdf as fitz

    file_path = file_details["full_path"]
    folder_name = file_details["folder_name"]
    issues: list[dict] = []

    pdf_file = _pdf_path(folder_name)
    if not os.path.exists(pdf_file):
        return {"issues_count": 0, "issues": []}

    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    segments = _pagebreak_collect_segments(soup)
    # The first segment has label=None (pre-marker text); skip it.
    labelled = [(label, text) for label, text in segments[1:] if label]
    if not labelled:
        return {"issues_count": 0, "issues": []}

    doc = fitz.open(pdf_file)
    try:
        for label, text in labelled:
            try:
                indices = doc.get_page_numbers(label)
            except Exception:
                indices = []
            if not indices:
                issues.append({
                    "type": "pagebreak_label_unknown",
                    "rule_name": "Pagebreak Position",
                    "page_label": label,
                    "message": f"Pagebreak marker title=\"{label}\" has no matching page label in the PDF",
                    "category": "Warning",
                })
                continue

            tokens = _PAGEBREAK_WORD_RE.findall(text.replace("­", "").lower())
            head_tokens = tokens[:5]
            if len(head_tokens) < 3:
                # Too little content to compare reliably (e.g. trailing marker).
                continue

            pdf_words = _pagebreak_normalize(doc[indices[0]].get_text("text")).split()
            # Match if at least 3 of the first 5 XHTML tokens appear in the
            # first 30 PDF tokens in order. Tolerates the inevitable
            # concatenated-word / hyphenation noise without losing the
            # signal of an off-by-a-page marker.
            scan = pdf_words[:30]
            matched = 0
            cursor = 0
            for tok in head_tokens:
                while cursor < len(scan) and scan[cursor] != tok:
                    cursor += 1
                if cursor < len(scan):
                    matched += 1
                    cursor += 1
            if matched >= 3:
                continue

            xhtml_head = " ".join(head_tokens)
            pdf_excerpt = " ".join(pdf_words[:24]) if pdf_words else ""
            issues.append({
                "type": "pagebreak_position_mismatch",
                "rule_name": "Pagebreak Position",
                "page_label": label,
                "message": (
                    f"Pagebreak marker for page {label} does not appear at the "
                    f"start of the matching PDF page"
                ),
                "expected_text": pdf_excerpt,
                "actual_text": xhtml_head,
                "category": "Warning",
            })
    finally:
        doc.close()

    return {"issues_count": len(issues), "issues": issues}


# =====================================
# LOAD RULES
# =====================================

def load_rules():
    if not os.path.exists(RULES_FILE):
        return []
    with open(RULES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("rules", [])


# =====================================
# VALIDATE EPUB
# =====================================

def validate_epub(epub_folder, folder_name, target_file=None):
    rules = load_rules()
    report = {
        "folder": folder_name,
        "epub_path": epub_folder,
        "files": []
    }

    # Resolve asset->chapter references once so book-scope issues pointing to
    # CSS/images surface under each chapter that uses them.
    asset_index = _build_asset_to_chapters_index(_bundle.get_epub_bundle(folder_name))

    # =====================================
    # LOOP RULES FIRST
    # =====================================

    for rule in rules:
        if not rule.get("enabled"):
            continue
        function_name = rule.get("function")

        # =====================================
        # BOOK-SCOPE RULES — run once per upload
        # =====================================
        if rule.get("scope") == "book":
            current_module = sys.modules[__name__]
            validation_function = getattr(current_module, function_name, None)
            if not validation_function:
                continue
            book_details = {
                "folder_name": folder_name,
                "epub_path": epub_folder,
            }
            try:
                result = validation_function(book_details)
            except Exception as e:  # noqa: BLE001
                result = {
                    "issues_count": 1,
                    "issues": [{
                        "type": "rule_error",
                        "message": f"{function_name} crashed: {e}",
                        "category": "Error",
                    }],
                }
            report["files"].append({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "function": function_name,
                "target_path": "",
                "file_pattern": "[book-scope]",
                "file_details": {
                    "file_name": "[book-level]",
                    "full_path": epub_folder,
                    "relative_path": "",
                    "folder_name": folder_name,
                },
                "result": result,
            })

            # Also surface chapter-bound findings under each chapter, so the
            # chapter card lights up and the modal lists the issue inline.
            # The [book-level] entry above keeps the full aggregate for the
            # summary card; FilesPage groups by file_name so there's no
            # double count.
            for rel_path, chapter_issues in _group_chapter_issues(
                result.get("issues", []), asset_index
            ).items():
                file_name = os.path.basename(rel_path)
                if target_file and file_name != target_file:
                    continue
                report["files"].append({
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "function": function_name,
                    "target_path": os.path.dirname(rel_path),
                    "file_pattern": "[book-scope]",
                    "file_details": {
                        "file_name": file_name,
                        "full_path": os.path.join(epub_folder, rel_path),
                        "relative_path": rel_path,
                        "folder_name": folder_name,
                    },
                    "result": {
                        "issues_count": len(chapter_issues),
                        "issues": chapter_issues,
                    },
                })
            continue

        target_path = rule.get(
            "target_path",
            ""
        ).strip("/")
        file_pattern = rule.get(
            "file_name_pattern",
            "*"
        )
        file_patterns = (
            file_pattern
            if isinstance(file_pattern, list)
            else [file_pattern]
        )

        # =====================================
        # TARGET FOLDER
        # =====================================

        search_folder = os.path.join(
            epub_folder,
            target_path
        )

        if not os.path.exists(search_folder):
            continue

        # =====================================
        # FIND FILES
        # =====================================

        for root, dirs, files in os.walk(search_folder):

            for file in files:
                  # Specific file validation
                if target_file and file != target_file:
                    continue

                # File pattern match
                if not any(
                    fnmatch.fnmatch(file, p)
                    for p in file_patterns
                ):
                    continue

                full_path = os.path.join(
                    root,
                    file
                )

                relative_path = os.path.relpath(
                    full_path,
                    epub_folder
                ).replace("\\", "/")

                file_details = {
                    "file_name": file,
                    "full_path": full_path,
                    "relative_path": relative_path,
                    "folder_name": folder_name
                }

                # =====================================
                # GET FUNCTION DYNAMICALLY
                # =====================================

                current_module = sys.modules[__name__]

                validation_function = getattr(
                    current_module,
                    function_name,
                    None
                )

                # Function not found
                if not validation_function:
                    continue

                # =====================================
                # EXECUTE VALIDATION
                # =====================================

                result = validation_function(
                    file_details
                )

                # =====================================
                # REPORT
                # =====================================

                report["files"].append({
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "function": function_name,
                    "target_path": target_path,
                    "file_pattern": file_pattern,
                    "file_details": file_details,
                    "result": result
                })

    return report