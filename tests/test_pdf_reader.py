"""PDF extraction checks use synthetic fixtures only, without network access."""

import hashlib
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from document_reader import read_document, read_document_bytes
from document_reader.pdf import MAX_PDF_BYTES, MAX_PAGES, MAX_STREAM_BYTES


SAMPLES = Path(__file__).resolve().parents[1] / "sample_documents"
STORY_NAMES = ("DOC-001_statement_ajmain.txt", "DOC-002_statement_saaiem.pdf",
               "DOC-003_statement_rifat.txt", "DOC-004_eyewitness_priya.pdf", "DOC-005_police_report.pdf")


def make_pdf(*texts, encrypted=False):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(612, 792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(("BT /F1 12 Tf 30 750 Td (" + escaped + ") Tj ET").encode("ascii"))
        page[NameObject("/Contents")] = stream
    if encrypted:
        writer.encrypt("synthetic-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class PDFReaderTests(unittest.TestCase):
    def test_all_five_story_documents_have_stable_raw_byte_ids_and_readable_text(self):
        for name in STORY_NAMES:
            with self.subTest(name=name):
                path = SAMPLES / name
                document = read_document(path)
                self.assertEqual(document["status"], "ok", document["error"])
                self.assertEqual(document["document_id"], "doc_" + hashlib.sha256(path.read_bytes()).hexdigest())
                uploaded = read_document_bytes(name, path.read_bytes())
                for field in ("document_id", "text", "lines"):
                    self.assertEqual(document[field], uploaded[field])
                self.assertGreater(len(document["text"].strip()), 100)

    def test_page_counts_and_exact_page_by_page_line_mapping(self):
        for name, count in ((STORY_NAMES[1], 2), (STORY_NAMES[3], 1), (STORY_NAMES[4], 2)):
            with self.subTest(name=name):
                document = read_document(SAMPLES / name)
                self.assertEqual(document["page_count"], count)
                self.assertEqual(document["text"], "\n".join(line["text"] for line in document["lines"]))
                reader = PdfReader(SAMPLES / name)
                for number, page in enumerate(reader.pages, 1):
                    original = page.extract_text(extraction_mode="layout").splitlines()
                    extracted = [line for line in document["lines"] if line["page_number"] == number]
                    self.assertEqual([line["text"] for line in extracted], original)
                    self.assertEqual([line["page_line_number"] for line in extracted], list(range(1, len(original) + 1)))
                    meta = document["pages"][number - 1]
                    self.assertEqual(meta["line_start"], extracted[0]["line_number"])
                    self.assertEqual(meta["line_end"], extracted[-1]["line_number"])
                self.assertEqual([line["line_number"] for line in document["lines"]], list(range(1, document["line_count"] + 1)))

    def test_police_table_preserves_column_relationships_and_report_details(self):
        document = read_document(SAMPLES / STORY_NAMES[4])
        rows = [line["text"] for line in document["lines"] if line["page_number"] == 1]
        for person, description in (("Ajmain", "red hoodie"), ("Saaiem", "gray beanie"), ("Rifat", "green jacket")):
            row = next(row for row in rows if "Involved party" in row and person in row)
            self.assertIn(description, row)
            self.assertIn("On file", row)
        witness = next(row for row in rows if "Priya Nandkumar" in row)
        self.assertIn("Female student, headphones", witness)
        self.assertIn("(555) 555-0142", witness)
        self.assertTrue(any("Role" in row and "Name" in row and "Contact" in row for row in rows))
        self.assertIn("No arrests", document["text"])

    def test_same_bytes_renamed_pdf_keep_identity(self):
        raw = make_pdf("Synthetic evidence")
        self.assertEqual(read_document_bytes("first.pdf", raw)["document_id"], read_document_bytes("renamed.PDF", raw)["document_id"])

    def test_empty_pages_have_no_invented_text_or_ocr(self):
        document = read_document_bytes("blank.pdf", make_pdf(""))
        self.assertEqual(document["status"], "empty")
        self.assertEqual(document["page_count"], 1)
        self.assertEqual(document["pages"][0]["line_count"], 0)
        self.assertEqual(document["text"], "")

    def test_encrypted_pdf_is_rejected_without_decrypting(self):
        document = read_document_bytes("secret.pdf", make_pdf("Do not expose", encrypted=True))
        self.assertEqual(document["error"]["code"], "encrypted_pdf")
        self.assertEqual(document["text"], "")
        self.assertIsNone(document["document_id"])

    def test_malformed_and_zero_byte_pdfs_return_safe_errors(self):
        for raw in (b"", b"not a PDF SENSITIVE_TEST_VALUE", b"%PDF-1.4\ntruncated"):
            document = read_document_bytes("broken.pdf", raw)
            self.assertEqual(document["error"]["code"], "invalid_pdf")
            self.assertEqual(document["lines"], [])
            self.assertNotIn("SENSITIVE_TEST_VALUE", repr(document))

    def test_oversized_pdf_is_rejected_before_parser(self):
        with patch("pypdf.PdfReader") as parser:
            document = read_document_bytes("large.pdf", b"x" * (MAX_PDF_BYTES + 1))
            parser.assert_not_called()
        self.assertEqual(document["error"]["code"], "file_too_large")

    def test_page_count_limit(self):
        document = read_document_bytes("many.pdf", make_pdf(*([""] * (MAX_PAGES + 1))))
        self.assertEqual(document["error"]["code"], "pdf_limit")
        self.assertEqual(document["lines"], [])

    def test_decompression_limit_rejects_small_compressed_bomb(self):
        writer = PdfWriter()
        page = writer.add_blank_page(612, 792)
        stream = DecodedStreamObject()
        stream.set_data(b" " * (MAX_STREAM_BYTES + 1))
        page[NameObject("/Contents")] = stream.flate_encode()
        output = BytesIO()
        writer.write(output)
        self.assertLess(len(output.getvalue()), MAX_PDF_BYTES)
        document = read_document_bytes("compressed.pdf", output.getvalue())
        self.assertEqual(document["error"]["code"], "pdf_limit")
        self.assertEqual(document["text"], "")

    def test_extracted_text_and_line_limits(self):
        for text in ("x" * (256 * 1024 + 1), "x\n" * 10001):
            with self.subTest(length=len(text)), patch("pypdf._page.PageObject.extract_text", return_value=text):
                document = read_document_bytes("bounded.pdf", make_pdf("small"))
                self.assertEqual(document["error"]["code"], "pdf_limit")
                self.assertEqual(document["lines"], [])

    def test_parser_exceptions_do_not_leak_text_to_logs_or_response(self):
        with patch("pypdf._page.PageObject.extract_text", side_effect=RuntimeError("SENSITIVE_TEST_VALUE")):
            document = read_document_bytes("bad.pdf", make_pdf("small"))
        self.assertEqual(document["error"]["code"], "invalid_pdf")
        self.assertNotIn("SENSITIVE_TEST_VALUE", repr(document))

    def test_local_pdf_read_failures_return_structured_errors(self):
        for exception, code in ((PermissionError("denied"), "permission_denied"), (OSError("unreadable"), "read_error")):
            with patch("document_reader.reader.Path.open", side_effect=exception):
                document = read_document("unreadable.pdf")
            self.assertEqual(document["error"]["code"], code)
            self.assertEqual(document["text"], "")

    def test_missing_dependency_is_reported_safely(self):
        with patch.dict("sys.modules", {"pypdf": None}):
            document = read_document_bytes("source.pdf", b"%PDF-1.4")
        self.assertEqual(document["error"]["code"], "pdf_dependency_missing")
        self.assertEqual(document["lines"], [])
