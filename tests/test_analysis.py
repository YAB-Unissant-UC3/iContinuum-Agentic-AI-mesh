import unittest

from backend.analysis import analyze_documents
from document_reader import read_document_bytes


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
