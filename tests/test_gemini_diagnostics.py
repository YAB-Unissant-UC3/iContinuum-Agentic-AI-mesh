"""Bounded HTTP diagnostics using fake credentials and a mocked transport only."""

from io import BytesIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from backend.analysis import analyze_documents
from backend.gemini import DEFAULT_MODEL, GeminiBriefGenerator, MAX_ERROR_RESPONSE_BYTES
from document_reader import read_document_bytes


FAKE_KEY = "DIAGNOSTIC_TEST_CREDENTIAL_95e31"
PRIVATE_MESSAGE = "PROVIDER_PRIVATE_MESSAGE_AND_DOCUMENT_CONTENT"


class TrackingBody(BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes = []
        self.bytes_read = 0

    def read(self, size=-1):
        self.read_sizes.append(size)
        value = super().read(size)
        self.bytes_read += len(value)
        return value


def provider_error(code, body):
    # Deliberately put a fake credential in every unsafe part of HTTPError.
    return HTTPError("https://provider.invalid/?key=" + FAKE_KEY, code,
                     PRIVATE_MESSAGE + FAKE_KEY,
                     {"x-goog-api-key": FAKE_KEY, "Private-Header": PRIVATE_MESSAGE}, body)


def error_body(code, status, reason=None):
    detail = {"code": code, "status": status, "message": PRIVATE_MESSAGE + FAKE_KEY}
    if reason:
        detail["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                              "reason": reason, "metadata": {"private": FAKE_KEY}}]
    return json.dumps({"error": detail}).encode()


class GeminiDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.document = read_document_bytes("synthetic.txt", b"Backups run daily.\n")
        self.request = {"task": "brief", "documents": [self.document]}
        self.provider = GeminiBriefGenerator(FAKE_KEY, enabled=True)
        transport_patch = patch("backend.gemini._send_request")
        self.transport = transport_patch.start()
        self.addCleanup(transport_patch.stop)

    def run_failure(self, code, raw):
        body = TrackingBody(raw)
        self.transport.side_effect = provider_error(code, body)
        result = analyze_documents(self.request, brief_generator=self.provider)
        self.assertEqual(result["mode"], "deterministic_demo")
        self.assertEqual(result["audit"]["status"], "passed")
        self.assertEqual(result["review"]["status"], "pending")
        self.assertEqual(result["provider_diagnostics"], result["audit_event"]["provider_diagnostics"])
        self.assertEqual(body.read_sizes, [MAX_ERROR_RESPONSE_BYTES])
        self.assertTrue(body.closed)
        self.assertNotIn(FAKE_KEY, json.dumps(result))
        self.assertNotIn(PRIVATE_MESSAGE, json.dumps(result))
        return result, body

    def test_http_classes_and_structured_google_fields(self):
        cases = [
            (400, "INVALID_ARGUMENT", None, "invalid_request"),
            (400, "FAILED_PRECONDITION", None, "failed_precondition"),
            (400, "INVALID_ARGUMENT", "API_KEY_INVALID", "authentication_failed"),
            (400, "INVALID_ARGUMENT", "API_KEY_EXPIRED", "authentication_failed"),
            (400, "INVALID_ARGUMENT", "API_KEY_NOT_FOUND", "authentication_failed"),
            (401, "UNAUTHENTICATED", None, "authentication_failed"),
            (402, "FAILED_PRECONDITION", "BILLING_DISABLED", "billing_required"),
            (403, "PERMISSION_DENIED", "API_KEY_SERVICE_BLOCKED", "permission_denied"),
            (404, "NOT_FOUND", None, "generation_not_found"),
            (408, "DEADLINE_EXCEEDED", None, "provider_timeout"),
            (413, "INVALID_ARGUMENT", None, "request_too_large"),
            (429, "RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED", "quota_exceeded"),
            (500, "INTERNAL", None, "provider_unavailable"),
            (503, "UNAVAILABLE", None, "provider_unavailable"),
            (504, "DEADLINE_EXCEEDED", None, "provider_timeout"),
        ]
        for code, status, reason, expected in cases:
            with self.subTest(http_status=code, google_status=status, google_reason=reason):
                result, _ = self.run_failure(code, error_body(code, status, reason))
                self.assertEqual(result["fallback_reason"], expected)
                self.assertEqual(result["provider_diagnostics"], {
                    "http_status": code, "google_status": status, "google_error_code": code,
                    "google_reason": reason, "model_id": DEFAULT_MODEL, "api_version": "v1beta",
                    "operation": "generateContent", "error_body_state": "parsed"})
        self.assertEqual(self.transport.call_count, len(cases))  # No automatic retry.

    def test_404_does_not_assume_model_invalid_or_hide_status_disagreement(self):
        result, _ = self.run_failure(404, error_body(429, "RESOURCE_EXHAUSTED", "RATE_LIMIT_EXCEEDED"))
        self.assertEqual(result["fallback_reason"], "generation_not_found")
        self.assertEqual(result["provider_diagnostics"]["http_status"], 404)
        self.assertEqual(result["provider_diagnostics"]["google_error_code"], 429)
        self.assertEqual(result["provider_diagnostics"]["google_status"], "RESOURCE_EXHAUSTED")

    def test_unparseable_errors_keep_http_classification(self):
        for raw in (b"", b"<html>upstream error</html>", b"\xff", b"[]", b"null", b'{"error": null}',
                    b'{"error": {"status": NaN}}'):
            with self.subTest(raw=raw):
                result, _ = self.run_failure(429, raw)
                self.assertEqual(result["fallback_reason"], "quota_exceeded")
                self.assertIsNone(result["provider_diagnostics"]["google_status"])
                self.assertEqual(result["provider_diagnostics"]["error_body_state"], "unparseable")

    def test_oversized_body_is_read_once_with_a_hard_byte_bound(self):
        raw = error_body(404, "NOT_FOUND")[:-2] + b" " * (MAX_ERROR_RESPONSE_BYTES * 3)
        result, body = self.run_failure(404, raw)
        self.assertEqual(body.bytes_read, MAX_ERROR_RESPONSE_BYTES)
        self.assertEqual(result["provider_diagnostics"]["error_body_state"], "limit_reached")
        self.assertIsNone(result["provider_diagnostics"]["google_status"])

    def test_body_read_failure_still_closes_response_and_falls_back(self):
        body = TrackingBody(b"unused")
        with patch.object(body, "read", side_effect=OSError(FAKE_KEY + PRIVATE_MESSAGE)) as read:
            self.transport.side_effect = provider_error(503, body)
            result = analyze_documents(self.request, brief_generator=self.provider)
        read.assert_called_once_with(MAX_ERROR_RESPONSE_BYTES)
        self.assertTrue(body.closed)
        self.assertEqual(result["fallback_reason"], "provider_unavailable")
        self.assertEqual(result["provider_diagnostics"]["error_body_state"], "unreadable")
        self.assertNotIn(FAKE_KEY, json.dumps(result))

    def test_unknown_fields_and_credential_echoes_are_discarded(self):
        raw = json.dumps({"error": {"code": True, "status": FAKE_KEY,
            "message": PRIVATE_MESSAGE, "model_id": FAKE_KEY, "api_version": FAKE_KEY,
            "details": [{"@type": "type.googleapis.com/google.rpc.LocalizedMessage", "message": FAKE_KEY},
                        {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": FAKE_KEY,
                         "metadata": {"document": PRIVATE_MESSAGE}}]},
            "request_headers": {"x-goog-api-key": FAKE_KEY}, "document": PRIVATE_MESSAGE}).encode()
        result, _ = self.run_failure(400, raw)
        diag = result["provider_diagnostics"]
        self.assertIsNone(diag["google_status"])
        self.assertIsNone(diag["google_error_code"])
        self.assertIsNone(diag["google_reason"])
        self.assertEqual(diag["model_id"], DEFAULT_MODEL)
        self.assertNotIn(self.document["text"].strip(), json.dumps(diag))

    def test_credential_cannot_escape_via_otherwise_allowlisted_strings(self):
        for key in ("NOT_FOUND", "MODEL_NOT_FOUND", DEFAULT_MODEL):
            with self.subTest(fake_credential=key):
                self.provider = GeminiBriefGenerator(key, enabled=True)
                self.transport.side_effect = provider_error(404, TrackingBody(error_body(404, "NOT_FOUND", "MODEL_NOT_FOUND")))
                result = analyze_documents(self.request, brief_generator=self.provider)
                self.assertNotIn(key, json.dumps(result))

