#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_DIR = PROJECT_ROOT / "out/navicus_database"
DEFAULT_DB = DEFAULT_DB_DIR / "navicus_proposals.sqlite"
DEFAULT_OUT = PROJECT_ROOT / "Navicus-Reserch"


def load_db_server_module(server_py: Path) -> Any:
    spec = importlib.util.spec_from_file_location("navicus_db_server_static_export", server_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load server module: {server_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: Any, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    else:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    path.write_text(text + "\n", encoding="utf-8")


def write_json_gzip(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    with gzip.open(path, "wb", compresslevel=9) as fh:
        fh.write(raw)


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, dict) else {}


def require_release_go(run_date: str) -> dict[str, Any]:
    filtered_dir = PROJECT_ROOT / "out/navicus_filtered" / run_date
    source_dir = PROJECT_ROOT / "out/navicus_sources" / run_date
    research_dir = PROJECT_ROOT / "out/navicus_research" / run_date
    artifacts = {
        "releaseDecision": load_json_file(filtered_dir / "release_go_decision_v12_4.json"),
        "qualityReport": load_json_file(filtered_dir / "quality_report.json"),
        "csvGoAudit": load_json_file(filtered_dir / "csv_go_audit_report.json"),
        "top20Precision": load_json_file(filtered_dir / "top20_precision_report.json"),
        "knownPositiveReplay": load_json_file(source_dir / "known_positive_replay/replay_report.json"),
        "schemaPreflight": load_json_file(research_dir / "schema_preflight_report.json"),
        "waveStatus": load_json_file(research_dir / "wave_status.json"),
        "externalPortalRecallAudit": load_json_file(research_dir / "external_portal_recall_audit.json"),
    }
    release = artifacts["releaseDecision"]
    if release.get("decision") != "GO" or release.get("passed") is not True:
        raise SystemExit(f"Release-GO artifact missing or not GO: {filtered_dir / 'release_go_decision_v12_4.json'}")
    return artifacts


def release_summary(artifacts: dict[str, Any]) -> dict[str, Any]:
    release = artifacts.get("releaseDecision") or {}
    csv_go = artifacts.get("csvGoAudit") or {}
    top20 = artifacts.get("top20Precision") or {}
    known = artifacts.get("knownPositiveReplay") or {}
    quality = artifacts.get("qualityReport") or {}
    preflight = artifacts.get("schemaPreflight") or {}
    external_recall = artifacts.get("externalPortalRecallAudit") or {}
    summary = release.get("summary") if isinstance(release.get("summary"), dict) else {}
    out = {
        "decision": release.get("decision"),
        "passed": release.get("passed"),
        "qualityPassed": quality.get("passed"),
        "csvDecision": csv_go.get("decision"),
        "top20Precision": top20.get("top20_precision"),
        "knownPositiveRecall": known.get("known_positive_replay_recall") or known.get("recall"),
        "schemaPreflightPassed": preflight.get("passed"),
        "candidatePromoteEligibleCount": summary.get("candidate_promote_eligible_count") or csv_go.get("candidate_promote_eligible_count"),
        "salesPromoteEligibleCount": summary.get("sales_promote_eligible_count") or csv_go.get("sales_promote_eligible_count"),
        "activeishSnsCandidateCount": summary.get("activeish_sns_candidate_count") or csv_go.get("activeish_sns_candidate_count"),
        "activeishSnsOperationCount": summary.get("activeish_sns_operation_count") or csv_go.get("activeish_sns_operation_count"),
    }
    if external_recall:
        out["externalPortalRecall"] = {
            "caseCount": external_recall.get("case_count", 0),
            "includedInRankedFinal": external_recall.get("included_in_ranked_final_count", 0),
            "notFound": external_recall.get("not_found_count", 0),
            "sourceSeenNotRanked": external_recall.get("source_seen_not_ranked_count", 0),
        }
    return out


def flatten_index(indexed: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rows in indexed.values():
        out.extend(rows)
    return out


def slim_material(row: dict[str, Any]) -> dict[str, Any]:
    evidence = str(row.get("evidence") or "").replace("\r", " ").replace("\n", " ").strip()
    if len(evidence) > 320:
        evidence = evidence[:320].rstrip() + "..."
    return {
        "canonical_id": row.get("canonical_id"),
        "title": row.get("title"),
        "url": row.get("url"),
        "source_type": row.get("source_type"),
        "evidence": evidence,
        "confidence": row.get("confidence"),
        "run_id": row.get("run_id"),
    }


def slim_similar(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_id": row.get("canonical_id"),
        "title": row.get("title"),
        "issuer": row.get("issuer"),
        "fiscal_year": row.get("fiscal_year"),
        "url": row.get("url"),
        "result_url": row.get("result_url"),
        "winner_name": row.get("winner_name"),
        "similarity_reason": row.get("similarity_reason"),
        "observed_date": row.get("observed_date"),
        "confidence": row.get("confidence"),
        "run_id": row.get("run_id"),
    }


SUMMARY_KEEP_KEYS = {
    "summary",
    "rawSummary",
    "rawTitle",
    "labels",
    "decision",
    "priority",
    "stopped",
    "stopReason",
    "stopDisplayReason",
    "mainRisk",
    "proposalDeadline",
    "proposal_deadline",
    "submissionDeadline",
    "submission_deadline",
    "documentSubmissionDeadline",
    "document_submission_deadline",
    "deadlineText",
    "deadlineMilestones",
    "participationDeadline",
    "participation_deadline",
    "questionDeadline",
    "question_deadline",
    "briefingDeadline",
    "briefing_deadline",
    "answerDeadline",
    "answer_deadline",
    "budgetText",
    "budget",
    "budgetYen",
    "budgetStatus",
    "budgetSourceUrl",
    "budgetEvidenceSnippet",
    "upperLimitAmount",
    "upper_limit_amount",
    "upperLimitAmountYen",
    "upper_limit_amount_yen",
    "amounts",
    "estimatedPrice",
    "scheduledPrice",
    "contractAmountYen",
    "awardAmountYen",
    "criteria",
    "bidderQualificationSummary",
    "eligibilitySummary",
    "qualificationSummary",
    "eligibility",
    "eligibilityStatus",
    "eligibilityReason",
    "eligibilityNextAction",
    "eligibilitySourceUrl",
    "historicalSimilaritySummary",
    "proposalPageUrl",
    "titleUrl",
    "sourceUrl",
    "confirmPoints",
    "why",
    "originStatus",
    "originDetail",
}


def compact_text(value: Any, *, limit: int = 420) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def compact_value(value: Any, *, list_limit: int = 8, text_limit: int = 420) -> Any:
    if isinstance(value, str):
        return compact_text(value, limit=text_limit)
    if isinstance(value, list):
        return [compact_value(item, text_limit=text_limit) for item in value[:list_limit]]
    if isinstance(value, dict):
        return {key: compact_value(item, text_limit=text_limit) for key, item in value.items() if item not in ("", None, [], {})}
    return value


FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９，,．", "0123456789,,.")
BUDGET_UNKNOWN_VALUES = {"", "0", "0円", "unknown", "not_found", "none", "null", "未確認", "不明"}
BUDGET_LABEL_RE = re.compile(
    r"(?:提案限度額|提案上限額|契約限度額|契約上限額|委託料の上限額|委託上限額|上限額|限度額|予算額|予定価格|予定金額)"
    r"[^0-9０-９]{0,35}"
    r"(?:金\s*)?"
    r"([0-9０-９][0-9０-９,，\.．]*)\s*(千円|万円|億円|円)"
)
QUALIFICATION_TERM_RE = re.compile(
    r"入札参加資格|参加資格|応募資格|資格要件|競争入札参加資格|資格者名簿|名簿|"
    r"業種区分|営業種目|登録|地域要件|県内|市内|町内|本店|本社|支店|営業所|"
    r"実績|許可|認定|共同企業体|JV|共同提案|単独又は共同|所在地を問わない|"
    r"法人又は団体|全国|随時申請"
)
UNKNOWN_QUALIFICATION_RE = re.compile(
    r"未確認|不明|要確認|UNKNOWN|Local candidate data does not include|参加資格の明示的な可否が未確認"
)
TITLE_PUNCT_RE = re.compile(r"[\s　「」『』（）()【】\[\]・_＿\-‐ー〜～:：,，.．/／]+")
GENERIC_TITLE_TOKENS = {
    "令和8年度",
    "令和8年",
    "2026年度",
    "2026年",
    "業務",
    "業務委託",
    "公告",
    "募集",
    "公募",
    "入札公告",
    "企画提案",
}


def normalize_number_text(value: Any) -> str:
    return str(value or "").translate(FULLWIDTH_DIGITS).replace(",", "").strip()


def yen_from_number_and_unit(number_text: Any, unit: str = "円") -> int | None:
    normalized = normalize_number_text(number_text)
    if not normalized:
        return None
    try:
        amount = float(normalized)
    except ValueError:
        return None
    if amount <= 0:
        return None
    multiplier = {"円": 1, "千円": 1000, "万円": 10000, "億円": 100000000}.get(unit, 1)
    return int(round(amount * multiplier))


def yen_from_raw(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"([0-9０-９][0-9０-９,，\.．]*)\s*(千円|万円|億円|円)?", text)
    if not match:
        return None
    return yen_from_number_and_unit(match.group(1), match.group(2) or "円")


def format_yen(yen: int | None) -> str:
    return f"{yen:,}円" if yen and yen > 0 else ""


def extract_budget_from_text(*values: Any) -> tuple[int | None, str, str]:
    for value in values:
        text = compact_text(value, limit=1800)
        if not text:
            continue
        match = BUDGET_LABEL_RE.search(text)
        if not match:
            continue
        yen = yen_from_number_and_unit(match.group(1), match.group(2))
        if yen:
            return yen, format_yen(yen), compact_text(match.group(0), limit=180)
    return None, "", ""


def budget_value_is_unknown(value: Any) -> bool:
    text = str(value or "").strip()
    return text.lower() in BUDGET_UNKNOWN_VALUES


def load_observation_records(db_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    import sqlite3

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        for row in con.execute("SELECT canonical_id, run_id, proposal_json FROM proposal_observations"):
            payload = load_json_text(row["proposal_json"])
            if isinstance(payload, dict):
                records[(str(row["canonical_id"]), str(row["run_id"]))] = payload
    return records


def load_json_text(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def budget_status_label(source: dict[str, Any]) -> str:
    upper_status = str(source.get("upper_limit_status") or "").strip()
    scheduled_status = str(source.get("scheduled_price_status") or "").strip()
    if upper_status == "found":
        return "上限額確認済み"
    if upper_status == "not_found":
        return "上限額記載なし"
    if scheduled_status == "not_public":
        return "予定価格等は非公表"
    if upper_status == "unclear":
        return "金額要確認"
    return "金額要確認"


def enrich_budget(public: dict[str, Any], source: dict[str, Any]) -> None:
    if not source:
        return
    summary = public.get("summary") if isinstance(public.get("summary"), dict) else {}
    current_text = summary.get("budgetText")
    current_budget = summary.get("budget")
    if not budget_value_is_unknown(current_text) and not budget_value_is_unknown(current_budget):
        return

    amounts = source.get("amounts") if isinstance(source.get("amounts"), dict) else {}
    yen = (
        yen_from_raw(source.get("corrected_budget_yen"))
        or yen_from_raw(source.get("upper_limit_amount_yen"))
        or yen_from_raw(amounts.get("upper_limit_amount_yen"))
        or yen_from_raw(source.get("scheduled_price_yen"))
        or yen_from_raw(source.get("upper_limit_amount"))
        or yen_from_raw(amounts.get("upper_limit_amount"))
        or yen_from_raw(source.get("scheduled_price"))
    )
    evidence = ""
    if yen:
        label = format_yen(yen)
    else:
        yen, label, evidence = extract_budget_from_text(
            source.get("upper_limit_evidence_snippet"),
            source.get("contract_period_text"),
            source.get("overview"),
        )
    if label:
        summary["budgetText"] = label
        summary["budget"] = round((yen or 0) / 10000) if yen else ""
        summary["budgetYen"] = yen
        summary["budgetStatus"] = "found"
        summary["budgetSourceUrl"] = (
            source.get("upper_limit_evidence_source_url")
            or source.get("contract_period_source_url")
            or source.get("source_url")
            or source.get("root_notice_url")
            or source.get("url")
            or ""
        )
        if evidence:
            summary["budgetEvidenceSnippet"] = evidence
    else:
        summary["budgetText"] = budget_status_label(source)
        summary["budget"] = ""
        summary["budgetStatus"] = str(source.get("upper_limit_status") or source.get("scheduled_price_status") or "needs_review")
    public["summary"] = summary


def normalize_budget_summary(summary: dict[str, Any]) -> dict[str, Any]:
    out = dict(summary)
    status = str(out.get("budgetStatus") or "").strip()
    if budget_value_is_unknown(out.get("budgetText")):
        if status == "found":
            out["budgetText"] = "金額確認済み"
        elif status == "not_found":
            out["budgetText"] = "上限額記載なし"
        elif status in {"not_public", "scheduled_price_not_public"}:
            out["budgetText"] = "予定価格等は非公表"
        else:
            out["budgetText"] = "金額要確認"
    if budget_value_is_unknown(out.get("budget")):
        out["budget"] = ""
    return out


def qualification_value_is_unknown(value: Any) -> bool:
    text = compact_text(value, limit=500)
    return not text or bool(UNKNOWN_QUALIFICATION_RE.search(text))


def qualification_snippet_from_text(value: Any) -> str:
    text = compact_text(value, limit=2400)
    if not text:
        return ""
    match = QUALIFICATION_TERM_RE.search(text)
    if not match:
        return ""
    start = max(0, match.start() - 180)
    end = min(len(text), match.end() + 520)
    for sep in ("。", "】", "）", ")"):
        pos = text.rfind(sep, 0, match.start())
        if pos >= 0 and pos > match.start() - 240:
            start = pos + 1
            break
    for sep in ("。", "】"):
        pos = text.find(sep, match.end())
        if pos >= 0 and pos < match.end() + 520:
            end = pos + 1
            break
    snippet = text[start:end].strip(" /　、。")
    return compact_text(snippet, limit=360)


def extract_qualification_snippet(source: dict[str, Any], materials: list[dict[str, Any]]) -> tuple[str, str]:
    source_fields = [
        "bidderQualificationSummary",
        "eligibilitySummary",
        "eligibility",
        "participation_eligibility",
        "bidEligibility",
        "contract_period_text",
        "submission_method_evidence_snippet",
        "overview",
        "scored_text_prefix",
        "text",
    ]
    for field in source_fields:
        snippet = qualification_snippet_from_text(source.get(field))
        if snippet:
            return snippet, str(source.get(f"{field}_source_url") or source.get("source_url") or source.get("root_notice_url") or source.get("url") or "")
    for material in materials:
        snippet = qualification_snippet_from_text(
            " ".join(str(material.get(key) or "") for key in ("evidence", "title", "source_json"))
        )
        if snippet:
            return snippet, str(material.get("url") or "")
    return "", ""


def normalize_match_text(value: Any) -> str:
    text = compact_text(value, limit=1200).lower()
    return TITLE_PUNCT_RE.sub("", text)


def normalize_url_key(value: Any) -> str:
    return str(value or "").strip().rstrip("/")


def url_domain(value: Any) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    return parsed.netloc.lower()


def title_tokens(value: Any) -> set[str]:
    raw = compact_text(value, limit=1200).lower()
    tokens = {
        token
        for token in TITLE_PUNCT_RE.split(raw)
        if len(token) >= 5 and token not in GENERIC_TITLE_TOKENS
    }
    return tokens


def load_mineru_eligibility_overrides(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        return []
    overrides: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict) or case.get("status") != "extracted":
            continue
        snippet = compact_text(case.get("eligibilitySnippet"), limit=520)
        if not snippet:
            continue
        title_key = normalize_match_text(case.get("title"))
        source_url = normalize_url_key(case.get("url"))
        overrides.append(
            {
                "canonicalId": case.get("canonical_id") or case.get("canonicalId"),
                "title": case.get("title"),
                "titleKey": title_key,
                "titleTokens": sorted(title_tokens(case.get("title"))),
                "sourceUrl": source_url,
                "snippet": snippet,
                "slug": case.get("slug"),
            }
        )
    return overrides


def proposal_url_keys(public: dict[str, Any], source: dict[str, Any], materials: list[dict[str, Any]]) -> set[str]:
    summary = public.get("summary") if isinstance(public.get("summary"), dict) else {}
    keys: set[str] = set()
    for container in (public, summary, source):
        for field in (
            "url",
            "sourceUrl",
            "source_url",
            "titleUrl",
            "title_url",
            "proposalPageUrl",
            "proposal_page_url",
            "root_notice_url",
        ):
            key = normalize_url_key(container.get(field))
            if key:
                keys.add(key)
    for material in materials:
        key = normalize_url_key(material.get("url"))
        if key:
            keys.add(key)
    return keys


def proposal_domains(public: dict[str, Any], source: dict[str, Any], materials: list[dict[str, Any]]) -> set[str]:
    return {domain for domain in (url_domain(url) for url in proposal_url_keys(public, source, materials)) if domain}


def find_mineru_eligibility_override(
    public: dict[str, Any],
    source: dict[str, Any],
    materials: list[dict[str, Any]],
    overrides: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not overrides:
        return None
    canonical_id = str(public.get("canonical_id") or "")
    for override in overrides:
        if override.get("canonicalId") and str(override["canonicalId"]) == canonical_id:
            return override

    urls = proposal_url_keys(public, source, materials)
    for override in overrides:
        if override.get("sourceUrl") and override["sourceUrl"] in urls:
            return override

    title_keys = [
        normalize_match_text(public.get("title")),
        normalize_match_text(public.get("rawTitle")),
        normalize_match_text(source.get("title")),
        normalize_match_text(source.get("rawTitle")),
    ]
    domains = proposal_domains(public, source, materials)
    for override in overrides:
        key = str(override.get("titleKey") or "")
        if len(key) < 8:
            continue
        for title_key in title_keys:
            if len(title_key) >= 8 and (key in title_key or title_key in key):
                return override
        override_domain = url_domain(override.get("sourceUrl"))
        if override_domain and domains and override_domain not in domains:
            continue
        override_tokens = set(override.get("titleTokens") or [])
        if override_tokens:
            for raw_title in (public.get("title"), public.get("rawTitle"), source.get("title"), source.get("rawTitle")):
                if override_tokens & title_tokens(raw_title):
                    return override
    return None


def apply_mineru_eligibility(public: dict[str, Any], override: dict[str, Any] | None) -> bool:
    if not override:
        return False
    summary = public.get("summary") if isinstance(public.get("summary"), dict) else {}
    current = (
        summary.get("bidderQualificationSummary")
        or summary.get("eligibilitySummary")
        or summary.get("qualificationSummary")
        or summary.get("eligibility")
    )
    if current and not qualification_value_is_unknown(current):
        return False
    text = f"公式PDF抽出候補（要確認）: {override['snippet']}"
    summary["bidderQualificationSummary"] = text
    summary["eligibilitySummary"] = text
    summary["eligibilityStatus"] = "NEEDS_CONFIRMATION"
    summary["eligibilityReason"] = "MinerUで公式PDFの参加資格・入札者資格条項を抽出。"
    summary["eligibilityNextAction"] = "等級、名簿登録、地域要件、実績要件、共同提案可否を原文で最終確認する。"
    if override.get("sourceUrl"):
        summary["eligibilitySourceUrl"] = override["sourceUrl"]
    public["summary"] = summary
    return True


def enrich_eligibility(public: dict[str, Any], source: dict[str, Any], materials: list[dict[str, Any]]) -> None:
    summary = public.get("summary") if isinstance(public.get("summary"), dict) else {}
    current = (
        summary.get("bidderQualificationSummary")
        or summary.get("eligibilitySummary")
        or summary.get("qualificationSummary")
        or summary.get("eligibility")
    )
    if current and not qualification_value_is_unknown(current):
        return
    snippet, source_url = extract_qualification_snippet(source, materials)
    if not snippet:
        return
    text = f"要確認: 公式資料に資格記載候補あり - {snippet}"
    summary["bidderQualificationSummary"] = text
    summary["eligibilitySummary"] = text
    summary["eligibilityStatus"] = "NEEDS_CONFIRMATION"
    summary["eligibilityReason"] = "公式資料または取得済みevidence内に参加資格・名簿・実績等の記載候補を検出。"
    summary["eligibilityNextAction"] = "該当する公式資料の資格条項を確認し、地域要件・名簿登録・業種区分・JV可否を確定する。"
    if source_url:
        summary["eligibilitySourceUrl"] = source_url
    public["summary"] = summary


def slim_summary(summary: dict[str, Any]) -> dict[str, Any]:
    summary = normalize_budget_summary(summary)
    out: dict[str, Any] = {}
    for key in SUMMARY_KEEP_KEYS:
        value = summary.get(key)
        if value in ("", None, [], {}):
            continue
        out[key] = compact_value(value)
    return out


def compact_search_text(proposal: dict[str, Any]) -> str:
    summary = proposal.get("summary") if isinstance(proposal.get("summary"), dict) else {}
    values = [
        proposal.get("title"),
        proposal.get("issuer"),
        proposal.get("latest_grade"),
        proposal.get("best_grade"),
        proposal.get("latest_status"),
        proposal.get("updated_run_id"),
        proposal.get("first_seen_run_date"),
        proposal.get("historical_similarity_status"),
        summary.get("summary"),
        summary.get("budgetText"),
        summary.get("budget"),
        summary.get("bidderQualificationSummary"),
        summary.get("eligibilitySummary"),
        summary.get("eligibilityReason"),
        summary.get("eligibilityNextAction"),
        summary.get("historicalSimilaritySummary"),
        " ".join(str(x) for x in summary.get("labels", []) if x),
        " ".join(str(x) for x in summary.get("why", [])[:4] if x),
        " ".join(str(x) for x in summary.get("confirmPoints", [])[:4] if x),
    ]
    return compact_text(" ".join(str(value or "") for value in values), limit=2200).lower()


def slim_proposal(public: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "canonical_id",
        "canonical_case_key",
        "updated_run_id",
        "title",
        "rawTitle",
        "issuer",
        "source_url",
        "latest_rank",
        "latest_grade",
        "latest_status",
        "historical_similarity_status",
        "result_followup_status",
        "updated_at",
        "first_seen_run_id",
        "first_seen_run_date",
        "is_new",
        "newly_discovered",
        "grade_history",
        "best_grade",
        "best_rank",
        "best_grade_run_id",
        "best_grade_run_date",
        "best_grade_run_label",
        "deadlineBucket",
        "isHistoricalAB",
    }
    out = {key: compact_value(public.get(key)) for key in keep if public.get(key) not in ("", None, [], {})}
    summary = public.get("summary") if isinstance(public.get("summary"), dict) else {}
    out["summary"] = slim_summary(summary)
    out["searchText"] = compact_search_text(out)
    return out


def build_snapshot(
    db_path: Path,
    server_module: Any,
    release_artifacts: dict[str, Any],
    mineru_eligibility_overrides: list[dict[str, Any]],
) -> dict[str, Any]:
    database = server_module.ProposalDatabase(db_path)
    data = database.cache()
    observations = load_observation_records(db_path)
    materials_index = {
        canonical_id: rows
        for canonical_id, rows in (data.get("materialsById") or {}).items()
    }
    proposals: list[dict[str, Any]] = []
    mineru_applied = 0
    for row in data["proposals"]:
        public = server_module.public_row(row)
        source = observations.get((str(row.get("canonical_id")), str(row.get("updated_run_id"))), {})
        materials_for_case = materials_index.get(str(row.get("canonical_id")), [])
        enrich_budget(public, source)
        enrich_eligibility(public, source, materials_for_case)
        mineru_override = find_mineru_eligibility_override(public, source, materials_for_case, mineru_eligibility_overrides)
        if apply_mineru_eligibility(public, mineru_override):
            mineru_applied += 1
        public["deadlineBucket"] = row.get("_deadline_bucket", "all")
        public["isHistoricalAB"] = bool(server_module.is_historical_ab(row))
        proposals.append(slim_proposal(public))

    similar = [slim_similar(row) for row in flatten_index(data["similarById"])]
    materials = [slim_material(row) for row in flatten_index(data["materialsById"])]
    followups = flatten_index(data["followupsById"])
    latest_run = data["runs"][0] if data.get("runs") else {}
    stats = {
        "filtered": len(proposals),
        "total": len(proposals),
        "tabCounts": data.get("tabCounts") or {},
        "new": sum(1 for p in proposals if p.get("is_new") or p.get("newly_discovered") or p.get("isNew")),
        "bplus": sum(1 for p in proposals if p.get("latest_grade") in {"S", "A", "B"}),
        "bestBplus": sum(1 for p in proposals if (p.get("best_grade") or p.get("latest_grade")) in {"S", "A", "B"}),
        "historicalAB": sum(1 for p in proposals if p.get("isHistoricalAB")),
        "similar": len({row.get("canonical_id") for row in similar if row.get("canonical_id")}),
        "materials": len(materials),
        "favorite": 0,
        "viewed": 0,
        "exportedAt": data["exportedAt"],
        "latestRunId": latest_run.get("run_id", ""),
        "releaseDecision": (release_artifacts.get("releaseDecision") or {}).get("decision", ""),
        "mineruEligibilityApplied": mineru_applied,
    }
    external_recall = release_artifacts.get("externalPortalRecallAudit") or {}
    if external_recall:
        stats["externalPortalRecall"] = {
            "caseCount": external_recall.get("case_count", 0),
            "includedInRankedFinal": external_recall.get("included_in_ranked_final_count", 0),
            "notFound": external_recall.get("not_found_count", 0),
            "sourceSeenNotRanked": external_recall.get("source_seen_not_ranked_count", 0),
        }
    stats["existing"] = max(0, stats["total"] - stats["new"])
    release_gate = release_summary(release_artifacts)
    return {
        "schemaVersion": "navicus_static_pages_v1",
        "sourceSchemaVersion": server_module.SCHEMA_VERSION,
        "exportedAt": data["exportedAt"],
        "releaseGate": release_gate,
        "latestRun": latest_run,
        "runs": data["runs"],
        "proposals": proposals,
        "similarProposals": similar,
        "proposalMaterials": materials,
        "resultFollowups": followups,
        "stats": stats,
    }


def replace_function(source: str, signature: str, replacement: str) -> str:
    start = source.find(signature)
    if start < 0:
        raise RuntimeError(f"function signature not found: {signature}")
    brace = source.find("{", start)
    if brace < 0:
        raise RuntimeError(f"function body not found: {signature}")
    depth = 0
    in_quote = ""
    escape = False
    for idx in range(brace, len(source)):
        ch = source[idx]
        if in_quote:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_quote:
                in_quote = ""
            continue
        if ch in {"'", '"', "`"}:
            in_quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[:start] + replacement.rstrip() + "\n" + source[idx + 1 :]
    raise RuntimeError(f"function end not found: {signature}")


STATIC_HELPERS = r"""
let FULL_DATA = null;
let FULL_SIMILAR_BY_ID = new Map();
let FULL_FOLLOWUPS_BY_ID = new Map();
let FULL_MATERIALS_BY_ID = new Map();

async function loadStaticData() {
  if (FULL_DATA) return FULL_DATA;
  const index = await fetchJson('data/index.json');
  const snapshotPath = index.latest && index.latest.snapshot;
  if (!snapshotPath) throw new Error('latest snapshot is not configured');
  FULL_DATA = await fetchJson(`data/${snapshotPath}`);
  FULL_DATA.index = index;
  FULL_SIMILAR_BY_ID = indexByCanonical(FULL_DATA.similarProposals || []);
  FULL_FOLLOWUPS_BY_ID = indexByCanonical(FULL_DATA.resultFollowups || []);
  FULL_MATERIALS_BY_ID = indexByCanonical(FULL_DATA.proposalMaterials || []);
  return FULL_DATA;
}

async function fetchJson(path) {
  const response = await fetch(path, {cache: 'no-store'});
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  if (!path.endsWith('.gz')) return response.json();
  if (!response.body || !('DecompressionStream' in window)) {
    throw new Error('This browser cannot read compressed snapshot data. Use a current Chrome, Edge, Safari, or Firefox.');
  }
  const stream = response.body.pipeThrough(new DecompressionStream('gzip'));
  const text = await new Response(stream).text();
  return JSON.parse(text);
}

function rankNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 999999;
}

function parseDeadlineDate(value) {
  const m = String(value || '').match(/(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
  if (!m) return 9999999999999;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime();
}

function formatExportedAt(value) {
  const text = String(value || '');
  const m = text.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}Z` : text;
}

function fullSimilarFor(id) { return FULL_SIMILAR_BY_ID.get(id) || []; }
function fullFollowupsFor(id) { return FULL_FOLLOWUPS_BY_ID.get(id) || []; }
function fullMaterialsFor(id) { return FULL_MATERIALS_BY_ID.get(id) || []; }

function filteredStaticRows(data) {
  const q = $('query').value.trim().toLowerCase();
  const grade = $('grade').value;
  const gradeBasis = $('gradeBasis').value || 'latest';
  const state = $('state').value;
  const favs = favorites;
  const seen = viewed;
  return (data.proposals || []).filter(p => {
    const cid = p.canonical_id;
    const filterGrade = gradeBasis === 'best' ? (p.best_grade || p.latest_grade) : p.latest_grade;
    if (deadlineTab !== 'all' && p.deadlineBucket !== deadlineTab) return false;
    if (quickMode === 'bplus' && !['S','A','B'].includes(filterGrade)) return false;
    if (quickMode === 'historical_ab' && !p.isHistoricalAB) return false;
    if (q && !String(p.searchText || '').toLowerCase().includes(q)) return false;
    if (grade && filterGrade !== grade) return false;
    if (state === 'favorite' && !favs.has(cid)) return false;
    if (state === 'new' && !(p.is_new || p.newly_discovered || p.isNew)) return false;
    if (state === 'viewed' && !seen.has(cid)) return false;
    if (state === 'unviewed' && seen.has(cid)) return false;
    if (state === 'similar' && !fullSimilarFor(cid).length) return false;
    if (state === 'followup' && !fullFollowupsFor(cid).length) return false;
    if (state === 'historical_ab' && !p.isHistoricalAB) return false;
    return true;
  });
}

function sortedStaticRows(rows) {
  const key = sortKey || 'rank';
  const copy = rows.slice();
  const keyFn = key === 'best-grade'
    ? p => [gradeRank(p.best_grade || p.latest_grade), rankNumber(p.best_rank || p.latest_rank), rankNumber(p.latest_rank)]
    : key === 'grade'
      ? p => [gradeRank(p.latest_grade), rankNumber(p.latest_rank)]
      : key === 'run-rank'
        ? p => [rankNumber(p.latest_rank), gradeRank(p.latest_grade)]
        : key === 'deadline'
          ? p => [parseDeadlineDate(proposalDeadlineValue(p)), gradeRank(p.latest_grade), rankNumber(p.latest_rank)]
          : key === 'new'
            ? p => [(p.is_new || p.newly_discovered || p.isNew) ? 0 : 1, rankNumber(p.latest_rank)]
            : key === 'issuer'
              ? p => [String(p.issuer || ''), rankNumber(p.latest_rank)]
              : key === 'title'
                ? p => [String(p.title || ''), rankNumber(p.latest_rank)]
                : p => [gradeRank(p.latest_grade), rankNumber(p.latest_rank)];
  copy.sort((a, b) => {
    const ka = keyFn(a);
    const kb = keyFn(b);
    for (let i = 0; i < Math.max(ka.length, kb.length); i += 1) {
      if (ka[i] < kb[i]) return -1;
      if (ka[i] > kb[i]) return 1;
    }
    return 0;
  });
  return copy;
}

function staticStats(data, filtered) {
  const proposals = data.proposals || [];
  const allIds = new Set(proposals.map(p => p.canonical_id));
  const base = data.stats || {};
  return {
    ...base,
    filtered,
    total: proposals.length,
    tabCounts: base.tabCounts || {},
    favorite: [...favorites].filter(id => allIds.has(id)).length,
    viewed: [...viewed].filter(id => allIds.has(id)).length,
    exportedAt: data.exportedAt,
    latestRunId: (data.latestRun && data.latestRun.run_id) || base.latestRunId || '',
  };
}
"""


STATIC_RENDER = r"""
async function render() {
  const seq = ++requestSeq;
  const firstLoad = !FULL_DATA;
  if (firstLoad) {
    $('cards').innerHTML = '<div class="empty">静的データを読み込み中...</div>';
  }
  try {
    const data = await loadStaticData();
    if (seq !== requestSeq) return;
    const rows = sortedStaticRows(filteredStaticRows(data));
    const total = rows.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    currentPage = Math.max(1, Math.min(currentPage, totalPages));
    const start = (currentPage - 1) * pageSize;
    const end = Math.min(total, start + pageSize);
    const pageRows = rows.slice(start, end);
    const pageIds = pageRows.map(row => row.canonical_id);
    const similar = pageIds.flatMap(id => fullSimilarFor(id));
    const materials = pageIds.flatMap(id => fullMaterialsFor(id));
    const followups = pageIds.flatMap(id => fullFollowupsFor(id));
    setSnapshot({
      ...data,
      proposals: pageRows,
      similarProposals: similar,
      proposalMaterials: materials,
      resultFollowups: followups,
      stats: staticStats(data, total),
      page: currentPage,
      pageSize,
      totalPages,
      start,
      end,
    });
    renderDeadlineTabs();
    renderStats();
    $('resultLabel').textContent = `${total ? start + 1 : 0}-${end}件 / 全${(SNAPSHOT.stats && SNAPSHOT.stats.total) || 0}件`;
    $('cards').innerHTML = pageRows.map(renderCard).join('') || '<div class="empty">該当案件がありません。</div>';
    renderPager(total, totalPages, start, end);
    renderRuns();
  } catch (error) {
    if (seq !== requestSeq) return;
    $('cards').innerHTML = `<div class="empty">静的データを読み込めません。<br><span class="small">${esc(error.message || error)}</span></div>`;
    $('resultCount').textContent = 0;
    $('resultLabel').textContent = 'データ未読込';
  }
}
"""


STATIC_BUDGET_SUMMARY = r"""
function budgetSummary(p) {
  const s = p.summary || {};
  const values = [
    s.budgetText,
    s.upperLimitAmount,
    s.upper_limit_amount,
    s.amounts && (s.amounts.upper_limit_amount || s.amounts.upperLimitAmount),
    s.budgetYen,
    s.budget,
    s.upperLimitAmountYen,
    s.upper_limit_amount_yen,
    s.estimatedPrice,
    s.scheduledPrice,
    s.contractAmountYen,
    s.awardAmountYen,
    p.budget
  ];
  const amount = values.map(formatYen).find(Boolean) || '';
  const status = String(s.budgetStatus || '').toLowerCase();
  const unresolved = /記載なし|非公表|要確認|未確認|不明|unknown|not_found/.test(amount);
  const found = status === 'found' || (!!amount && !unresolved && /円|千円|万円|億円/.test(amount));
  const grade = (s.criteria && s.criteria.budget) || s.budgetGrade || '';
  const meta = found
    ? (grade ? `予算評価: ${grade}` : '公式資料から抽出')
    : (amount ? '金額情報の公開状況' : '公式資料で要確認');
  return {amount: amount || '未確認', cls: found ? '' : 'unknown', meta};
}
"""


def build_static_app(source_js: str) -> str:
    if "async function render()" not in source_js:
        raise RuntimeError("source app.js does not contain async render")
    patched = source_js.replace("function requestPayload() {", STATIC_HELPERS + "\nfunction requestPayload() {")
    patched = replace_function(patched, "async function render()", STATIC_RENDER)
    patched = replace_function(patched, "function budgetSummary(p)", STATIC_BUDGET_SUMMARY)
    patched = patched.replace(
        "if (!text || text === '0' || text === '0円' || text === '未確認' || text === '不明') return '';",
        "if (!text || ['0','0円','未確認','不明','unknown','not_found','none','null'].includes(text.toLowerCase())) return '';",
    )
    patched = patched.replace(
        "['exported', stats.exportedAt || SNAPSHOT.exportedAt || ''],",
        "['Release', stats.releaseDecision || (SNAPSHOT.releaseGate && SNAPSHOT.releaseGate.decision) || ''],\n"
        "    ['外部ポータル監査', stats.externalPortalRecall ? `${stats.externalPortalRecall.includedInRankedFinal || 0}/${stats.externalPortalRecall.caseCount || 0} ranked / 未収録${stats.externalPortalRecall.notFound || 0} / source止まり${stats.externalPortalRecall.sourceSeenNotRanked || 0}` : ''],\n"
        "    ['exported', formatExportedAt(stats.exportedAt || SNAPSHOT.exportedAt || '')],",
    )
    patched = patched.replace(
        "['次アクション', s.eligibilityNextAction || ''],",
        "['次アクション', s.eligibilityNextAction || ''],\n"
        "    ['根拠URL', s.eligibilitySourceUrl || ''],",
    )
    return patched


def build_index_html(source_html: str) -> str:
    html = source_html.replace("<title>NAVICUS Proposal Research DB</title>", "<title>NAVICUS Research Daily DB</title>")
    html = html.replace("<h1>NAVICUS Proposal Research DB</h1>", "<h1>NAVICUS Research Daily DB</h1>")
    html = html.replace('<script src="app.js"></script>', '<script src="assets/app.js"></script>')
    html = html.replace(
        ".db-status .row { display:flex; justify-content:space-between; gap:12px; margin:7px 0; font-size:13px; }",
        ".db-status .row { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.2fr); align-items:flex-start; gap:12px; margin:7px 0; font-size:13px; }\n"
        "    .db-status .row span,.db-status .row strong { min-width:0; }\n"
        "    .db-status .row strong { text-align:right; overflow-wrap:anywhere; word-break:break-all; }",
    )
    html = html.replace(
        "    @media print { body { background:#fff; }",
        "    @media (max-width:820px) { .app,.sidebar,main { max-width:100vw; overflow-x:hidden; } .db-status .row { grid-template-columns:1fr; gap:2px; } .db-status .row strong { text-align:left; } }\n"
        "    @media print { body { background:#fff; }",
    )
    return html


def write_site(out_dir: Path, snapshot: dict[str, Any], db_dir: Path, run_date: str, run_label: str, release_artifacts: dict[str, Any]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "assets").mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    run_rel = Path("runs") / run_date / run_label
    run_dir = out_dir / "data" / run_rel
    run_dir.mkdir(parents=True, exist_ok=True)

    index_html = build_index_html((db_dir / "index.html").read_text(encoding="utf-8"))
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")
    static_app = build_static_app((db_dir / "app.js").read_text(encoding="utf-8"))
    (out_dir / "assets/app.js").write_text(static_app, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    snapshot_path = run_dir / "snapshot.json.gz"
    write_json_gzip(snapshot_path, snapshot)
    old_uncompressed = run_dir / "snapshot.json"
    if old_uncompressed.exists():
        old_uncompressed.unlink()

    run_report = PROJECT_ROOT / "out/navicus_database/runs" / f"{run_date}_{run_label}" / "run_research_rank_db_once_report.json"
    final_audit = PROJECT_ROOT / "out/navicus_database/runs" / f"{run_date}_{run_label}" / "final_database_sales_audit.json"
    if run_report.exists():
        shutil.copy2(run_report, run_dir / "run_research_rank_db_once_report.json")
    if final_audit.exists():
        shutil.copy2(final_audit, run_dir / "final_database_sales_audit.json")
    release_paths = {
        "releaseDecision": "release_go_decision_v12_4.json",
        "qualityReport": "quality_report.json",
        "csvGoAudit": "csv_go_audit_report.json",
        "top20Precision": "top20_precision_report.json",
        "knownPositiveReplay": "known_positive_replay_report.json",
        "schemaPreflight": "schema_preflight_report.json",
        "waveStatus": "wave_status.json",
        "externalPortalRecallAudit": "external_portal_recall_audit.json",
    }
    for key, filename in release_paths.items():
        payload = release_artifacts.get(key)
        if payload:
            public_payload = dict(payload)
            if key == "externalPortalRecallAudit" and public_payload.get("input"):
                public_payload["input"] = Path(str(public_payload["input"])).name
            write_json(run_dir / filename, public_payload, pretty=True)
    external_recall_csv = PROJECT_ROOT / "out/navicus_research" / run_date / "external_portal_recall_audit.csv"
    if external_recall_csv.exists():
        shutil.copy2(external_recall_csv, run_dir / "external_portal_recall_audit.csv")

    latest_run = snapshot.get("latestRun") or {}
    manifest_path = run_rel / "snapshot.json.gz"
    run_entry = {
        "runDate": run_date,
        "runLabel": run_label,
        "runId": latest_run.get("run_id", f"{run_date}_{run_label}"),
        "snapshot": str(manifest_path).replace("\\", "/"),
        "exportedAt": snapshot.get("exportedAt"),
        "proposalCount": len(snapshot.get("proposals") or []),
        "bplus": (snapshot.get("stats") or {}).get("bplus", 0),
        "releaseDecision": (snapshot.get("releaseGate") or {}).get("decision", ""),
        "releaseGate": (snapshot.get("releaseGate") or {}),
    }
    index_path = out_dir / "data/index.json"
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            index = {}
    else:
        index = {}
    runs = [r for r in index.get("runs", []) if r.get("runId") != run_entry["runId"]]
    runs.insert(0, run_entry)
    index = {
        "schemaVersion": "navicus_static_manifest_v1",
        "latest": run_entry,
        "runs": runs[:120],
    }
    write_json(index_path, index, pretty=True)
    write_json(out_dir / "data/latest.json", {"latest": run_entry}, pretty=True)

    readme = f"""# NAVICUS Research Daily DB

Static GitHub Pages export for NAVICUS municipal SNS/proposal research.

- Latest run: `{run_entry['runId']}`
- Release: `{run_entry['releaseDecision']}`
- Latest snapshot: `data/{run_entry['snapshot']}` (gzip-compressed JSON)
- Daily archive: `data/runs/YYYY-MM-DD/<run-label>/`

Update command:

```bash
python3 tools/navicus_pages/export_static_pages.py --run-date YYYY-MM-DD --run-label manual_research
```
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    return run_entry


def write_root_redirect(project_root: Path, target: str) -> None:
    html = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="0; url={target}/">
  <title>NAVICUS Research Daily DB</title>
</head>
<body>
  <p><a href="{target}/">NAVICUS Research Daily DB</a></p>
</body>
</html>
"""
    (project_root / "index.html").write_text(html, encoding="utf-8")
    (project_root / ".nojekyll").write_text("", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export NAVICUS SQLite DB to a static GitHub Pages folder.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--db-dir", type=Path, default=DEFAULT_DB_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--run-label", default="manual_research")
    parser.add_argument(
        "--mineru-eligibility-report",
        type=Path,
        help="Optional MinerU eligibility extraction report JSON.",
    )
    parser.add_argument("--root-redirect", action="store_true")
    args = parser.parse_args()

    server_py = args.db_dir / "server.py"
    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")
    if not server_py.exists():
        raise SystemExit(f"server.py not found: {server_py}")

    release_artifacts = require_release_go(args.run_date)
    server_module = load_db_server_module(server_py)
    mineru_report = args.mineru_eligibility_report or (
        PROJECT_ROOT / "out/navicus_research" / args.run_date / "mineru_eligibility_report.json"
    )
    mineru_overrides = load_mineru_eligibility_overrides(mineru_report)
    snapshot = build_snapshot(args.db, server_module, release_artifacts, mineru_overrides)
    run_entry = write_site(args.out, snapshot, args.db_dir, args.run_date, args.run_label, release_artifacts)
    if args.root_redirect:
        write_root_redirect(PROJECT_ROOT, args.out.name)
    print(json.dumps({"out": str(args.out), "latest": run_entry}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
