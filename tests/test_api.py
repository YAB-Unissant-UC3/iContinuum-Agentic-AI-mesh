"""Exercise the real local HTTP server with Python's standard HTTP client."""

import base64
import hashlib
from http.client import HTTPConnection
import json
from pathlib import Path
from threading import Thread
import unittest

from backend.server import create_server, MAX_FILE_BYTES, MAX_REQUEST_BYTES
from document_reader import read_document


ROOT = Path(__file__).resolve().parents[1]


def upload(name="document.txt", data=b"First\r\n\r\nLast\n"):
    return {"file_name": name, "content_base64": base64.b64encode(data).decode("ascii")}


class WorkspaceAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0)
        cls.thread = Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method, path, payload=None, headers=None, raw_body=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        self.addCleanup(connection.close)
        body = json.dumps(payload) if raw_body is None and payload is not None else raw_body
        request_headers = {"Content-Type": "application/json"} if body is not None else {}
        request_headers.update(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        if response.getheader("Content-Type", "").startswith("application/json"):
            data = json.loads(data)
        return response.status, data, response

    def test_health_reports_real_agent_availability(self):
        status, result, _ = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(result["agents"], {"reader": "ready", "analysis": "not_connected", "audit": "not_connected"})

    def test_upload_preserves_bytes_lines_and_identity(self):
        raw = "\ufeffCaf\u00e9\r\n\r\n  Original text  \n".encode("utf-8")
        status, result, _ = self.request("POST", "/api/documents", {"files": [upload(data=raw)]})
        self.assertEqual(status, 200)
        document = result["documents"][0]
        self.assertEqual(document["text"], raw.decode("utf-8"))
        self.assertEqual(document["document_id"], "doc_" + hashlib.sha256(raw).hexdigest())
        self.assertEqual(document["lines"][1], {"line_number": 2, "text": ""})
        self.assertEqual(document["lines"][2]["text"], "  Original text  ")
        self.assertEqual(document["source_path"], "document.txt")

    def test_demo_and_uploaded_files_have_identical_ids(self):
        status, result, _ = self.request("GET", "/api/demo")
        self.assertEqual(status, 200)
        self.assertEqual(len(result["documents"]), 3)
        for document in result["documents"]:
            path = ROOT / document["source_path"]
            self.assertEqual(document["document_id"], read_document(path)["document_id"])
            status, uploaded, _ = self.request("POST", "/api/documents", {"files": [upload(path.name, path.read_bytes())]})
            self.assertEqual(status, 200)
            self.assertEqual(uploaded["documents"][0]["document_id"], document["document_id"])

    def test_empty_invalid_encoding_and_unsupported_type_are_per_file_results(self):
        files = [upload(data=b""), upload("invalid.txt", b"\xff"), upload("source.pdf", b"PDF"), upload("ok.txt", b"ok")]
        status, result, _ = self.request("POST", "/api/documents", {"files": files})
        self.assertEqual(status, 200)
        self.assertEqual([item["status"] for item in result["documents"]], ["empty", "error", "error", "ok"])
        self.assertEqual(result["documents"][1]["error"]["code"], "invalid_encoding")
        self.assertEqual(result["documents"][2]["error"]["code"], "unsupported_file_type")

    def test_invalid_upload_envelopes_return_json_errors(self):
        cases = [
            ({}, "invalid_files"),
            ({"files": []}, "invalid_files"),
            ({"files": [upload()] * 13}, "invalid_files"),
            ({"files": [None]}, "invalid_file"),
            ({"files": [{"file_name": "../secret.txt", "content_base64": ""}]}, "invalid_filename"),
            ({"files": [{"file_name": "C:\\secret.txt", "content_base64": ""}]}, "invalid_filename"),
            ({"files": [{"file_name": "bad\x00.txt", "content_base64": ""}]}, "invalid_filename"),
            ({"files": [{"file_name": "document.txt"}]}, "invalid_content"),
            ({"files": [{"file_name": "document.txt", "content_base64": "!bad!"}]}, "invalid_base64"),
            ({"files": [{"file_name": "document.txt", "content_base64": "\u00e9"}]}, "invalid_base64"),
        ]
        for payload, code in cases:
            with self.subTest(code=code, payload=payload):
                status, result, _ = self.request("POST", "/api/documents", payload)
                self.assertEqual(status, 400)
                self.assertEqual(result["error"]["code"], code)

    def test_file_and_line_limits_are_enforced(self):
        cases = [
            ([upload(data=b"x" * (MAX_FILE_BYTES + 1))], "file_too_large"),
            ([upload(data=b"\n" * 10001)], "too_many_lines"),
            ([upload(data=b"x" * MAX_FILE_BYTES)] * 9, "file_too_large"),
        ]
        for files, code in cases:
            with self.subTest(code=code):
                status, result, _ = self.request("POST", "/api/documents", {"files": files})
                self.assertEqual(status, 413)
                self.assertEqual(result["error"]["code"], code)

    def test_valid_line_limit_boundary(self):
        status, result, _ = self.request("POST", "/api/documents", {"files": [upload(data=b"\n" * 10000)]})
        self.assertEqual(status, 200)
        self.assertEqual(result["documents"][0]["line_count"], 10000)

    def test_bad_json_and_media_type(self):
        for body in ["{bad", "[]", '"text"', "null"]:
            with self.subTest(body=body):
                status, result, _ = self.request("POST", "/api/documents", raw_body=body)
                self.assertEqual(status, 400)
                self.assertEqual(result["error"]["code"], "invalid_json")
        status, result, _ = self.request("POST", "/api/documents", {}, {"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.assertEqual(result["error"]["code"], "unsupported_media_type")

    def test_request_length_and_transfer_limits(self):
        cases = [
            ({"Content-Length": str(MAX_REQUEST_BYTES + 1)}, 413, "request_too_large"),
            ({"Content-Length": "9" * 5000}, 413, "request_too_large"),
            ({"Content-Length": "-1"}, 400, "invalid_length"),
            ({"Transfer-Encoding": "chunked"}, 400, "unsupported_transfer"),
        ]
        for headers, expected_status, code in cases:
            with self.subTest(code=code):
                status, result, _ = self.request("POST", "/api/documents", {}, headers)
                self.assertEqual(status, expected_status)
                self.assertEqual(result["error"]["code"], code)

    def test_analysis_is_explicitly_unavailable_without_fake_results(self):
        _, demo, _ = self.request("GET", "/api/demo")
        for task in ("brief", "requirements"):
            with self.subTest(task=task):
                status, result, _ = self.request("POST", "/api/analysis", {
                    "api_version": "1.0", "task": task, "documents": demo["documents"],
                })
                self.assertEqual(status, 501)
                self.assertEqual(result["error"]["code"], "analysis_not_connected")
                self.assertNotIn("claims", result)

    def test_analysis_request_checks_top_level_fields(self):
        for task in (None, "unknown", [], {}):
            with self.subTest(task=task):
                status, result, _ = self.request("POST", "/api/analysis", {"task": task, "documents": [{}]})
                self.assertEqual(status, 400)
                self.assertEqual(result["error"]["code"], "invalid_task")
        status, result, _ = self.request("POST", "/api/analysis", {"task": "brief", "documents": []})
        self.assertEqual(status, 400)
        self.assertEqual(result["error"]["code"], "invalid_documents")

    def test_host_and_cross_site_requests_are_rejected(self):
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                status, result, _ = self.request("GET", "/api/demo", headers=headers)
                self.assertEqual(status, 403)
                self.assertIn(result["error"]["code"], ("invalid_host", "invalid_origin"))

    def test_same_origin_request_is_allowed(self):
        origin = "http://127.0.0.1:{}".format(self.server.server_address[1])
        status, _, _ = self.request("POST", "/api/documents", {"files": [upload()]}, {"Origin": origin})
        self.assertEqual(status, 200)

    def test_only_frontend_assets_are_served(self):
        for path, expected_type in (("/", "text/html"), ("/styles.css", "text/css"), ("/app.js", "text/javascript")):
            status, body, response = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertTrue(response.getheader("Content-Type").startswith(expected_type))
            self.assertTrue(body)
            self.assertIn("script-src 'self'", response.getheader("Content-Security-Policy"))
        for path in ("/../README.md", "/.git/config", "/document_reader/reader.py", "/unknown"):
            with self.subTest(path=path):
                status, result, _ = self.request("GET", path)
                self.assertEqual(status, 404)
                self.assertEqual(result["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
