"""Server-owned evidence, ACLs, results, and metadata-only JSONL audit records."""

import copy
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
import uuid

from document_reader import read_document_bytes


class WorkspaceError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


class Workspace:
    def __init__(self, sample_dir, data_dir):
        self.lock = RLock()
        self.sessions, self.documents, self.runs = {}, {}, {}
        self.demo_ids = []
        self.log_path = Path(data_dir) / "audit.jsonl"
        root = Path(sample_dir).resolve()
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        for item in manifest["documents"]:
            source = (root / item["path"]).resolve()
            source.relative_to(root)
            roles = frozenset(item["allowed_roles"])
            if not roles or not roles <= {"analyst", "manager"} or "manager" not in roles:
                raise ValueError("Invalid document roles in manifest.")
            if source.stat().st_size > 256 * 1024:
                raise ValueError("Synthetic manifest file exceeds 256 KiB.")
            if source.suffix.lower() not in {".txt", ".pdf"}:
                raise ValueError("Manifest documents must be TXT or PDF files.")
            with source.open("rb") as stream:
                raw = stream.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError("Synthetic manifest file exceeds 256 KiB.")
            identifier = "doc_" + hashlib.sha256(raw).hexdigest()
            if identifier in self.documents:
                raise ValueError("Manifest contains duplicate file contents.")
            # Index identities and ACLs, not extracted text. In particular, the
            # restricted police report is never parsed on an Analyst request.
            self.documents[identifier] = {"document": None, "roles": roles, "owner": None,
                                          "raw": raw, "name": source.name,
                                          "source_path": "sample_documents/" + item["path"]}
            self.demo_ids.append(identifier)

    def allowed(self, record, user):
        return user["role"] in record["roles"] and (
            user["role"] == "manager" or record["owner"] in (None, user["username"]))

    def document(self, identifier, user):
        if not isinstance(identifier, str):
            raise WorkspaceError("invalid_document_id", "Document IDs must be strings.")
        record = self.documents.get(identifier)
        if not record or not self.allowed(record, user):
            raise WorkspaceError("access_denied", "Document access denied.", 403)
        if record["document"] is None:
            document = read_document_bytes(record["name"], record["raw"])
            if document["status"] != "ok" or document["line_count"] > 10000:
                raise WorkspaceError("unreadable_document", "A registered sample cannot be extracted within the document limits.", 422)
            document["source_path"] = record["source_path"]
            record["document"] = document
        result = copy.deepcopy(record["document"])
        result["access"] = "restricted" if record["roles"] == frozenset({"manager"}) else "public"
        return result

    def list_documents(self, user, demo_only=False):
        identifiers = self.demo_ids if demo_only else self.documents
        return [self.document(identifier, user) for identifier in identifiers
                if self.allowed(self.documents[identifier], user)]

    def authorize_uploads(self, decoded, access, user):
        """Check every raw-byte identity before any upload is extracted."""
        if access not in ("public", "restricted"):
            raise WorkspaceError("invalid_access", "access must be public or restricted.")
        if access == "restricted" and user["role"] != "manager":
            raise WorkspaceError("access_denied", "Only Managers can register restricted uploads.", 403)
        roles = frozenset({"manager"}) if access == "restricted" else frozenset({"analyst", "manager"})
        for _, raw in decoded:
            identifier = "doc_" + hashlib.sha256(raw).hexdigest()
            existing = self.documents.get(identifier)
            if existing:
                if not self.allowed(existing, user):
                    raise WorkspaceError("access_denied", "Document access denied.", 403)
                if existing["roles"] != roles:
                    raise WorkspaceError("classification_conflict", "Identical bytes already have a different access classification.")
        return roles

    def register(self, documents, access, user, decoded):
        roles = self.authorize_uploads(decoded, access, user)
        originals = {"doc_" + hashlib.sha256(raw).hexdigest(): raw for _, raw in decoded}
        new_ids = {d["document_id"] for d in documents if d["document_id"] and d["document_id"] not in self.documents}
        if len(self.documents) + len(new_ids) > 100:
            raise WorkspaceError("workspace_full", "Demo workspace is full. Restart the server to clear uploads.", 413)
        results = []
        for document in documents:
            identifier = document["document_id"]
            if identifier:
                self.documents.setdefault(identifier, {"document": copy.deepcopy(document), "roles": roles,
                                                       "owner": user["username"], "raw": originals[identifier]})
                results.append(self.document(identifier, user))
            else:
                results.append(document)
        return results

    def resolve_analysis(self, payload, user):
        identifiers = payload.get("document_ids")
        supplied = payload.get("documents")
        if identifiers is None:
            if not isinstance(supplied, list) or any(not isinstance(d, dict) for d in supplied):
                raise WorkspaceError("invalid_documents", "Provide document_ids from the server.")
            identifiers = [d.get("document_id") for d in supplied]
        if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 12:
            raise WorkspaceError("invalid_documents", "Select between 1 and 12 documents.")
        # Resolve every ID and permission before trusting any submitted evidence.
        for identifier in identifiers:
            if (not isinstance(identifier, str) or identifier not in self.documents
                    or not self.allowed(self.documents[identifier], user)):
                raise WorkspaceError("access_denied", "Document access denied.", 403)
        documents = [self.document(identifier, user) for identifier in identifiers]
        if len(set(identifiers)) != len(identifiers):
            raise WorkspaceError("invalid_documents", "Select unique documents.")
        if supplied is not None:
            if not isinstance(supplied, list) or len(supplied) != len(documents):
                raise WorkspaceError("invalid_documents", "Document snapshots must match selected IDs.")
            for original, provided in zip(documents, supplied):
                fields = ("document_id", "text", "lines", "line_count", "status", "file_name")
                if original.get("format") == "pdf":
                    fields += ("format", "pages", "page_count", "extraction", "encoding")
                if not isinstance(provided, dict) or any(provided.get(field) != original[field]
                    for field in fields):
                    raise WorkspaceError("modified_evidence", "Submitted evidence differs from server records.")
        return {"task": payload.get("task"), "requirements": payload.get("requirements", []), "documents": documents}

    def pdf_sources(self, documents, user):
        """Private originals for canonical validation; never part of API JSON."""
        for document in documents:
            record = self.documents.get(document["document_id"])
            if not record or not self.allowed(record, user):
                raise WorkspaceError("access_denied", "Document access denied.", 403)
        return {d["document_id"]: self.documents[d["document_id"]]["raw"]
                for d in documents if d.get("format") == "pdf"}

    def write_event(self, event, user):
        record = dict(event, event_id="event_" + uuid.uuid4().hex,
                      actor=user["username"], role=user["role"])
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=True) + "\n")
        return record

    def save_run(self, result, user):
        if len(self.runs) >= 100:
            raise WorkspaceError("workspace_full", "Restart the server to clear demo analyses.", 413)
        result["audit_event"] = self.write_event(result["audit_event"], user)
        self.runs[result["analysis_id"]] = {"result": copy.deepcopy(result), "owner": user["username"]}

    def run(self, identifier, user):
        record = self.runs.get(identifier)
        if not record or (user["role"] != "manager" and record["owner"] != user["username"]):
            raise WorkspaceError("access_denied", "Analysis access denied.", 403)
        for document_id in record["result"]["document_ids"]:
            self.document(document_id, user)
        return copy.deepcopy(record["result"])

    def review(self, identifier, payload, user):
        if user["role"] != "manager":
            raise WorkspaceError("access_denied", "Only Managers can approve or reject analyses.", 403)
        result = self.run(identifier, user)
        decision, comment = payload.get("decision"), payload.get("comment")
        if decision not in ("approve", "reject") or not isinstance(comment, str) or not comment.strip() or len(comment) > 1000:
            raise WorkspaceError("invalid_review", "Choose approve/reject and supply a review note (up to 1,000 characters).")
        audit = result["audit"]
        reviewable_draft = (result.get("mode") in {"gemini", "groq"} and audit["status"] == "needs_review"
                            and bool(audit["flags"]) and all(flag.get("severity") == "warning" for flag in audit["flags"]))
        if decision == "approve" and not (audit["status"] == "passed" or reviewable_draft):
            raise WorkspaceError("audit_failed", "Flagged analyses cannot be approved.", 409)
        timestamp = datetime.now(timezone.utc).isoformat()
        result["review"] = {"status": "approved" if decision == "approve" else "rejected",
                            "audit_status_at_review": audit["status"],
                            "actor": user["username"], "timestamp": timestamp, "comment": comment.strip()}
        self.write_event({"event": "human_review", "analysis_id": identifier,
                          "timestamp": timestamp, "decision": result["review"]["status"],
                          "audit_status": audit["status"],
                          "document_ids": result["document_ids"]}, user)
        self.runs[identifier]["result"] = copy.deepcopy(result)
        return result

    def audit_trail(self, identifier, user):
        self.run(identifier, user)
        if not self.log_path.exists():
            return []
        return [event for line in self.log_path.read_text(encoding="utf-8").splitlines()
                if (event := json.loads(line)).get("analysis_id") == identifier]
