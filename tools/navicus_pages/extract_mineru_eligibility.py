#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SECTION_HEADING_RE = re.compile(
    r"^#{1,6}\s*"
    r"(?:[0-9０-９]+[．.\s、]|[(（]?[0-9０-９]+[)）]|[一二三四五六七八九十]+[．.\s、])?"
    r".*(?:入札者に必要な資格|入札参加資格|競争参加資格|参加資格|応募条件|応募資格|資格要件|企画提案応募条件)"
)
TERM_RE = re.compile(
    r"入札者に必要な資格|入札参加資格|競争参加資格|参加資格|応募条件|応募資格|資格要件|"
    r"企画提案応募条件|資格の種類|全省庁統一資格|資格者名簿|名簿に登録|名簿に登載|"
    r"役務の提供等|指名停止|暴力団|地方自治法施行令|実績|許可|認可|コンソーシアム|共同企業体"
)
PRIMARY_SECTION_RE = re.compile(r"^#{1,6}\s*([0-9０-９]+)[．.\s、]")
HTML_TAG_RE = re.compile(r"<[^>]+>")


def normalize_for_display(text: str, *, limit: int = 900) -> str:
    text = HTML_TAG_RE.sub(" ", text)
    text = text.replace("\r", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def primary_section_number(line: str) -> str:
    match = PRIMARY_SECTION_RE.match(line.strip())
    return match.group(1) if match else ""


def markdown_path_for(out_dir: Path, slug: str) -> Path:
    direct = out_dir / slug / "txt" / f"{slug}.md"
    if direct.exists():
        return direct
    matches = sorted((out_dir / slug).glob("**/*.md"))
    if matches:
        return matches[0]
    return direct


def extract_section(markdown: str) -> tuple[str, str]:
    lines = markdown.splitlines()
    start_index = -1
    start_section = ""
    source = "term_context"

    for i, line in enumerate(lines):
        if SECTION_HEADING_RE.search(line.strip()):
            start_index = i
            start_section = primary_section_number(line)
            source = "heading"
            break

    if start_index < 0:
        for i, line in enumerate(lines):
            if TERM_RE.search(line):
                start_index = max(0, i - 3)
                start_section = primary_section_number(line)
                break

    if start_index < 0:
        return "", "not_found"

    end_index = min(len(lines), start_index + 36)
    for j in range(start_index + 1, len(lines)):
        line = lines[j].strip()
        next_section = primary_section_number(line)
        if next_section and (not start_section or next_section != start_section):
            end_index = j
            break

    section = "\n".join(lines[start_index:end_index])
    return normalize_for_display(section), source


def summarize_section(section: str) -> str:
    lines = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        if TERM_RE.search(line) or re.match(r"^[・(（]?[0-9０-９一二三四五六七八九十アイウエオa-zA-Z]+[)）．.、]", line):
            lines.append(line)
        if len(lines) >= 8:
            break
    if not lines:
        lines = [line.strip() for line in section.splitlines() if line.strip()][:4]
    return normalize_for_display(" / ".join(lines), limit=520)


def build_report(manifest: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    cases = []
    extracted = 0
    for item in manifest:
        slug = str(item.get("slug") or "")
        md_path = markdown_path_for(out_dir, slug)
        if not md_path.exists():
            cases.append(
                {
                    **item,
                    "status": "markdown_missing",
                    "markdownPath": str(md_path),
                    "eligibilitySnippet": "",
                    "eligibilitySection": "",
                }
            )
            continue
        markdown = md_path.read_text(encoding="utf-8", errors="replace")
        section, extraction_source = extract_section(markdown)
        status = "extracted" if section else "not_found"
        if section:
            extracted += 1
        cases.append(
            {
                **item,
                "status": status,
                "extractionSource": extraction_source,
                "markdownPath": str(md_path),
                "eligibilitySnippet": summarize_section(section) if section else "",
                "eligibilitySection": section,
            }
        )
    return {
        "caseCount": len(cases),
        "extractedCount": extracted,
        "notFoundCount": len(cases) - extracted,
        "cases": cases,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# MinerU eligibility extraction trial",
        "",
        f"- cases: {report['caseCount']}",
        f"- extracted: {report['extractedCount']}",
        f"- not_found: {report['notFoundCount']}",
        "",
    ]
    for case in report["cases"]:
        lines.extend(
            [
                f"## {case.get('slug')} - {case.get('title')}",
                "",
                f"- status: {case.get('status')}",
                f"- source: {case.get('url')}",
                f"- markdown: {case.get('markdownPath')}",
                "",
            ]
        )
        snippet = case.get("eligibilitySnippet") or ""
        if snippet:
            lines.extend(["### Snippet", "", snippet, ""])
        section = case.get("eligibilitySection") or ""
        if section:
            lines.extend(["### Extracted section", "", "```text", section, "```", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract bidder eligibility sections from MinerU Markdown outputs.")
    parser.add_argument("--manifest", type=Path, required=True, help="JSON array of source PDF targets.")
    parser.add_argument("--mineru-out", type=Path, required=True, help="MinerU output directory containing <slug>/txt/<slug>.md.")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--md-out", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        raise SystemExit("--manifest must contain a JSON array")
    report = build_report(manifest, args.mineru_out)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.md_out:
        write_markdown(report, args.md_out)
    print(json.dumps({k: report[k] for k in ("caseCount", "extractedCount", "notFoundCount")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
