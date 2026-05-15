"""Report generation: Issue dataclass + console / JSON writers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any, Union


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    SKIP = "SKIP"


@dataclass
class Issue:
    """A single validation finding."""

    name: str
    status: Status
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    snippet: Optional[str] = None
    detail: Optional[str] = None
    category: Optional[str] = None
    pdf_context: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class Report:
    epub_path: str
    pdf_path: str
    issues: List[Issue] = field(default_factory=list)

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)

    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {s.value: 0 for s in Status}
        for i in self.issues:
            counts[i.status.value] += 1
        counts["TOTAL"] = len(self.issues)
        return counts


class ReportGenerator:
    """Render a Report to console + JSON file."""

    @staticmethod
    def to_json(report: Report, out_path: Union[str, Path]) -> Path:
        out = Path(out_path)
        payload = {
            "epub_path": report.epub_path,
            "pdf_path": report.pdf_path,
            "summary": report.summary(),
            "issues": [i.to_dict() for i in report.issues],
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    @staticmethod
    def to_console(report: Report) -> str:
        lines: List[str] = []
        bar = "=" * 78
        lines.append(bar)
        lines.append("PDF → EPUB Validation Report")
        lines.append(bar)
        lines.append(f"PDF  : {report.pdf_path}")
        lines.append(f"EPUB : {report.epub_path}")
        lines.append("")

        summary = report.summary()
        lines.append(
            f"Summary: PASS={summary['PASS']}  FAIL={summary['FAIL']}  "
            f"PARTIAL={summary['PARTIAL']}  SKIP={summary['SKIP']}  TOTAL={summary['TOTAL']}"
        )
        lines.append("-" * 78)

        # Group by category for readability.
        by_cat: Dict[str, List[Issue]] = {}
        for issue in report.issues:
            by_cat.setdefault(issue.category or issue.name, []).append(issue)

        for cat, issues in by_cat.items():
            lines.append("")
            lines.append(f"[{cat}]")
            for i in issues:
                head = f"  {i.status.value:7s} {i.name}"
                if i.file_path:
                    head += f"  ({i.file_path}"
                    if i.line_number:
                        head += f":{i.line_number}"
                    head += ")"
                lines.append(head)
                if i.detail:
                    lines.append(f"           {i.detail}")
                if i.snippet:
                    snip = i.snippet.strip().replace("\n", " ")
                    if len(snip) > 160:
                        snip = snip[:157] + "..."
                    lines.append(f"           EPUB: {snip}")
                if i.pdf_context:
                    pc = i.pdf_context.strip().replace("\n", " ")
                    if len(pc) > 160:
                        pc = pc[:157] + "..."
                    lines.append(f"           PDF : {pc}")

        lines.append("")
        lines.append(bar)
        return "\n".join(lines)
