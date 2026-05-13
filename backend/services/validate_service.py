import os
import json
import re
import fnmatch
import sys
from bs4 import BeautifulSoup
import requests
from urllib3 import Retry
from requests.adapters import HTTPAdapter

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