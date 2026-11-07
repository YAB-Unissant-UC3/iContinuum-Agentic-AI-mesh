"""Adapt Reader evidence to the existing deterministic mesh agents."""

from datetime import datetime, timezone
import re
import uuid
from pathlib import Path

from document_reader import read_document_bytes
from mesh import AnalysisAgent
from mesh.models import Passage
from mesh.conflicts import detect_conflicts
from .audit import audit_analysis
from .gemini import ProviderUnavailable
from .source_locations import add_page_references


class AnalysisUnavailable(Exception):
    """Reserved for an optional future model adapter."""


def validated_passages(documents, pdf_sources=None):
    if not isinstance(documents, list) or not 1 <= len(documents) <= 12:
        raise ValueError("Provide between 1 and 12 readable documents.")
    passages, seen = [], set()
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get("text"), str):
            raise ValueError("Each document must contain original text.")
        name = document.get("file_name")
        if not isinstance(name, str):
            raise ValueError("Each document needs a file name.")
        try:
            if Path(name).suffix.lower() == ".pdf":
                raw = (pdf_sources or {}).get(document.get("document_id"))
                if not isinstance(raw, bytes):
                    raise ValueError("PDF validation requires server-authorized original bytes.")
                canonical = read_document_bytes(name, raw)
            else:
                canonical = read_document_bytes(name, document["text"].encode("utf-8"))
        except UnicodeError:
            raise ValueError("Document text must be valid UTF-8.")
        for field in ("document_id", "text", "lines", "line_count", "status"):
            if document.get(field) != canonical[field]:
                raise ValueError("Document identity or source lines were modified.")
        if canonical.get("format") == "pdf" and any(document.get(field) != canonical[field]
                for field in ("format", "pages", "page_count", "extraction", "encoding")):
            raise ValueError("PDF extraction provenance or page mapping was modified.")
        if canonical["status"] != "ok" or canonical["document_id"] in seen:
            raise ValueError("Use unique, readable, nonempty documents.")
        seen.add(canonical["document_id"])
        passages.extend(Passage(canonical["document_id"], line["line_number"], line["text"])
                        for line in canonical["lines"] if line["text"].strip())
    return passages


def analyze_documents(request: dict, brief_generator=None, *, pdf_sources=None) -> dict:
    task = request.get("task")
    if task not in ("brief", "requirements"):
        raise ValueError("task must be brief or requirements.")
    passages = validated_passages(request.get("documents"), pdf_sources)
    requirements = request.get("requirements", [])
    if task == "requirements":
        if (not isinstance(requirements, list) or not 1 <= len(requirements) <= 30
                or any(not isinstance(item, str) or not re.search(r"\w", item)
                       or len(item) > 1000 for item in requirements)):
            raise ValueError("Requirements Checker needs 1–30 nonempty requirement strings.")
    else:
        requirements = []
    agent = AnalysisAgent()
    analysis = agent.analyze(passages, task, tuple(requirements))
    findings = analysis.findings
    if task == "brief":
        useful = [finding for finding in findings if not re.match(
            r"^(FICTIONAL|Project:|Meeting date:|REQ-\d+:)", finding.claim)]
        findings = (useful or findings)[:12]
    claims = [{"claim_id": "C{:03d}".format(index), "text": finding.claim,
               "citations": [{"document_id": cite.document_id, "line_start": cite.passage,
                              "line_end": cite.passage, "quote": cite.quote}
                             for cite in finding.citations]}
              for index, finding in enumerate(findings, 1)]
    checks = []
    for index, requirement in enumerate(requirements, 1):
        matched = agent.analyze(passages, "requirements", (requirement,))
        checks.append({"requirement_id": "R{:03d}".format(index), "text": requirement,
                       "status": "unclear", "explanation": (
                           "Matching evidence found; matching words do not prove compliance."
                           if matched.findings else "No complete lexical match found; compliance is unclear."),
                       "citations": [{"document_id": f.citations[0].document_id,
                                      "line_start": f.citations[0].passage,
                                      "line_end": f.citations[0].passage,
                                      "quote": f.citations[0].quote} for f in matched.findings[:12]]})
    result = {"api_version": "1.0", "analysis_id": "run_" + uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "task": task, "status": "completed", "mode": "deterministic_demo",
            "mode_label": "Deterministic demo mode (no LLM)",
            "document_ids": [item["document_id"] for item in request["documents"]],
            "claims": claims, "contradictions": detect_conflicts(passages),
            "requirement_checks": checks,
            "limitations": ["Extractive summaries quote sources; no LLM is used.",
                            "Conflict detection checks explicit record/log retention durations only.",
                            "Lexical requirement matches are evidence retrieval, not compliance verdicts."],
            "audit": {"status": "not_run", "flags": []}, "review": {"status": "pending"}}
    if task == "brief" and brief_generator is not None and brief_generator.enabled:
        provider = getattr(brief_generator, "provider", "gemini")
        result["attempted_provider"] = provider
        result["attempted_model"] = getattr(brief_generator, "public_model", brief_generator.model)
        try:
            generated = brief_generator.generate(request["documents"], result["contradictions"])
            allowed_ids = set(result["document_ids"])
            for claim in generated:
                if any(cite["document_id"] not in allowed_ids for cite in claim["citations"]):
                    claim["text"] = "Draft statement withheld: a citation refers to an unavailable source."
                    for cite in claim["citations"]:
                        if cite["document_id"] not in allowed_ids:
                            cite["quote"] = "[Unavailable source]"
            result.update(claims=generated, mode=provider, provider=provider,
                          mode_label="{}-generated draft / human review required".format(provider.capitalize()),
                          model=getattr(brief_generator, "public_model", brief_generator.model),
                          brief_word_count=sum(len(claim["text"].split()) for claim in generated),
                          limitations=["Citation checks do not prove that a paraphrase is semantically supported.",
                                       "AI output may contain unsupported or misleading statements; Manager review is required.",
                                       "Known retention conflicts remain unresolved unless reconciled in source evidence."])
        except ProviderUnavailable as exc:
            result["fallback_reason"] = exc.reason
            if exc.diagnostics:
                result["provider_diagnostics"] = dict(exc.diagnostics)
            result["mode_label"] = "Deterministic demo fallback ({} unavailable)".format(provider.capitalize())
            # If a credential was accidentally uploaded as evidence, do not
            # echo it through the deterministic fallback's quoted extracts.
            if exc.reason == "response_redacted" and brief_generator.contains_credential(result):
                result["claims"] = []
                result["contradictions"] = []
                result["source_redacted"] = True
                result["limitations"].append("Quoted output withheld because selected evidence contains a credential.")
    result["audit"], result["audit_event"] = audit_analysis(result, passages, request["documents"])
    # The server derives PDF locations from validated originals, never from AI.
    add_page_references(result, request["documents"])
    if any(d.get("format") == "pdf" for d in request["documents"]):
        result["limitations"].append("PDF citations refer to pypdf-extracted page lines, not physical printed lines; complex layouts require visual review. No OCR is performed.")
    result["audit_event"]["generation_mode"] = result["mode"]
    for field in ("provider", "attempted_provider", "attempted_model"):
        if result.get(field):
            result["audit_event"][field] = result[field]
    if result.get("model"):
        result["audit_event"]["model"] = result["model"]
    if result.get("fallback_reason"):
        result["audit_event"]["fallback_reason"] = result["fallback_reason"]
    if result.get("provider_diagnostics"):
        result["audit_event"]["provider_diagnostics"] = dict(result["provider_diagnostics"])
    return result
