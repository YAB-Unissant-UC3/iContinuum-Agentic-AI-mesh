"""Audit the actual returned result against canonical Reader evidence."""

from datetime import datetime, timezone
import hashlib
import json
import re

from mesh import AuditAgent
from mesh.models import Analysis, Citation, Finding
from mesh.conflicts import detect_conflicts
from .source_locations import page_references


def audit_analysis(result, passages, documents=None):
    flags = []
    sources = {(p.document_id, p.number): p.text for p in passages}
    if documents is not None:
        sources = {(d["document_id"], line["line_number"]): line["text"]
                   for d in documents for line in d["lines"]}
    generated = result.get("mode") in {"gemini", "groq"}
    document_lookup = {d["document_id"]: d for d in documents or []}

    def flag(code, target, message, severity="error"):
        flags.append({"code": code, "target": target, "message": message, "severity": severity})

    if result.get("source_redacted"):
        flag("source_redacted", "brief", "Quoted output was withheld because evidence contains a credential.")

    def citations(items, target):
        verified = []
        if not isinstance(items, list) or not items:
            flag("missing_citation", target, "No source citation was provided.")
            return verified
        for cite in items:
            if not isinstance(cite, dict):
                flag("invalid_citation", target, "Citation must be an object.")
                continue
            start, end = cite.get("line_start"), cite.get("line_end")
            if (type(start) is not int or type(end) is not int or start < 1 or end < start
                    or end - start > 19 or (not generated and end != start)):
                flag("invalid_range", target, "Citation range is invalid or exceeds the supported limit.")
                continue
            identifier = cite.get("document_id")
            if not isinstance(identifier, str):
                flag("unknown_source", target, "Source is missing or not authorized.")
                continue
            if "page_references" in cite:
                refs = cite["page_references"]
                valid_refs = (isinstance(refs, list) and all(isinstance(ref, dict)
                    and set(ref) == {"page_number", "line_start", "line_end"}
                    and all(type(value) is int for value in ref.values()) for ref in refs))
                if not valid_refs or refs != page_references(document_lookup.get(identifier), start, end):
                    flag("page_mismatch", target, "Page references differ from the extracted source mapping.")
            lines = [sources.get((identifier, number)) for number in range(start, end + 1)]
            if any(line is None for line in lines):
                flag("unknown_source", target, "Source is missing or not authorized.")
            elif cite.get("quote") != "\n".join(lines):
                flag("quote_mismatch", target, "Quoted text differs from the source line.")
            elif not cite["quote"].strip():
                flag("empty_evidence", target, "Blank source lines cannot support a factual claim.")
            else:
                verified.append(Citation(identifier, start, "\n".join(lines)))
        return verified

    for claim in result.get("claims", []):
        target = claim.get("claim_id", "claim")
        cites = citations(claim.get("citations"), target)
        finding = Finding(claim.get("text", ""), tuple(cites))
        if generated:
            # Location/quote validity is verifiable; semantic entailment is not.
            if cites:
                evidence = " ".join(cite.quote for cite in cites)
                numbers = set(re.findall(r"\b\d+(?:[.,]\d+)*\b", finding.claim))
                evidence_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)*\b", evidence))
                if numbers - evidence_numbers:
                    flag("unsupported_number", target, "Claim introduces numeric values absent from its cited evidence.")
                if re.search(r"\b(fully compliant|all requirements (?:are )?met|conflict (?:is |has been )?resolved|conflicts (?:are |have been )?resolved)\b", finding.claim, re.I):
                    flag("unsupported_verdict", target, "The brief asserts compliance or conflict resolution that this workflow cannot establish.")
            flag("semantic_review_required", target,
                 "AI draft: a human must check whether the cited evidence supports this statement.", "warning")
        elif not AuditAgent().validate(Analysis([finding]), passages).passed:
            flag("unsupported_claim", target, "Claim is not an exact supported extract.")
    known_conflicts = detect_conflicts(passages)
    for conflict in result.get("contradictions", []):
        target = conflict.get("conflict_id", "conflict")
        citations(conflict.get("citations"), target)
        # Page provenance is additive and checked above; compare the original
        # retention-rule contract without those server-derived display fields.
        comparison = dict(conflict)
        if isinstance(conflict.get("citations"), list):
            comparison["citations"] = [{key: value for key, value in cite.items() if key != "page_references"}
                                       if isinstance(cite, dict) else cite for cite in conflict["citations"]]
        if comparison not in known_conflicts:
            flag("unsupported_conflict", target, "Conflict is not supported by the retention rules and evidence.")
    if generated and known_conflicts:
        flag("unresolved_conflicting_evidence", "brief", "Source retention periods disagree; do not treat either value as reconciled.", "warning")
    if generated and not 300 <= result.get("brief_word_count", 0) <= 650:
        flag("brief_length_review", "brief", "Brief is outside the approximate one-page target; do not pad sparse evidence with invented facts.", "warning")
    for check in result.get("requirement_checks", []):
        if check.get("citations"):
            citations(check["citations"], check.get("requirement_id", "requirement"))
        if check.get("status") != "unclear":
            flag("unsupported_verdict", check.get("requirement_id"), "Word matching alone cannot establish compliance.")
    timestamp = datetime.now(timezone.utc).isoformat()
    has_errors = any(item["severity"] == "error" for item in flags)
    audit = {"status": "flagged" if has_errors else "needs_review" if flags else "passed", "flags": flags,
             "checked_at": timestamp, "method": "citation_checks_with_human_semantic_review" if generated else "exact_extract_and_retention_rules",
             "limitations": "Checks source locations, exact quotes, numeric support, and supported rules; it does not establish general semantic truth."}
    evidence = [(p.document_id, p.number, p.text) for p in passages]
    event = {"event": "analysis_audited", "analysis_id": result["analysis_id"],
             "timestamp": timestamp, "task": result["task"],
             "document_ids": sorted(result.get("document_ids", {p.document_id for p in passages})),
             "evidence_sha256": hashlib.sha256(json.dumps(evidence, ensure_ascii=True).encode()).hexdigest(),
             "audit_status": audit["status"], "flag_codes": [item["code"] for item in flags]}
    return audit, event
