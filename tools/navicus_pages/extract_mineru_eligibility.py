#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
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
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

LLM_SUMMARY_INSTRUCTIONS = """\
あなたは日本の自治体・公共調達の参加資格を営業確認用に要約する担当者です。
MinerUで抽出した公式PDFの参加資格セクションを読み、NAVICUSの営業担当が一覧画面で判断できる短い日本語に要約してください。

出力はJSONのみ:
{"summary":"...", "confidence":"high|medium|low"}

summaryの条件:
- 160〜260字程度。
- 「公式PDF資格要約（要確認）:」などの接頭辞は付けない。
- 実績要件、全省庁統一資格/自治体名簿、地域要件、認証、説明会参加、JV/コンソーシアム可否、指名停止・暴排除外など営業判断に必要な条件を優先する。
- 原文にない条件を補わない。
- OCR改行の「コンテン / ツ」のような分断を自然に直す。
- 参加資格ではない日程・予算・契約方式は入れない。
"""


def normalize_for_display(text: str, *, limit: int = 900) -> str:
    text = HTML_TAG_RE.sub(" ", text)
    text = text.replace("\r", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def compact_single_line(text: str, *, limit: int = 320) -> str:
    text = HTML_TAG_RE.sub(" ", str(text or ""))
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.replace(" / ", "、")
    text = re.sub(r"([ァ-ヶ一-龥])\s*/\s*([ァ-ヶ一-龥])", r"\1\2", text)
    text = re.sub(r"\s+", " ", text).strip(" 、。")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip(" 、。") + "..."


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


def parse_response_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"].strip()
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict):
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "\n".join(parts).strip()


def parse_summary_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    match = JSON_BLOCK_RE.search(candidate)
    if match:
        candidate = match.group(1).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return {"summary": compact_single_line(candidate), "confidence": "low"}
    if not isinstance(payload, dict):
        return {"summary": compact_single_line(candidate), "confidence": "low"}
    return {
        "summary": compact_single_line(payload.get("summary")),
        "confidence": str(payload.get("confidence") or "medium"),
    }


def openai_summarize(case: dict[str, Any], *, model: str, base_url: str) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --llm-summary-mode openai")
    user_prompt = {
        "title": case.get("title"),
        "source_url": case.get("url"),
        "eligibility_section": case.get("eligibilitySection"),
    }
    body = json.dumps(
        {
            "model": model,
            "input": LLM_SUMMARY_INSTRUCTIONS + "\n\n入力:\n" + json.dumps(user_prompt, ensure_ascii=False),
            "temperature": 0.1,
            "max_output_tokens": 420,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc
    return parse_summary_json(parse_response_output_text(payload))


def override_keys(case: dict[str, Any]) -> list[str]:
    keys = []
    for field in ("slug", "url", "title"):
        value = str(case.get(field) or "").strip()
        if value:
            keys.append(value)
    return keys


def load_llm_summary_overrides(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit("--llm-summary-overrides must contain a JSON array or {cases:[...]}")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        summary = compact_single_line(
            row.get("eligibilityLlmSummary")
            or row.get("eligibilityDisplaySummary")
            or row.get("summary")
        )
        if not summary:
            continue
        normalized = {
            "summary": summary,
            "confidence": str(row.get("confidence") or row.get("eligibilitySummaryConfidence") or "medium"),
            "source": str(row.get("source") or row.get("eligibilitySummarySource") or "codex_llm_override"),
        }
        for key in override_keys(row):
            out[key] = normalized
    return out


def apply_summary(case: dict[str, Any], summary: dict[str, Any], *, source: str) -> None:
    text = compact_single_line(summary.get("summary"))
    if not text:
        return
    case["eligibilityLlmSummary"] = text
    case["eligibilityDisplaySummary"] = text
    case["eligibilitySummaryConfidence"] = summary.get("confidence") or "medium"
    case["eligibilitySummarySource"] = summary.get("source") or source


def add_llm_summaries(
    cases: list[dict[str, Any]],
    *,
    mode: str,
    model: str,
    base_url: str,
    overrides: dict[str, dict[str, Any]],
) -> int:
    count = 0
    for case in cases:
        if case.get("status") != "extracted":
            continue
        summary = None
        for key in override_keys(case):
            summary = overrides.get(key)
            if summary:
                break
        if summary:
            apply_summary(case, summary, source="codex_llm_override")
            count += 1
            continue
        if mode == "openai":
            summary = openai_summarize(case, model=model, base_url=base_url)
            apply_summary(case, summary, source="openai_responses")
            count += 1
    return count


def build_report(
    manifest: list[dict[str, Any]],
    out_dir: Path,
    *,
    llm_summary_mode: str,
    llm_model: str,
    openai_base_url: str,
    llm_summary_overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
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
    llm_summary_count = add_llm_summaries(
        cases,
        mode=llm_summary_mode,
        model=llm_model,
        base_url=openai_base_url,
        overrides=llm_summary_overrides,
    )
    return {
        "caseCount": len(cases),
        "extractedCount": extracted,
        "notFoundCount": len(cases) - extracted,
        "llmSummaryCount": llm_summary_count,
        "llmSummaryMode": llm_summary_mode,
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
        llm_summary = case.get("eligibilityLlmSummary") or case.get("eligibilityDisplaySummary") or ""
        if llm_summary:
            lines.extend(["### LLM summary", "", llm_summary, ""])
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
    parser.add_argument(
        "--llm-summary-mode",
        choices=("none", "openai"),
        default="none",
        help="Use an LLM to summarize extracted eligibility sections.",
    )
    parser.add_argument("--llm-summary-overrides", type=Path, help="JSON summaries generated by Codex or another LLM.")
    parser.add_argument("--openai-model", default=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--openai-base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        raise SystemExit("--manifest must contain a JSON array")
    overrides = load_llm_summary_overrides(args.llm_summary_overrides)
    report = build_report(
        manifest,
        args.mineru_out,
        llm_summary_mode=args.llm_summary_mode,
        llm_model=args.openai_model,
        openai_base_url=args.openai_base_url,
        llm_summary_overrides=overrides,
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.md_out:
        write_markdown(report, args.md_out)
    print(json.dumps({k: report[k] for k in ("caseCount", "extractedCount", "notFoundCount", "llmSummaryCount")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
