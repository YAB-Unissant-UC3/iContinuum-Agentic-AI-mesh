"""Local Groq failure codes contain no model data or exception details."""

import copy
from http.client import HTTPConnection
from io import BytesIO
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from backend.analysis import analyze_documents
from backend.gemini import MAX_RESPONSE_BYTES, ProviderUnavailable
from backend.groq import (ENDPOINT, LOCAL_FAILURE_STAGES, LOCAL_FAILURE_CATEGORIES,
                          GroqBriefGenerator, _local_failure, _json_type)
from backend.server import create_server
from document_reader import read_document_bytes
from test_gemini import MockResponse, claim
from test_groq import FAKE_KEY, PRIVATE, groq_response


class GroqLocalDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.document = read_document_bytes("synthetic.txt", b"Backups run daily.\n")
        self.request = {"task": "brief", "documents": [self.document]}
        self.payload = {"claims": [claim(self.document)]}
        self.provider = GroqBriefGenerator(FAKE_KEY, enabled=True)
        transport_patch = patch("backend.groq._send_request")
        self.transport = transport_patch.start()
        self.addCleanup(transport_patch.stop)

    def assert_failure(self, response, stage, category, type_details=None):
        self.transport.return_value = response
        result = analyze_documents(self.request, self.provider)
        self.assertEqual(result["fallback_reason"], "invalid_response")
        self.assertEqual(result["mode"], "deterministic_demo")
        diag = result["provider_diagnostics"]
        expected = {"provider": "groq", "failure_stage": stage, "failure_category": category}
        expected.update(type_details or {})
        self.assertEqual(diag, expected)
        self.assertEqual(result["audit_event"]["provider_diagnostics"], diag)
        self.assertIn(diag["failure_stage"], LOCAL_FAILURE_STAGES)
        self.assertIn(diag["failure_category"], LOCAL_FAILURE_CATEGORIES)
        self.assertNotIn("http_status", diag)
        self.assertNotIn(self.document["text"].strip(), json.dumps(diag))
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assertNotIn(FAKE_KEY, json.dumps(result))
        return result

    def test_structure_failure_categories_are_distinct(self):
        cases = [("missing_field", lambda p: p["claims"][0].pop("text")),
                 ("extra_field", lambda p: p["claims"][0].update({PRIVATE: PRIVATE})),
                 ("invalid_type", lambda p: p["claims"][0].update(text=42)),
                 ("invalid_section", lambda p: p["claims"][0].update(section=PRIVATE)),
                 ("count_limit", lambda p: p.update(claims=[])),
                 ("length_limit", lambda p: p["claims"][0].update(text="x" * 4001)),
                 ("blank_text", lambda p: p["claims"][0].update(text=" \n ")),
                 ("invalid_encoding", lambda p: p["claims"][0].update(text="\ud800")),
                 ("invalid_type", lambda p: p["claims"][0]["citations"][0].update(line_start=True)),
                 ("length_limit", lambda p: p["claims"][0].update(text="x " * 851)),
                 ("count_limit", lambda p: p["claims"][0].update(citations=[]))]
        for category, mutate in cases:
            with self.subTest(category=category):
                payload = copy.deepcopy(self.payload)
                mutate(payload)
                details = None
                if category == "invalid_type":
                    details = ({"failure_field": "claim.text", "expected_type": "string", "actual_type": "integer"}
                               if payload["claims"][0]["text"] == 42 else
                               {"failure_field": "citation.line_start", "expected_type": "integer", "actual_type": "boolean"})
                self.assert_failure(groq_response(payload), "structure_validation", category, details)

    def test_each_structural_type_mismatch_reports_a_fixed_field_and_types(self):
        fields = [("root", (), "object"), ("claims", ("claims",), "array"),
                  ("claim", ("claims", 0), "object"),
                  ("claim.section", ("claims", 0, "section"), "string"),
                  ("claim.text", ("claims", 0, "text"), "string"),
                  ("claim.citations", ("claims", 0, "citations"), "array"),
                  ("citation", ("claims", 0, "citations", 0), "object"),
                  ("citation.document_id", ("claims", 0, "citations", 0, "document_id"), "string"),
                  ("citation.quote", ("claims", 0, "citations", 0, "quote"), "string"),
                  ("citation.line_start", ("claims", 0, "citations", 0, "line_start"), "integer"),
                  ("citation.line_end", ("claims", 0, "citations", 0, "line_end"), "integer")]
        values = [(None, "null"), ([], "array"), ({}, "object"), (PRIVATE, "string"),
                  (42, "integer"), (1.0, "number"), (True, "boolean"), (False, "boolean")]
        for field, path, expected_type in fields:
            for value, actual_type in values:
                if expected_type == actual_type:
                    continue
                with self.subTest(field=field, actual_type=actual_type):
                    payload = copy.deepcopy(self.payload)
                    if not path:
                        payload = copy.deepcopy(value)
                    else:
                        target = payload
                        for part in path[:-1]:
                            target = target[part]
                        target[path[-1]] = copy.deepcopy(value)
                    original = copy.deepcopy(payload)
                    with patch("backend.groq.normalize_brief") as normalize:
                        self.assert_failure(groq_response(payload), "structure_validation", "invalid_type", {
                            "failure_field": field, "expected_type": expected_type, "actual_type": actual_type})
                        normalize.assert_not_called()
                    self.assertEqual(payload, original)  # No coercion/repair.

    def test_type_diagnostic_fields_and_tags_are_closed_allowlists(self):
        basic = {"provider": "groq", "failure_stage": "structure_validation", "failure_category": "invalid_type"}
        for unknown in (PRIVATE, FAKE_KEY, "claims[" + PRIVATE + "]", None, []):
            with self.subTest(unknown_type=type(unknown).__name__):
                self.assertEqual(_local_failure("structure_validation", "invalid_type",
                    failure_field=unknown, actual_type="string").diagnostics, basic)
                self.assertEqual(_local_failure("structure_validation", "invalid_type",
                    failure_field="citation.line_start", actual_type=unknown).diagnostics, basic)
        for stage, category in (("content_json", "invalid_type"), ("structure_validation", "missing_field")):
            self.assertEqual(_local_failure(stage, category, failure_field="citation.quote", actual_type="array").diagnostics,
                {"provider": "groq", "failure_stage": stage, "failure_category": category})
        # Never derive a tag from a Python class name or object representation.
        class PrivateValue:
            def __str__(self):
                raise AssertionError("Diagnostic code must not stringify values")

            __repr__ = __str__

        self.assertEqual(_json_type(PrivateValue()), "unknown")

    def test_nested_invalid_type_values_never_leak_credentials_or_model_text(self):
        for field, value, tag in (("quote", [{FAKE_KEY: PRIVATE}], "array"),
                                  ("line_start", {PRIVATE: FAKE_KEY}, "object")):
            with self.subTest(field=field):
                payload = copy.deepcopy(self.payload)
                payload["claims"][0]["citations"][0][field] = value
                response = groq_response(payload)
                response.data = response.data.replace(FAKE_KEY.encode(),
                    "".join("\\u{:04x}".format(ord(char)) for char in FAKE_KEY).encode())
                self.assert_failure(response, "structure_validation", "invalid_type", {
                    "failure_field": "citation." + field,
                    "expected_type": "string" if field == "quote" else "integer", "actual_type": tag})

    def test_type_diagnostics_keep_existing_first_failure_order(self):
        payload = copy.deepcopy(self.payload)
        citation = payload["claims"][0]["citations"][0]
        citation.update(quote=[], line_start="1", line_end=False)
        self.assert_failure(groq_response(payload), "structure_validation", "invalid_type", {
            "failure_field": "citation.quote", "expected_type": "string", "actual_type": "array"})
        citation["quote"] = self.payload["claims"][0]["citations"][0]["quote"]
        self.assert_failure(groq_response(payload), "structure_validation", "invalid_type", {
            "failure_field": "citation.line_start", "expected_type": "integer", "actual_type": "string"})
        citation["line_start"] = 1
        self.assert_failure(groq_response(payload), "structure_validation", "invalid_type", {
            "failure_field": "citation.line_end", "expected_type": "integer", "actual_type": "boolean"})

    def test_response_json_and_content_json_have_different_stages(self):
        self.assert_failure(MockResponse(b"not JSON"), "response_json", "invalid_json")
        output = json.dumps(self.payload)
        for content in (output[:-1], "```json\n" + output + "\n```", output + " trailing prose"):
            with self.subTest(content_prefix=content[:10]):
                response = MockResponse(json.dumps({"choices": [{"finish_reason": "stop",
                    "message": {"content": content}}]}).encode())
                self.assert_failure(response, "content_json", "invalid_json")
        content = output.replace('"line_start": 1', '"line_start": NaN')
        response = MockResponse(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}]}).encode())
        self.assert_failure(response, "content_json", "invalid_json")

    def test_duplicate_fields_never_reveal_the_field_name(self):
        self.assert_failure(MockResponse(b'{"choices": [], "choices": []}'), "response_json", "duplicate_field")
        output = '{"' + PRIVATE + '": 1, "' + PRIVATE + '": 2}'
        response = MockResponse(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": output}}]}).encode())
        self.assert_failure(response, "content_json", "duplicate_field")

    def test_envelope_errors_remain_safe_and_specific(self):
        for value, category in (({}, "missing_field"), ({"choices": []}, "count_limit"),
                                ({"choices": [None]}, "invalid_type"), ({"choices": [{}]}, "missing_field")):
            with self.subTest(category=category):
                self.assert_failure(MockResponse(json.dumps(value).encode()), "response_envelope", category)
        response = MockResponse(json.dumps({"choices": [{"finish_reason": "stop", "message": {}}]}).encode())
        self.assert_failure(response, "content_json", "missing_field")

    def test_truncation_requires_explicit_length_finish_reason(self):
        self.assert_failure(groq_response(self.payload, finish="length"), "completion", "truncated_response")
        for finish in (None, "unknown_status", PRIVATE):
            with self.subTest(finish=finish):
                self.assert_failure(groq_response(self.payload, finish=finish), "completion", "unexpected_finish_reason")
        self.assert_failure(groq_response(self.payload, tool_calls=[{PRIVATE: PRIVATE}]), "completion", "unexpected_tool_call")
        response = MockResponse(b'{"choices":[{"finish_reason":"stop","message":{"content":"{\\"claims\\": ["}}]}')
        self.assert_failure(response, "content_json", "invalid_json")

    def test_response_size_encoding_and_normalization_failures(self):
        self.assert_failure(MockResponse(b"x" * (MAX_RESPONSE_BYTES + 1)), "response_read", "response_size_limit")
        self.assert_failure(MockResponse(b"\xff"), "response_decode", "invalid_encoding")
        with patch("backend.groq.normalize_brief", side_effect=ProviderUnavailable("invalid_response")):
            self.assert_failure(groq_response(self.payload), "normalization", "normalization_failed")
        self.transport.side_effect = ProviderUnavailable("invalid_response")
        self.assert_failure(groq_response(self.payload), "response_read", "validation_failed")

    def test_allowlists_reject_unknown_codes_and_escaped_secret_keys_do_not_leak(self):
        for value in (PRIVATE, FAKE_KEY, None, []):
            error = _local_failure(value, value)
            self.assertEqual(error.diagnostics, {"provider": "groq", "failure_stage": "local_processing",
                                                 "failure_category": "validation_failed"})
        for location in ("root", "claim", "citation"):
            with self.subTest(location=location):
                payload = copy.deepcopy(self.payload)
                target = payload if location == "root" else payload["claims"][0]
                if location == "citation":
                    target = target["citations"][0]
                target[FAKE_KEY] = PRIVATE
                response = groq_response(payload)
                response.data = response.data.replace(FAKE_KEY.encode(),
                    "".join("\\u{:04x}".format(ord(char)) for char in FAKE_KEY).encode())
                self.assert_failure(response, "structure_validation", "extra_field")

    def test_http_diagnostics_are_not_replaced_by_local_categories(self):
        for status, code, reason in ((400, "json_validate_failed", "invalid_response"),
                                     (429, "rate_limit_exceeded", "quota_exceeded")):
            with self.subTest(status=status):
                self.transport.side_effect = HTTPError(ENDPOINT, status, PRIVATE, {}, BytesIO(json.dumps({
                    "error": {"code": code, "message": FAKE_KEY + PRIVATE}}).encode()))
                result = analyze_documents(self.request, self.provider)
                self.assertEqual(result["fallback_reason"], reason)
                diag = result["provider_diagnostics"]
                self.assertEqual(diag["http_status"], status)
                self.assertEqual(diag["provider_error_code"], code)
                self.assertNotIn("failure_stage", diag)
                self.assertEqual(result["audit_event"]["provider_diagnostics"], diag)
                self.assertNotIn(FAKE_KEY, json.dumps(result))
                self.assertNotIn(PRIVATE, json.dumps(result))

    def test_local_diagnostics_persist_in_http_result_saved_run_and_audit_log(self):
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
                wrong_line = copy.deepcopy(self.payload)
                wrong_line["claims"][0]["citations"][0]["line_end"] = "1"
                cases = [(groq_response({"claims": []}), "structure_validation", "count_limit", {}),
                         (groq_response(self.payload, finish="length"), "completion", "truncated_response", {}),
                         (groq_response(wrong_line), "structure_validation", "invalid_type", {
                             "failure_field": "citation.line_end", "expected_type": "integer", "actual_type": "string"})]
                for response, stage, category, type_details in cases:
                    self.transport.return_value = response
                    status, result, _ = call("POST", "/api/analysis", {"task": "brief",
                        "document_ids": [docs["documents"][0]["document_id"]]}, cookie)
                    self.assertEqual(status, 200)
                    expected = {"provider": "groq", "failure_stage": stage, "failure_category": category}
                    expected.update(type_details)
                    self.assertEqual(result["provider_diagnostics"], expected)
                    self.assertEqual(result["fallback_reason"], "invalid_response")
                    self.assertEqual(result["mode"], "deterministic_demo")
                    self.assertEqual(result["audit"]["status"], "passed")
                    route = "/api/analysis/" + result["analysis_id"]
                    _, saved, _ = call("GET", route, cookie=cookie)
                    _, trail, _ = call("GET", route + "/audit", cookie=cookie)
                    self.assertEqual(saved["provider_diagnostics"], expected)
                    self.assertEqual(trail["events"][0]["provider_diagnostics"], expected)
                log = Path(folder, "audit.jsonl").read_text(encoding="utf-8")
                for private in (FAKE_KEY, PRIVATE, docs["documents"][0]["text"].strip()):
                    self.assertNotIn(private, log)
                records = [json.loads(line) for line in log.splitlines()]
                self.assertEqual(len(records), 3)
                self.assertEqual(records[-1]["provider_diagnostics"], expected)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(5)
