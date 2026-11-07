"""Canonical PDF evidence, citation audit, and direct HTTP permission tests."""

import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError

import test_workflow
from test_pdf_reader import SAMPLES, STORY_NAMES, make_pdf
from backend.analysis import analyze_documents, validated_passages
from backend.audit import audit_analysis
from backend.gemini import GeminiBriefGenerator
from backend.groq import GroqBriefGenerator
from backend.source_locations import page_references
from document_reader import read_document_bytes


class Response:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.body[:limit]


class PDFWorkflowTests(unittest.TestCase):
    setUp = test_workflow.FullWorkflowTests.setUp
    tearDown = test_workflow.FullWorkflowTests.tearDown
    call = test_workflow.FullWorkflowTests.call
    demo = test_workflow.FullWorkflowTests.demo
    analyze = test_workflow.FullWorkflowTests.analyze

    def upload(self, user, name, raw, access="public"):
        return self.call(user, "POST", "/api/documents", {"access": access, "files": [
            {"file_name": name, "content_base64": base64.b64encode(raw).decode()}]})

    def test_all_story_documents_analyze_and_audit_for_manager(self):
        stories = [d for d in self.demo("manager") if d["file_name"] in STORY_NAMES]
        self.assertEqual(len(stories), 5)
        for document in stories:
            with self.subTest(name=document["file_name"]):
                status, result, _ = self.analyze("manager", documents=[document])
                self.assertEqual(status, 200, result)
                self.assertEqual(result["audit"]["status"], "passed")
                self.assertEqual(result["review"]["status"], "pending")
                for claim in result["claims"]:
                    for cite in claim["citations"]:
                        self.assertEqual(cite["quote"], document["lines"][cite["line_start"] - 1]["text"])
                        if document.get("format") == "pdf":
                            self.assertEqual(cite["page_references"], page_references(document, cite["line_start"], cite["line_end"]))
                status, review, _ = self.call("manager", "POST", "/api/analysis/" + result["analysis_id"] + "/review",
                                             {"decision": "approve", "comment": "Synthetic PDF review"})
                self.assertEqual(status, 200)
                self.assertEqual(review["audit"]["status"], "passed")
        self.assertEqual(self.analyze("manager", documents=stories)[0], 200)

    def test_analyst_has_four_public_story_documents_and_no_police_content(self):
        docs = self.demo()
        stories = [d for d in docs if d["file_name"].startswith("DOC-")]
        self.assertEqual({d["file_name"] for d in stories}, set(STORY_NAMES[:-1]))
        self.assertNotIn("Dana Whitfield", json.dumps(docs))
        status, result, _ = self.analyze(documents=stories)
        self.assertEqual(status, 200)
        self.assertEqual(result["audit"]["status"], "passed")
        police_id = "doc_" + hashlib.sha256((SAMPLES / STORY_NAMES[-1]).read_bytes()).hexdigest()
        self.assertNotIn(police_id, json.dumps(result))

    def test_restricted_police_is_not_extracted_on_startup_or_analyst_listing(self):
        workspace = self.server.workspace
        self.assertTrue(all(record["document"] is None for record in workspace.documents.values()))
        with patch("backend.workspace.read_document_bytes", wraps=read_document_bytes) as reader:
            self.demo()
        self.assertNotIn(STORY_NAMES[-1], [call.args[0] for call in reader.call_args_list])
        identifier = "doc_" + hashlib.sha256((SAMPLES / STORY_NAMES[-1]).read_bytes()).hexdigest()
        self.assertIsNone(workspace.documents[identifier]["document"])

    def test_direct_retrieval_analysis_snapshot_and_batch_denied_before_extraction_or_provider(self):
        raw = (SAMPLES / STORY_NAMES[-1]).read_bytes()
        police_id = "doc_" + hashlib.sha256(raw).hexdigest()
        public_id = self.server.workspace.demo_ids[0]
        attempts = [("GET", "/api/documents/" + police_id, None),
                    ("POST", "/api/analysis", {"task": "brief", "document_ids": [police_id]}),
                    ("POST", "/api/analysis", {"task": "brief", "document_ids": [public_id, police_id]}),
                    ("POST", "/api/analysis", {"task": "brief", "documents": [{"document_id": police_id,
                       "text": "fake accessible evidence", "access": "public", "allowed_roles": ["analyst"]}]})]
        with patch("backend.workspace.read_document_bytes") as reader, patch("backend.server.analyze_documents") as analysis:
            for method, route, payload in attempts:
                status, error, _ = self.call("analyst", method, route, payload, {"X-Role": "manager"})
                self.assertEqual(status, 403)
                self.assertNotIn("police", repr(error).lower())
            reader.assert_not_called()
            analysis.assert_not_called()

    def test_restricted_upload_is_denied_before_extraction_even_when_renamed(self):
        raw = (SAMPLES / STORY_NAMES[-1]).read_bytes()
        with patch("backend.server.read_document_bytes") as reader:
            for name in (STORY_NAMES[-1], "ordinary.pdf", "ordinary.txt", "ordinary.docx"):
                status, error, _ = self.upload("analyst", name, raw)
                self.assertEqual(status, 403)
                self.assertEqual(error["error"]["code"], "access_denied")
            reader.assert_not_called()

    def test_restricted_upload_batch_is_atomic_and_anonymous_upload_is_denied(self):
        raw = (SAMPLES / STORY_NAMES[-1]).read_bytes()
        payload = {"files": [{"file_name": "new.txt", "content_base64": base64.b64encode(b"Unique public fixture").decode()},
                             {"file_name": "renamed.pdf", "content_base64": base64.b64encode(raw).decode()}]}
        with patch("backend.server.read_document_bytes") as reader:
            for user, expected in (("analyst", 403), (None, 401)):
                self.assertEqual(self.call(user, "POST", "/api/documents", payload)[0], expected)
            reader.assert_not_called()
        self.assertEqual(len(self.server.workspace.documents), 9)

    def test_manager_cannot_downgrade_police_classification(self):
        raw = (SAMPLES / STORY_NAMES[-1]).read_bytes()
        with patch("backend.server.read_document_bytes") as reader:
            status, error, _ = self.upload("manager", "renamed.pdf", raw, "public")
            self.assertEqual(status, 400)
            self.assertEqual(error["error"]["code"], "classification_conflict")
            reader.assert_not_called()
        status, result, _ = self.upload("manager", "renamed.pdf", raw, "restricted")
        self.assertEqual(status, 200)
        self.assertEqual(result["documents"][0]["access"], "restricted")

    def test_uploaded_pdf_canonical_analysis_and_retrieval(self):
        raw = make_pdf("Original PDF source evidence", "Second page evidence")
        status, uploaded, _ = self.upload("analyst", "uploaded.pdf", raw)
        self.assertEqual(status, 200)
        doc = uploaded["documents"][0]
        self.assertEqual(doc["page_count"], 2)
        status, result, _ = self.analyze(documents=[doc])
        self.assertEqual(status, 200)
        self.assertEqual(result["audit"]["status"], "passed")
        self.assertEqual(result["claims"][1]["citations"][0]["page_references"][0]["page_number"], 2)
        fetched = self.call("analyst", "GET", "/api/documents/" + doc["document_id"])[1]["document"]
        self.assertEqual(fetched, doc)
        self.assertNotIn("raw", doc)

    def test_client_modified_pdf_mapping_text_or_identity_is_rejected(self):
        doc = next(d for d in self.demo() if d.get("format") == "pdf")
        for field in ("text", "lines", "pages", "page_count", "extraction", "encoding", "format"):
            forged = copy.deepcopy(doc)
            forged[field] = "FORGED"
            status, error, _ = self.call("analyst", "POST", "/api/analysis", {"task": "brief", "documents": [forged]})
            self.assertEqual(status, 400)
            self.assertEqual(error["error"]["code"], "modified_evidence")

    def test_pdf_requires_original_bytes_and_local_canonical_validation_is_strict(self):
        raw = make_pdf("Exact source evidence")
        doc = read_document_bytes("sample.pdf", raw)
        with self.assertRaises(ValueError):
            validated_passages([doc])
        sources = {doc["document_id"]: raw}
        self.assertTrue(validated_passages([doc], sources))
        for field in ("text", "lines", "pages", "page_count", "extraction", "encoding", "format"):
            modified = copy.deepcopy(doc)
            modified[field] = "FORGED"
            with self.subTest(field=field), self.assertRaises(ValueError):
                validated_passages([modified], sources)

    def test_police_run_and_trail_remain_inaccessible_after_manager_review(self):
        police = next(d for d in self.demo("manager") if d["file_name"] == STORY_NAMES[-1])
        status, run, _ = self.analyze("manager", documents=[police])
        self.assertEqual(status, 200)
        route = "/api/analysis/" + run["analysis_id"]
        self.assertEqual(self.call("manager", "POST", route + "/review", {"decision": "approve", "comment": "Reviewed"})[0], 200)
        for path in (route, route + "/audit", "/sample_documents/" + STORY_NAMES[-1]):
            status, error, _ = self.call("analyst", "GET", path)
            self.assertIn(status, (403, 404))
            self.assertNotIn("Whitfield", repr(error))
        _, listing, _ = self.call("analyst", "GET", "/api/analyses")
        self.assertNotIn(run["analysis_id"], repr(listing))
        log = Path(self.runtime.name, "audit.jsonl").read_text()
        self.assertNotIn("Whitfield", log)
        self.assertNotIn("555-0142", log)

    def test_pdf_requirements_evidence_uses_page_citations(self):
        police = next(d for d in self.demo("manager") if d["file_name"] == STORY_NAMES[-1])
        status, result, _ = self.call("manager", "POST", "/api/analysis", {"task": "requirements",
            "document_ids": [police["document_id"]], "requirements": ["No arrests", "unicorn evidence"]})
        self.assertEqual(status, 200)
        self.assertEqual(result["audit"]["status"], "passed")
        cites = result["requirement_checks"][0]["citations"]
        self.assertTrue(cites)
        self.assertEqual(cites[0]["page_references"][0]["page_number"], 2)
        self.assertEqual(result["requirement_checks"][1]["citations"], [])
        self.assertTrue(all(check["status"] == "unclear" for check in result["requirement_checks"]))

    def test_pdf_provider_success_audit_failures_and_fallback_for_both_providers(self):
        public_pdf = next(d for d in self.demo() if d.get("format") == "pdf")
        line = next(line for line in public_pdf["lines"] if line["text"].strip())
        citation = {"document_id": public_pdf["document_id"], "line_start": line["line_number"],
                    "line_end": line["line_number"], "quote": line["text"]}
        police_id = "doc_" + hashlib.sha256((SAMPLES / STORY_NAMES[-1]).read_bytes()).hexdigest()
        for provider_name in ("groq", "gemini"):
            provider = GroqBriefGenerator("OFFLINE_TEST_ONLY_KEY", enabled=True) if provider_name == "groq" else GeminiBriefGenerator("OFFLINE_TEST_ONLY_KEY", enabled=True)
            self.server.brief_generator = provider
            for case in ("valid", "quote", "range", "unknown", "outage"):
                cite = dict(citation)
                if case == "quote": cite["quote"] = "Invented quotation"
                if case == "range": cite["line_end"] = public_pdf["line_count"] + 1
                if case == "unknown": cite["document_id"] = police_id
                claims = {"claims": [{"section": "Overview", "text": "The source records an account for review.", "citations": [cite]}]}
                if provider_name == "groq":
                    envelope = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(claims)}}]}
                else:
                    envelope = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(claims)}]}}]}
                with self.subTest(provider=provider_name, case=case), patch("backend." + provider_name + "._send_request",
                         side_effect=URLError("offline") if case == "outage" else None,
                         return_value=Response(envelope)) as transport:
                    status, result, _ = self.analyze(documents=[public_pdf])
                    self.assertEqual(status, 200, result)
                    self.assertEqual(result["mode"], "deterministic_demo" if case == "outage" else provider_name)
                    self.assertEqual(result["audit"]["status"], "passed" if case == "outage" else "needs_review" if case == "valid" else "flagged")
                    self.assertEqual(result["review"]["status"], "pending")
                    outgoing = json.loads(transport.call_args.args[0].data)
                    self.assertNotIn(police_id, json.dumps(outgoing))
                    self.assertNotIn("Whitfield", json.dumps(outgoing))
                    if case == "valid":
                        self.assertEqual(result["claims"][0]["citations"][0]["page_references"][0]["page_number"], line["page_number"])
                        self.assertIn("semantic_review_required", result["audit_event"]["flag_codes"])
                    if case == "quote":
                        self.assertIn("quote_mismatch", result["audit_event"]["flag_codes"])
                        reviewed = self.call("manager", "POST", "/api/analysis/" + result["analysis_id"] + "/review", {"decision": "approve", "comment": "Cannot override mismatch"})
                        self.assertEqual(reviewed[0], 409)

    def test_multiline_pdf_quote_whitespace_and_page_mapping_are_audited(self):
        doc = next(d for d in self.demo("manager") if d["file_name"] == STORY_NAMES[-1])
        raw = (SAMPLES / STORY_NAMES[-1]).read_bytes()
        sources = {doc["document_id"]: raw}
        passages = validated_passages([doc], sources)
        base = analyze_documents({"task": "brief", "documents": [doc]}, pdf_sources=sources)
        start = next(line["line_number"] for line in doc["lines"] if "Involved party 1" in line["text"])
        quote = "\n".join(line["text"] for line in doc["lines"][start - 2:start + 1])
        self.assertTrue(quote.startswith("\n"))
        for variant in ("exact", "missing_blank", "wrong_page", "boolean_page"):
            result = copy.deepcopy(base)
            result.update(mode="groq", brief_word_count=300)
            cite = {"document_id": doc["document_id"], "line_start": start - 1, "line_end": start + 1, "quote": quote}
            if variant == "missing_blank": cite["quote"] = quote.lstrip("\n")
            if variant == "wrong_page": cite["page_references"] = [{"page_number": 999, "line_start": 1, "line_end": 3}]
            if variant == "boolean_page":
                cite["page_references"] = page_references(doc, start - 1, start + 1)
                cite["page_references"][0]["page_number"] = True
            result["claims"] = [{"claim_id": "C001", "text": "Ajmain is listed in the source table.", "citations": [cite]}]
            audit, _ = audit_analysis(result, passages, [doc])
            codes = [flag["code"] for flag in audit["flags"]]
            self.assertIn("semantic_review_required", codes)
            self.assertEqual(audit["status"], "needs_review" if variant == "exact" else "flagged")
            if variant == "missing_blank": self.assertIn("quote_mismatch", codes)
            if variant in {"wrong_page", "boolean_page"}: self.assertIn("page_mismatch", codes)
        page_one = doc["pages"][0]["line_end"]
        refs = page_references(doc, page_one, page_one + 2)
        self.assertEqual([ref["page_number"] for ref in refs], [1, 2])

    def test_pdf_and_txt_retention_conflict_survives_page_enrichment_and_reaudit(self):
        raw = make_pdf("Retain audit records for 30 days.")
        pdf = self.upload("analyst", "retention.pdf", raw)[1]["documents"][0]
        txt = self.upload("analyst", "amendment.txt", b"Retain audit records for 90 days.\n")[1]["documents"][0]
        status, result, _ = self.analyze(task="requirements", documents=[pdf, txt])
        self.assertEqual(status, 200)
        self.assertEqual(len(result["contradictions"]), 1)
        self.assertEqual(result["audit"]["status"], "passed")
        cites = result["contradictions"][0]["citations"]
        self.assertEqual(cites[0]["page_references"], [{"page_number": 1, "line_start": 1, "line_end": 1}])
        self.assertNotIn("page_references", cites[1])
        self.assertEqual(audit_analysis(result, validated_passages([pdf, txt], {pdf["document_id"]: raw}), [pdf, txt])[0]["status"], "passed")

    def test_unreadable_encrypted_and_blank_pdfs_are_safe_per_file_api_results(self):
        files = [("blank.pdf", make_pdf("")), ("bad.pdf", b"BROKEN_PDF_PRIVATE_CONTENT"),
                 ("encrypted.pdf", make_pdf("secret", encrypted=True)), ("good.txt", b"Public synthetic evidence")]
        payload = {"files": [{"file_name": name, "content_base64": base64.b64encode(raw).decode()} for name, raw in files]}
        status, result, _ = self.call("analyst", "POST", "/api/documents", payload)
        self.assertEqual(status, 200)
        self.assertEqual([d["status"] for d in result["documents"]], ["empty", "error", "error", "ok"])
        self.assertNotIn("BROKEN_PDF_PRIVATE_CONTENT", json.dumps(result))
        blank = result["documents"][0]
        self.assertEqual(self.analyze(documents=[blank])[0], 400)
        self.assertEqual(self.analyze(documents=[result["documents"][-1]])[0], 200)
