"""Safe Groq HTTP diagnostics and real opener processing without network I/O."""

from http.client import HTTPConnection
from io import BytesIO
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

from backend.analysis import analyze_documents
from backend.gemini import _NoRedirect
from backend.groq import ENDPOINT, MAX_ERROR_RESPONSE_BYTES, GroqBriefGenerator
from backend.server import create_server
from document_reader import read_document_bytes


FAKE_KEY = "GROQ_DIAGNOSTIC_FAKE_CREDENTIAL_293ac"
PRIVATE = "PRIVATE_ERROR_AND_DOCUMENT_TEXT_NOT_FOR_DIAGNOSTICS"


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


class GroqDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.document = read_document_bytes("synthetic.txt", b"Backups run daily.\n")
        self.request = {"task": "brief", "documents": [self.document]}
        self.provider = GroqBriefGenerator(FAKE_KEY, enabled=True)

    def failure(self, raw, content_type=None, status=403):
        body = TrackingBody(raw)
        headers = {"Authorization": "Bearer " + FAKE_KEY, "Private-Header": PRIVATE}
        if content_type is not None:
            headers["Content-Type"] = content_type
        failure = HTTPError(ENDPOINT + "?private=" + FAKE_KEY, status, PRIVATE + FAKE_KEY, headers, body)
        with patch("backend.groq._send_request", side_effect=failure) as transport, \
                patch("backend.gemini._send_request") as gemini:
            result = analyze_documents(self.request, self.provider)
            transport.assert_called_once()
            gemini.assert_not_called()
        self.assertEqual(body.read_sizes, [MAX_ERROR_RESPONSE_BYTES])
        self.assertTrue(body.closed)
        self.assertLessEqual(body.bytes_read, MAX_ERROR_RESPONSE_BYTES)
        self.assertEqual(result["mode"], "deterministic_demo")
        self.assertEqual(result["audit"]["status"], "passed")
        self.assertEqual(result["review"]["status"], "pending")
        self.assertNotIn(FAKE_KEY, json.dumps(result))
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assertEqual(result["provider_diagnostics"], result["audit_event"]["provider_diagnostics"])
        return result, body

    def test_actual_opener_preserves_application_headers_without_connecting(self):
        captured = []

        class CaptureHTTPS(HTTPSHandler):
            def https_open(self, request):
                captured.append(request)
                raise URLError("Offline test transport")

        # Disable automatic proxy discovery, then replace the HTTPS handler.
        # The real _send_request and urllib header preparation still run.
        opener = build_opener(ProxyHandler({}), _NoRedirect(), CaptureHTTPS())
        with patch("backend.groq.build_opener", return_value=opener) as factory, \
                patch("socket.create_connection", side_effect=AssertionError("Network forbidden")) as connect:
            result = analyze_documents(self.request, self.provider)
            connect.assert_not_called()
        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("User-agent"), "iContinuum-PoC/1.0")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + FAKE_KEY)
        self.assertEqual(request.get_header("Content-length"), str(len(request.data)))
        body = json.loads(request.data)
        self.assertEqual(body["model"], "openai/gpt-oss-20b")
        self.assertEqual(body["max_completion_tokens"], 4096)
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertFalse(body["include_reasoning"])
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIsInstance(factory.call_args.args[0], _NoRedirect)
        self.assertEqual(result["fallback_reason"], "provider_unavailable")

    def test_non_json_and_unexpected_json_403_are_unclassified_forbidden(self):
        cases = [(b"<html><body>Access denied</body></html>", "Text/HTML; charset=UTF-8", "html", "text/html"),
                 (b"Access denied", "text/plain", "plain_text", "text/plain"),
                 (b"", None, "empty", None),
                 (b"\xff\xfe", "application/octet-stream", "undecodable", "application/octet-stream"),
                 (b'{"error":', "application/json", "plain_text", "application/json"),
                 (b'{"message": "Access denied"}', "application/json", "json", "application/json"),
                 (b"[]", "application/json", "json", "application/json"),
                 (b"null", "application/json", "json", "application/json")]
        for raw, header, category, mime in cases:
            with self.subTest(category=category, raw=raw):
                result, _ = self.failure(raw, header)
                self.assertEqual(result["fallback_reason"], "http_forbidden")
                diag = result["provider_diagnostics"]
                self.assertEqual(diag["response_content_type"], mime)
                self.assertEqual(diag["body_category"], category)
                self.assertEqual(diag["response_body_bytes"], len(raw))
                self.assertEqual(diag["failure_category"], "forbidden_unclassified")
                self.assertIsNone(diag["edge_error_code"])
                self.assertEqual(diag["error_body_state"], "unparseable")

    def test_recognized_edge_marker_is_a_clue_not_a_permission_verdict(self):
        cases = [(b"error code: 1010", "plain_text"),
                 (b"<html><h1>Error 1010</h1><p>Cloudflare</p></html>", "html")]
        for raw, category in cases:
            with self.subTest(category=category):
                result, _ = self.failure(raw)
                diag = result["provider_diagnostics"]
                self.assertEqual(result["fallback_reason"], "http_forbidden")
                self.assertEqual(diag["body_category"], category)
                self.assertEqual(diag["edge_error_code"], "1010")
                self.assertEqual(diag["failure_category"], "edge_block_suspected")
        for raw in (b"error code: 9999", b"Source document mentions error code: 1010", b"<html>Error 1010</html>"):
            result, _ = self.failure(raw)
            self.assertIsNone(result["provider_diagnostics"]["edge_error_code"])

    def test_documented_model_and_general_permission_errors(self):
        for code, category in (("model_permission_blocked_org", "model_permission"),
                               ("model_permission_blocked_project", "model_permission"),
                               (None, "provider_permission")):
            with self.subTest(code=code):
                raw = json.dumps({"error": {"code": code, "type": "permissions_error",
                                           "message": PRIVATE + FAKE_KEY}}).encode()
                result, _ = self.failure(raw, "application/json")
                self.assertEqual(result["fallback_reason"], "permission_denied")
                diag = result["provider_diagnostics"]
                self.assertEqual(diag["provider_error_code"], code)
                self.assertEqual(diag["provider_error_type"], "permissions_error")
                self.assertEqual(diag["body_category"], "json")
                self.assertEqual(diag["failure_category"], category)
                self.assertEqual(diag["error_body_state"], "parsed")

    def test_body_bound_is_single_read_and_byte_count_is_not_total_length(self):
        raw = (PRIVATE + FAKE_KEY).encode() * MAX_ERROR_RESPONSE_BYTES
        result, body = self.failure(raw, "text/plain")
        self.assertEqual(body.bytes_read, MAX_ERROR_RESPONSE_BYTES)
        self.assertEqual(result["provider_diagnostics"]["response_body_bytes"], MAX_ERROR_RESPONSE_BYTES)
        self.assertEqual(result["provider_diagnostics"]["error_body_state"], "limit_reached")

    def test_read_failure_remains_safe_and_response_is_closed(self):
        body = TrackingBody(b"unused")
        with patch.object(body, "read", side_effect=OSError(PRIVATE + FAKE_KEY)) as read, \
                patch("backend.groq._send_request", side_effect=HTTPError(ENDPOINT, 403, FAKE_KEY, {}, body)):
            result = analyze_documents(self.request, self.provider)
        read.assert_called_once_with(MAX_ERROR_RESPONSE_BYTES)
        self.assertTrue(body.closed)
        self.assertEqual(result["fallback_reason"], "http_forbidden")
        self.assertIsNone(result["provider_diagnostics"]["response_body_bytes"])
        self.assertIsNone(result["provider_diagnostics"]["body_category"])
        self.assertEqual(result["provider_diagnostics"]["error_body_state"], "unreadable")
        self.assertNotIn(FAKE_KEY, json.dumps(result))

    def test_untrusted_headers_body_fields_and_escaped_credentials_are_discarded(self):
        raw = json.dumps({"error": {"type": FAKE_KEY, "code": PRIVATE,
            "message": PRIVATE, "body_category": FAKE_KEY, "failure_category": FAKE_KEY,
            "response_content_type": FAKE_KEY, "request": self.document["text"]}}).replace(
                FAKE_KEY, "".join("\\u{:04x}".format(ord(c)) for c in FAKE_KEY)).encode()
        for header, mime in (("TEXT/PLAIN; private=" + FAKE_KEY, "text/plain"),
                             ("application/" + FAKE_KEY, "other"), (PRIVATE, "other")):
            with self.subTest(content_type=header):
                result, _ = self.failure(raw, header)
                diag = result["provider_diagnostics"]
                self.assertEqual(diag["response_content_type"], mime)
                self.assertEqual(diag["failure_category"], "forbidden_unclassified")
                self.assertIsNone(diag["provider_error_code"])
                self.assertIsNone(diag["provider_error_type"])
                self.assertNotIn(self.document["text"].strip(), json.dumps(diag))
                self.assertEqual(set(diag), {"provider", "http_status", "provider_error_code", "provider_error_type",
                    "model_id", "api_version", "operation", "error_body_state", "response_content_type",
                    "response_body_bytes", "body_category", "edge_error_code", "failure_category"})

    def test_safe_diagnostics_persist_through_http_result_and_existing_audit_trail(self):
        with tempfile.TemporaryDirectory() as folder:
            server = create_server(0, data_dir=folder, brief_generator=self.provider)
            thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
            thread.start()

            def call(method, route, payload=None, cookie=None):
                connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                try:
                    headers = {"Content-Type": "application/json"}
                    if cookie:
                        headers["Cookie"] = cookie
                    connection.request(method, route, json.dumps(payload) if payload is not None else None, headers)
                    response = connection.getresponse()
                    return response.status, json.loads(response.read()), response.getheader("Set-Cookie")
                finally:
                    connection.close()

            try:
                _, _, cookie = call("POST", "/api/login", {"username": "analyst", "password": "AnalystDemo!2026"})
                cookie = cookie.split(";", 1)[0]
                _, docs, _ = call("GET", "/api/demo", cookie=cookie)
                raw = ("<html><body>" + PRIVATE + FAKE_KEY + "</body></html>").encode()
                failure = HTTPError(ENDPOINT, 403, FAKE_KEY, {"Content-Type": "text/html"}, TrackingBody(raw))
                with patch("backend.groq._send_request", side_effect=failure):
                    status, result, _ = call("POST", "/api/analysis", {"task": "brief",
                        "document_ids": [docs["documents"][0]["document_id"]]}, cookie)
                self.assertEqual(status, 200)
                self.assertEqual(result["fallback_reason"], "http_forbidden")
                self.assertEqual(result["audit"]["status"], "passed")
                _, trail, _ = call("GET", "/api/analysis/" + result["analysis_id"] + "/audit", cookie=cookie)
                self.assertEqual(trail["events"][0]["provider_diagnostics"], result["provider_diagnostics"])
                log = Path(folder, "audit.jsonl").read_text(encoding="utf-8")
                for private in (FAKE_KEY, PRIVATE, docs["documents"][0]["text"].strip()):
                    self.assertNotIn(private, log)
                for private in (FAKE_KEY, PRIVATE):
                    self.assertNotIn(private, json.dumps([result, trail]))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(5)
