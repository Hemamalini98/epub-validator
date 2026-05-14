import os
import json
import re
import fnmatch
import posixpath
import sys
from bs4 import BeautifulSoup
import requests
from urllib3 import Retry
from requests.adapters import HTTPAdapter

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


def _cli_issue_to_web(issue) -> dict:
    """Convert a vendored Issue dataclass to the web app's issue dict."""
    status = getattr(issue.status, "value", str(issue.status))
    return {
        "type": (issue.category or issue.name or "issue").lower().replace(" ", "_"),
        "rule_name": issue.name,
        "category": _CLI_STATUS_TO_CATEGORY.get(status, "Warning"),
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

    Chapter-bound findings (anything with an XHTML file_path, or a non-XHTML
    asset that some chapter references) are excluded — they live on the
    per-chapter cards instead. The summary keeps only truly book-wide
    results, so PASS markers and global FAILs (e.g. missing EISBN, broken
    cross-anchor links) surface here without the chapter-level noise.
    """
    cli_issues_all = _run_book_rules_with_pass(folder_name)
    asset_index = _build_asset_to_chapters_index(_bundle.get_epub_bundle(folder_name))

    def _is_chapter_actionable(issue) -> bool:
        # PASS/SKIP markers are book-wide observations even when their
        # file_path points to where the evidence was found — they belong in
        # the summary. Only filter FAIL/PARTIAL findings down to those with
        # no chapter binding.
        status = getattr(issue.status, "value", str(issue.status))
        if status not in ("FAIL", "PARTIAL"):
            return False
        return bool(_chapters_for_issue(issue, asset_index))

    def _is_truncation_marker(issue) -> bool:
        # The vendored CLI emits a PARTIAL "Stopped after N findings" issue
        # whenever a check hits its per-category cap. It carries no signal
        # the user can act on — the real findings are already on the chapter
        # cards — so drop it from the summary.
        detail = (getattr(issue, "detail", "") or "").strip()
        return detail.startswith("Stopped after ")

    cli_issues = [
        i for i in cli_issues_all
        if not _is_chapter_actionable(i) and not _is_truncation_marker(i)
    ]

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

    totals = {"PASS": 0, "FAIL": 0, "PARTIAL": 0, "SKIP": 0}
    for issue in cli_issues:
        s = getattr(issue.status, "value", str(issue.status))
        totals[s] = totals.get(s, 0) + 1

    # Sort: FAIL → PARTIAL → PASS, then by count descending within each
    order = {"FAIL": 0, "PARTIAL": 1, "PASS": 2, "SKIP": 3}
    rows = sorted(
        by_category.values(),
        key=lambda r: (order.get(r["status"], 9), -r["count"], r["check"]),
    )

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

def validate_external_urls(file_details):

    file_path = file_details["full_path"]
    issues = []
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    links = soup.find_all("a", href=True, class_="url")
    # =====================================
    # REQUEST HEADERS
    # =====================================
    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    # =====================================
    # SESSION + RETRY
    # =====================================
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=2,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504
        ],
        allowed_methods=["HEAD", "GET"],
    )
    adapter = HTTPAdapter(
        max_retries=retry
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    # =====================================
    # LOOP LINKS
    # =====================================
    for link in links:
        href = link["href"].strip()
        if not (
            href.startswith("http://")
            or href.startswith("https://")
        ):
            continue
        try:
            # =====================================
            # TRY HEAD
            # =====================================
            response = session.head(
                href,
                timeout=30,
                allow_redirects=True,
                verify=False,
                headers=REQUEST_HEADERS,
            )
            status_code = response.status_code

            # =====================================
            # HEAD BLOCKED -> TRY GET
            # =====================================
            if status_code in [403, 405]:

                response = session.get(
                    href,
                    timeout=30,
                    allow_redirects=True,
                    verify=False,
                    headers=REQUEST_HEADERS,
                    stream=True
                )
                status_code = response.status_code
            # =====================================
            # SUCCESS
            # =====================================
            if status_code < 400:
                continue
            # =====================================
            # ISSUE CATEGORY
            # =====================================
            severity = "warning"
            message = "External URL issue"
            if status_code == 404:
                severity = "error"
                message = "URL not found"
            elif status_code == 403:
                severity = "warning"
                message = "Access forbidden or bot blocked"
            elif status_code == 405:
                severity = "warning"
                message = "Method not allowed"
            elif status_code >= 500:
                severity = "warning"
                message = "Server error"
            issues.append({
                "type": "external_url_issue",
                "href": href,
                "status_code": status_code,
                "category": severity,
                "message": message +'.Status code - '+ str(status_code)
            })
        except requests.exceptions.Timeout:
            issues.append({
                "type": "external_url_issue",
                "href": href,
                "category": "warning",
                "message": "Request timeout"
            })
        except requests.exceptions.ConnectionError:
            issues.append({
                "type": "external_url_issue",
                "href": href,
                "category": "error",
                "message": "Connection error"
            })
        except Exception as e:
            issues.append({
                "type": "external_url_issue",
                "href": href,
                "category": "error",
                "message": str(e)
            })
    return {
        "issues_count": len(issues),
        "issues": issues
    }

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
            "h6"
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
                if not fnmatch.fnmatch(
                    file,
                    file_pattern
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