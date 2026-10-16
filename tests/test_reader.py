"""Run from the repository root: python -m unittest discover -s tests -v"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from document_reader import read_document


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class DocumentReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.folder = Path(self.temporary_directory.name)

    def write_file(self, contents, name="document.txt"):
        path = self.folder / name
        path.write_bytes(contents)
        return path

    def run_cli(self, *paths):
        return subprocess.run(
            [sys.executable, "-m", "document_reader", *map(str, paths)],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_original_text_and_numbered_lines_are_preserved(self):
        original = "  First line  \r\n\r\nThird line\nFinal line\r"
        path = self.write_file(original.encode("utf-8"))
        result = read_document(path)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["error"])
        self.assertEqual(result["text"], original)
        self.assertEqual(result["line_count"], 4)
        self.assertEqual(result["lines"], [
            {"line_number": 1, "text": "  First line  "},
            {"line_number": 2, "text": ""},
            {"line_number": 3, "text": "Third line"},
            {"line_number": 4, "text": "Final line"},
        ])
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_id_is_repeatable_and_matches_sha256(self):
        content = b"Evidence\n"
        path = self.write_file(content)
        first = read_document(path)
        self.assertEqual(first["document_id"], read_document(path)["document_id"])
        self.assertEqual(first["document_id"], "doc_" + hashlib.sha256(content).hexdigest())

    def test_identical_copies_and_renames_keep_the_same_id(self):
        first = self.write_file(b"Same contents", "first.txt")
        copy = self.write_file(b"Same contents", "copy.txt")
        expected = read_document(first)["document_id"]
        self.assertEqual(read_document(copy)["document_id"], expected)
        renamed = first.rename(self.folder / "renamed.txt")
        self.assertEqual(read_document(renamed)["document_id"], expected)

    def test_changed_contents_and_line_endings_change_the_id(self):
        ids = [
            read_document(self.write_file(content))["document_id"]
            for content in (b"First\n", b"Second\n", b"First\r\n")
        ]
        self.assertEqual(len(set(ids)), 3)

    def test_empty_file_has_an_id_and_no_lines(self):
        result = read_document(self.write_file(b""))
        self.assertEqual(result["status"], "empty")
        self.assertIsNotNone(result["document_id"])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["lines"], [])
        self.assertEqual(result["line_count"], 0)
        self.assertIsNone(result["error"])

    def test_line_boundaries_and_whitespace(self):
        cases = [
            ("one", ["one"]),
            ("one\n", ["one"]),
            ("\n", [""]),
            ("\n\n", ["", ""]),
            ("one\n\n", ["one", ""]),
            (" \t", [" \t"]),
            ("one\rtwo", ["one", "two"]),
            ("one\vtwo\u2028three", ["one\vtwo\u2028three"]),
        ]
        for original, expected in cases:
            with self.subTest(original=repr(original)):
                result = read_document(self.write_file(original.encode("utf-8")))
                self.assertEqual(result["text"], original)
                self.assertEqual([line["text"] for line in result["lines"]], expected)
                self.assertEqual(result["line_count"], len(expected))

    def test_unicode_and_utf8_byte_order_mark_are_preserved(self):
        original = "\ufeffCaf\u00e9 \u2014 \u6771\u4eac\n"
        result = read_document(self.write_file(original.encode("utf-8"), "UNICODE.TXT"))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["text"], original)
        self.assertEqual(result["lines"][0]["text"], original[:-1])

    def test_missing_file_returns_a_structured_error(self):
        result = read_document(self.folder / "missing.txt")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "file_not_found")
        self.assertIsNone(result["document_id"])
        self.assertEqual(result["lines"], [])

    def test_permission_and_other_read_failures_are_safe(self):
        cases = [
            (PermissionError("Access denied"), "permission_denied"),
            (OSError("Device unavailable"), "read_error"),
        ]
        for exception, expected_code in cases:
            with self.subTest(code=expected_code):
                # Simulate failures so this test works regardless of OS permissions.
                with patch("document_reader.reader.Path.read_bytes", side_effect=exception):
                    result = read_document(self.folder / "unreadable.txt")
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["error"]["code"], expected_code)
                self.assertIsNone(result["document_id"])
                self.assertEqual(result["text"], "")

    def test_directory_returns_a_structured_error(self):
        path = self.folder / "directory.txt"
        path.mkdir()
        result = read_document(path)
        self.assertEqual(result["status"], "error")
        self.assertIsNotNone(result["error"])

    def test_invalid_utf8_is_reported_without_replacing_text(self):
        result = read_document(self.write_file(b"valid prefix\xff"))
        self.assertEqual(result["error"]["code"], "invalid_encoding")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["text"], "")
        self.assertIsNone(result["document_id"])

    def test_non_txt_files_are_rejected(self):
        result = read_document(self.write_file(b"not supported", "document.pdf"))
        self.assertEqual(result["error"]["code"], "unsupported_file_type")
        self.assertEqual(result["status"], "error")

    def test_all_three_synthetic_documents_have_valid_citations(self):
        folder = REPOSITORY_ROOT / "sample_documents"
        results = [read_document(path) for path in sorted(folder.glob("*.txt"))]
        self.assertEqual(len(results), 3)
        self.assertEqual(len({result["document_id"] for result in results}), 3)
        for result in results:
            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["text"].startswith("FICTIONAL SYNTHETIC DOCUMENT"))
            self.assertEqual(result["line_count"], len(result["lines"]))
        requirements = read_document(folder / "requirements.txt")
        notes = read_document(folder / "meeting_notes.txt")
        self.assertEqual(requirements["lines"][8], {
            "line_number": 9,
            "text": "REQ-006: Retain audit records for 30 days.",
        })
        self.assertIn("90 days", notes["lines"][7]["text"])

    def test_cli_prints_json_for_a_valid_document(self):
        path = self.write_file("Caf\u00e9\n".encode("utf-8"))
        process = self.run_cli(path)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, "")
        self.assertEqual(json.loads(process.stdout)["documents"], [read_document(path)])

    def test_cli_continues_after_an_error_and_exits_with_one(self):
        valid = self.write_file(b"Evidence\n")
        empty = self.write_file(b"", "empty.txt")
        process = self.run_cli(self.folder / "missing.txt", valid, empty)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(process.stderr, "")
        results = json.loads(process.stdout)["documents"]
        self.assertEqual([result["status"] for result in results], ["error", "ok", "empty"])

    def test_cli_requires_at_least_one_file(self):
        process = self.run_cli()
        self.assertEqual(process.returncode, 2)
        self.assertIn("usage:", process.stderr)


if __name__ == "__main__":
    unittest.main()
