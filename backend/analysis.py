"""Reader-contract adapter for the extractive analysis and audit agents."""


class AnalysisUnavailable(Exception):
    """Raised until the real Analysis Agent has been connected."""


def analyze_documents(request: dict) -> dict:
    """Adapt the reader contract to the extractive agents for the local workspace."""
    from document_reader import read_document_bytes
    from mesh import run_workflow
    from mesh.models import Document

    documents = request.get("documents")
    if request.get("api_version") != "1.0":
        raise ValueError("api_version must be 1.0")
    if not isinstance(documents, list) or not 1 <= len(documents) <= 12:
        raise ValueError("Provide between 1 and 12 extracted documents")
    normalized = []
    total = 0
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get("text"), str):
            raise ValueError("Each document must contain decoded text")
        raw = document["text"].encode("utf-8")
        total += len(raw)
        if len(raw) > 256 * 1024 or total > 2 * 1024 * 1024:
            raise ValueError("Document size limits exceeded")
        canonical = read_document_bytes("source.txt", raw)
        if (document.get("status") != "ok" or canonical["status"] != "ok"
                or canonical["document_id"] != document.get("document_id")
                or canonical["lines"] != document.get("lines")
                or canonical["line_count"] > 10000):
            raise ValueError("Document identity or source lines do not match its text")
        # All submitted documents belong to this single-user local workspace.
        # Client-supplied role/ACL fields are intentionally not used.
        normalized.append(Document(canonical["document_id"], canonical["text"], frozenset({"local"})))
    requirements = request.get("requirements", [])
    if not isinstance(requirements, list) or len(requirements) > 100 or any(
            not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in requirements):
        raise ValueError("requirements must contain up to 100 nonempty strings")
    mode = request.get("task")
    if mode == "requirements" and not requirements:
        raise ValueError("Supply explicit requirements to check")
    result = run_workflow(normalized, "local", mode, tuple(requirements))
    claims = []
    for index, finding in enumerate(result["analysis"]["findings"], 1):
        claims.append({"claim_id": f"claim_{index}", "text": finding["claim"], "citations": [
            {"document_id": c["document_id"], "line_start": c["passage"], "line_end": c["passage"]}
            for c in finding["citations"]]})
    checks = []
    if mode == "requirements":
        from mesh.agents import _tokens
        for index, requirement in enumerate(requirements, 1):
            matches = [c for c in claims if _tokens(requirement) <= _tokens(c["text"])]
            checks.append({"requirement_id": f"requirement_{index}", "text": requirement,
                           "status": "unclear", "explanation": "Lexical evidence found; human review required." if matches else "No lexical evidence found; human review required.",
                           "citations": [ref for claim in matches for ref in claim["citations"]]})
    return {"api_version": "1.0", "task": mode, "status": "completed", "claims": claims,
            "contradictions": [], "requirement_checks": checks,
            "limitations": ["Extractive baseline; no LLM or semantic conflict detection.",
                            "Requirement matching does not establish compliance.",
                            "Audit verifies exact extracts against submitted sources, not source truth.",
                            "Single-user local workspace; no authentication or persistent audit storage."],
            "audit": {"status": "passed" if result["audit"]["passed"] else "failed",
                      "flags": result["audit"]["issues"], "event": result["audit_event"]}}
