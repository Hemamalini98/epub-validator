import os
import json
import re
import fnmatch
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

    # =====================================
    # LOOP RULES FIRST
    # =====================================

    for rule in rules:
        if not rule.get("enabled"):
            continue
        function_name = rule.get("function")
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