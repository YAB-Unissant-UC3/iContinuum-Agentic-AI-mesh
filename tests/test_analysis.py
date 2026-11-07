import unittest
from pathlib import Path

from backend.analysis import analyze_documents
from document_reader import read_document_bytes, read_document


class AnalysisContractTests(unittest.TestCase):
    def request(self):
        return {"api_version": "1.0", "task": "brief", "documents": [
            read_document_bytes("test.txt", b"Backups run daily.\n")
        ]}

    def test_modified_source_identity_or_lines_are_rejected(self):
        for field, value in (("document_id", "forged"), ("lines", []), ("text", "changed")):
            request = self.request()
            request["documents"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                analyze_documents(request)

    def test_requirements_need_explicit_input(self):
        request = self.request()
        request["task"] = "requirements"
        with self.assertRaises(ValueError):
            analyze_documents(request)

    def test_match_does_not_claim_compliance(self):
        request = self.request()
        request.update(task="requirements", requirements=["backups daily", "encryption"])
        result = analyze_documents(request)
        self.assertEqual([c["status"] for c in result["requirement_checks"]], ["unclear", "unclear"])
        self.assertTrue(result["requirement_checks"][0]["citations"])
        self.assertFalse(result["requirement_checks"][1]["citations"])

    def test_brief_quotes_existing_source_lines(self):
        request = self.request()
        result = analyze_documents(request)
        self.assertEqual(result["mode"], "deterministic_demo")
        for claim in result["claims"]:
            cite = claim["citations"][0]
            self.assertEqual(cite["document_id"], request["documents"][0]["document_id"])
            self.assertEqual(claim["text"], request["documents"][0]["lines"][cite["line_start"] - 1]["text"])

    def test_retention_conflict_has_both_original_locations(self):
        root = Path(__file__).resolve().parents[1] / "sample_documents"
        docs = [read_document(root / name) for name in ("requirements.txt", "meeting_notes.txt")]
        result = analyze_documents({"task": "requirements", "documents": docs, "requirements": ["audit records"]})
        cites = result["contradictions"][0]["citations"]
        self.assertEqual([(c["document_id"], c["line_start"]) for c in cites],
                         [(docs[0]["document_id"], 9), (docs[1]["document_id"], 8)])

    def test_equivalent_durations_are_not_conflicts(self):
        docs = [read_document_bytes("test.txt", b"Retain audit records for 1 week.\nRetain audit records for 7 days.\n")]
        result = analyze_documents({"task": "requirements", "documents": docs, "requirements": ["audit records"]})
        self.assertEqual(result["contradictions"], [])
