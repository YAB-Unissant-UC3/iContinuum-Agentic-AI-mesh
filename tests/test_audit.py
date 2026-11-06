import copy
import unittest

from backend.analysis import analyze_documents, validated_passages
from backend.audit import audit_analysis
from document_reader import read_document_bytes


class ResultAuditTests(unittest.TestCase):
    def setUp(self):
        self.docs = [read_document_bytes("test.txt", b"Backups run daily.\n\nRetain audit records for 30 days.\nRetain audit records for 90 days.\n")]
        self.passages = validated_passages(self.docs)
        self.result = analyze_documents({"task": "requirements", "documents": self.docs, "requirements": ["backups daily"]})

    def test_supported_extract_and_conflict_pass(self):
        self.assertEqual(self.result["audit"]["status"], "passed")
        self.assertEqual(self.result["review"]["status"], "pending")

    def test_fabricated_claim_is_flagged(self):
        result = copy.deepcopy(self.result)
        result["claims"][0]["text"] = "Backups run hourly."
        audit, _ = audit_analysis(result, self.passages)
        self.assertEqual(audit["status"], "flagged")
        self.assertIn("unsupported_claim", [flag["code"] for flag in audit["flags"]])

    def test_fabricated_ids_quotes_and_line_ranges_fail(self):
        for key, value in (("document_id", "restricted"), ("line_start", 0),
                           ("line_start", True), ("line_end", 999), ("quote", "invented")):
            result = copy.deepcopy(self.result)
            result["claims"][0]["citations"][0][key] = value
            with self.subTest(key=key, value=value):
                audit, _ = audit_analysis(result, self.passages)
                self.assertEqual(audit["status"], "flagged")

    def test_missing_citation_fails(self):
        self.result["claims"][0]["citations"] = []
        audit, _ = audit_analysis(self.result, self.passages)
        self.assertIn("missing_citation", [flag["code"] for flag in audit["flags"]])

    def test_fabricated_conflict_description_fails(self):
        self.result["contradictions"][0]["description"] = "Encryption is disabled."
        audit, _ = audit_analysis(self.result, self.passages)
        self.assertIn("unsupported_conflict", [flag["code"] for flag in audit["flags"]])

    def test_audit_event_omits_source_text(self):
        self.assertNotIn("Backups", repr(self.result["audit_event"]))
        self.assertEqual(len(self.result["audit_event"]["evidence_sha256"]), 64)
