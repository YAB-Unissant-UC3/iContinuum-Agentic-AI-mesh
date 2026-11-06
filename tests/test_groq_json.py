"""Groq JSON-object compatibility, strict local structure, and safe fallback."""

import copy
from io import BytesIO
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from backend.analysis import analyze_documents
from backend.gemini import BRIEF_SCHEMA
from backend.groq import ENDPOINT, GROQ_SYSTEM_INSTRUCTION, GroqBriefGenerator, validate_brief_payload
from document_reader import read_document_bytes
from test_gemini import MockResponse, claim
from test_groq import FAKE_KEY, PRIVATE, groq_response


class GroqJSONTests(unittest.TestCase):
    def setUp(self):
        self.document = read_document_bytes("fictional.txt", (
            "The fictional pilot uses a shared Python backend with daily backups.\n"
            "\nRetain audit records for 30 days.\nRetain audit records for 90 days.\n").encode())
        self.request = {"task": "brief", "documents": [self.document]}
        self.payload = {"claims": [claim(self.document, "The fictional pilot uses daily backups and a shared Python backend.")]}
        self.provider = GroqBriefGenerator(FAKE_KEY, enabled=True)
        transport_patch = patch("backend.groq._send_request")
        self.transport = transport_patch.start()
        self.addCleanup(transport_patch.stop)
        self.transport.return_value = groq_response(self.payload)

    def run_brief(self):
        return analyze_documents(self.request, self.provider)

    def assert_invalid_payload(self, payload):
        self.transport.return_value = groq_response(payload)
        with patch("backend.groq.normalize_brief") as normalize:
            result = self.run_brief()
            normalize.assert_not_called()
        self.assertEqual(result["mode"], "deterministic_demo")
        self.assertEqual(result["fallback_reason"], "invalid_response")
        self.assertEqual(result["audit_event"]["generation_mode"], "deterministic_demo")
        self.assertEqual(result["audit_event"]["fallback_reason"], "invalid_response")
        self.assertTrue(result["contradictions"])
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assertNotIn(FAKE_KEY, json.dumps(result))

    def test_one_page_shape_stays_ai_generated_with_unchanged_citations(self):
        # This mock tests length/structure, not real model quality.
        sentence = "The fictional pilot uses daily backups and a shared Python backend. "
        sections = BRIEF_SCHEMA["properties"]["claims"]["items"]["properties"]["section"]["enum"]
        payload = {"claims": [claim(self.document, sentence * 10, section=section) for section in sections]}
        original = copy.deepcopy(payload)
        validate_brief_payload(payload)
        self.assertEqual(payload, original)  # Validation does not repair values.
        self.transport.return_value = groq_response(payload)
        result = self.run_brief()
        self.assertEqual(result["mode"], "groq")
        self.assertTrue(400 <= result["brief_word_count"] <= 550)
        self.assertEqual(result["audit"]["status"], "needs_review")
        self.assertEqual([c["section"] for c in result["claims"]], sections)
        self.assertEqual([c["citations"] for c in result["claims"]], [c["citations"] for c in payload["claims"]])
        body = json.loads(self.transport.call_args.args[0].data)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["messages"][0]["content"], GROQ_SYSTEM_INSTRUCTION)
        for field in ("claims", "section", "text", "citations", "document_id", "line_start", "line_end", "quote"):
            self.assertIn('"' + field + '"', GROQ_SYSTEM_INSTRUCTION)
        for section in sections:
            self.assertIn('"' + section + '"', GROQ_SYSTEM_INSTRUCTION)
        self.assertIn("400-550 narrative words TOTAL", GROQ_SYSTEM_INSTRUCTION)

    def test_missing_or_extra_fields_at_every_level_are_rejected(self):
        for level, fields in (("root", ("claims",)), ("claim", ("section", "text", "citations")),
                              ("citation", ("document_id", "line_start", "line_end", "quote"))):
            for field in fields + ("extra",):
                with self.subTest(level=level, field=field):
                    payload = copy.deepcopy(self.payload)
                    target = payload if level == "root" else payload["claims"][0]
                    if level == "citation":
                        target = target["citations"][0]
                    if field == "extra":
                        target[field] = PRIVATE
                    else:
                        del target[field]
                    self.assert_invalid_payload(payload)

    def test_wrong_types_invalid_sections_and_blank_text_are_rejected(self):
        for payload in (None, [], "text", {"claims": {}}, {"claims": [None]}, {"claims": [[]]}):
            with self.subTest(root_type=type(payload).__name__):
                self.assert_invalid_payload(payload)
        cases = [("section", None), ("section", []), ("section", "Summary"), ("section", " Overview"),
                 ("text", 42), ("text", ""), ("text", " \n "), ("text", "\ud800"),
                 ("citations", None), ("citations", {}), ("citations", [None])]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(self.payload)
                payload["claims"][0][field] = value
                self.assert_invalid_payload(payload)
        for field, value in (("document_id", 1), ("quote", []), ("line_start", "1"), ("line_end", 1.0),
                             ("line_start", True), ("line_end", False), ("quote", "\ud800")):
            with self.subTest(citation_field=field, value=value):
                payload = copy.deepcopy(self.payload)
                payload["claims"][0]["citations"][0][field] = value
                self.assert_invalid_payload(payload)

    def test_count_and_character_limits_reject_overflow(self):
        for count in (0, 25):
            with self.subTest(claim_count=count):
                payload = copy.deepcopy(self.payload)
                payload["claims"] *= count
                self.assert_invalid_payload(payload)
        for count in (0, 9):
            with self.subTest(citation_count=count):
                payload = copy.deepcopy(self.payload)
                payload["claims"][0]["citations"] *= count
                self.assert_invalid_payload(payload)
        for field, value in (("text", "x" * 4001), ("document_id", "d" * 129), ("quote", "q" * 10001),
                             ("text", "x " * 851)):
            with self.subTest(field=field, length=len(value)):
                payload = copy.deepcopy(self.payload)
                target = payload["claims"][0] if field == "text" else payload["claims"][0]["citations"][0]
                target[field] = value
                self.assert_invalid_payload(payload)

    def test_inclusive_bounds_validate_without_claiming_citation_accuracy(self):
        for count in (1, 24):
            payload = copy.deepcopy(self.payload)
            payload["claims"] *= count
            validate_brief_payload(payload)
        payload = copy.deepcopy(self.payload)
        payload["claims"][0]["citations"] *= 8
        validate_brief_payload(payload)
        for field, value in (("text", "x" * 4000), ("document_id", "d" * 128), ("quote", "q" * 10000),
                             ("text", "x " * 850)):
            with self.subTest(field=field, length=len(value)):
                payload = copy.deepcopy(self.payload)
                target = payload["claims"][0] if field == "text" else payload["claims"][0]["citations"][0]
                target[field] = value
                validate_brief_payload(payload)
        # These are structural bounds; fabricated sources/quotes still fail audit.

    def test_bad_citation_locations_and_quotes_stay_visible_audit_failures(self):
        cases = [("document_id", "doc_FABRICATED"), ("line_start", 0), ("line_start", -1),
                 ("line_end", 999), ("line_end", 0), ("quote", "Invented quote.")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(self.payload)
                payload["claims"][0]["citations"][0][field] = value
                validate_brief_payload(payload)
                self.transport.return_value = groq_response(payload)
                result = self.run_brief()
                self.assertEqual(result["mode"], "groq")
                self.assertEqual(result["audit"]["status"], "flagged")
                self.assertNotIn("fallback_reason", result)
                self.assertEqual(result["review"]["status"], "pending")

    def test_malformed_json_duplicate_fields_and_fences_are_not_repaired(self):
        valid = json.dumps(self.payload)
        invalid = [valid[:-1], valid + " trailing explanation", "```json\n" + valid + "\n```", "{\"claims\": [],}",
                   '{"claims": [], "claims": ' + valid[len('{"claims": '):],
                   valid.replace('"section": "Overview"', '"section": "Overview", "section": "Overview"'),
                   valid.replace('"line_start": 1', '"line_start": 1, "line_start": 1'),
                   valid.replace('"line_start": 1', '"line_start": NaN')]
        for output in invalid:
            with self.subTest(output_prefix=output[:30]):
                envelope = {"choices": [{"finish_reason": "stop", "message": {"content": output}}]}
                self.transport.return_value = MockResponse(json.dumps(envelope).encode())
                with patch("backend.groq.normalize_brief") as normalize:
                    result = self.run_brief()
                    normalize.assert_not_called()
                self.assertEqual(result["fallback_reason"], "invalid_response")
                self.assertEqual(result["mode"], "deterministic_demo")

    def test_truncation_rejects_even_a_parseable_partial_response(self):
        for finish in ("length", None):
            with self.subTest(finish_reason=finish):
                self.transport.return_value = groq_response(self.payload, finish=finish)
                with patch("backend.groq.validate_brief_payload") as validate, patch("backend.groq.normalize_brief") as normalize:
                    result = self.run_brief()
                    validate.assert_not_called()
                    normalize.assert_not_called()
                self.assertEqual(result["mode"], "deterministic_demo")
                self.assertEqual(result["fallback_reason"], "invalid_response")
        self.assertEqual(self.transport.call_count, 2)  # No retry on truncation.

    def test_json_validate_failed_is_output_failure_without_rescuing_failed_generation(self):
        for status in (400, 422):
            with self.subTest(status=status):
                failure = {"error": {"code": "json_validate_failed", "type": "invalid_request_error",
                    "message": FAKE_KEY + PRIVATE, "failed_generation": json.dumps(self.payload)}}
                self.transport.side_effect = HTTPError(ENDPOINT, status, PRIVATE, {}, BytesIO(json.dumps(failure).encode()))
                with patch("backend.groq.normalize_brief") as normalize:
                    result = self.run_brief()
                    normalize.assert_not_called()
                self.assertEqual(result["mode"], "deterministic_demo")
                self.assertEqual(result["fallback_reason"], "invalid_response")
                self.assertEqual(result["provider_diagnostics"]["failure_category"], "output_validation")
                self.assertEqual(result["provider_diagnostics"]["provider_error_code"], "json_validate_failed")
                self.assertEqual(result["provider_diagnostics"]["http_status"], status)
                self.assertNotIn(PRIVATE, json.dumps(result))
                self.assertNotIn(FAKE_KEY, json.dumps(result))
                self.assertNotIn(self.document["text"], json.dumps(result["provider_diagnostics"]))
        self.assertEqual(self.transport.call_count, 2)

    def test_model_cannot_set_server_owned_fields_even_in_json_object_mode(self):
        payload = copy.deepcopy(self.payload)
        payload.update(mode="groq", audit={"status": "passed"}, review={"status": "approved"}, contradictions=[])
        self.assert_invalid_payload(payload)

