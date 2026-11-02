"""Deterministic baseline. Document text is evidence, never executable instructions."""

import hashlib
import re
from dataclasses import asdict
from datetime import datetime, timezone

from .models import Analysis, AuditResult, Citation, Document, Finding, Passage


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


class DocumentAgent:
    def extract(self, documents: list[Document], role: str) -> list[Passage]:
        if not role.strip():
            raise ValueError("A trusted caller role is required")
        ids = [doc.id for doc in documents]
        if any(not identifier.strip() for identifier in ids) or len(ids) != len(set(ids)):
            raise ValueError("Document IDs must be nonempty and unique")
        passages = []
        for doc in documents:
            if role not in doc.allowed_roles:
                continue
            for number, line in enumerate(doc.text.splitlines(), start=1):
                if line.strip():
                    passages.append(Passage(doc.id, number, line.strip()))
        return passages


class AnalysisAgent:
    def analyze(self, passages: list[Passage], mode: str = "brief", requirements: tuple[str, ...] = ()) -> Analysis:
        if mode not in {"brief", "requirements"}:
            raise ValueError("mode must be brief or requirements")
        if mode == "requirements" and (not requirements or any(not _tokens(r) for r in requirements)):
            raise ValueError("Requirements mode needs nonempty requirements")
        result = Analysis()
        selected = passages
        if mode == "requirements":
            selected = []
            for requirement in requirements:
                # Conservative lexical coverage is a retrieval aid, not a compliance verdict.
                matches = [p for p in passages if _tokens(requirement) <= _tokens(p.text)]
                if not matches:
                    result.unmet_requirements.append(requirement)
                for passage in matches:
                    if passage not in selected:
                        selected.append(passage)
        for passage in selected:
            result.findings.append(Finding(passage.text, (Citation(passage.document_id, passage.number, passage.text),)))
        return result


class AuditAgent:
    def validate(self, analysis: Analysis, passages: list[Passage]) -> AuditResult:
        sources = {(p.document_id, p.number): p.text for p in passages}
        issues = []
        for index, finding in enumerate(analysis.findings):
            if not finding.citations:
                issues.append(f"Finding {index}: missing citation")
            supported = False
            for citation in finding.citations:
                source = sources.get((citation.document_id, citation.passage))
                if source is None or not citation.quote.strip() or citation.quote not in source:
                    issues.append(f"Finding {index}: invalid citation")
                elif finding.claim.strip() and finding.claim == citation.quote:
                    supported = True
            if not supported:
                issues.append(f"Finding {index}: claim is not an exact supported extract")
        return AuditResult(not issues, tuple(issues))


def run_workflow(documents: list[Document], role: str, mode: str = "brief", requirements: tuple[str, ...] = ()) -> dict:
    """Role must come from authenticated server context, not a client role selector."""
    passages = DocumentAgent().extract(documents, role)
    analysis = AnalysisAgent().analyze(passages, mode, requirements)
    audit = AuditAgent().validate(analysis, passages)
    visible_ids = sorted({p.document_id for p in passages})
    return {
        "analysis": asdict(analysis),
        "audit": asdict(audit),
        "audit_event": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "mode": mode,
            "document_ids": visible_ids,
            "evidence_sha256": hashlib.sha256(repr(passages).encode()).hexdigest(),
            "passed": audit.passed,
        },
    }
