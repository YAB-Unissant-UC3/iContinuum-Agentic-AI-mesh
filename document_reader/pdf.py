"""Bounded PDF text extraction. Locations refer to extracted text, not OCR."""

import hashlib
from io import BytesIO
import logging
import re


MAX_PDF_BYTES = 256 * 1024
MAX_PAGES = 50
MAX_LINES = 10000
MAX_TEXT_CHARS = 256 * 1024
MAX_STREAM_BYTES = 4 * 1024 * 1024

# Parser recovery messages may contain untrusted PDF values. Never log them.
_logger = logging.getLogger("pypdf")
_logger.addHandler(logging.NullHandler())
_logger.propagate = False


def extract_pdf(document, raw_bytes):
    def fail(code, message):
        document["error"] = {"code": code, "message": message}
        return document

    if len(raw_bytes) > MAX_PDF_BYTES:
        return fail("file_too_large", "PDF files must be 256 KiB or smaller.")
    if not raw_bytes:
        return fail("invalid_pdf", "The PDF file contains no bytes.")
    try:
        from pypdf import PdfReader, __version__, apply_configuration
        from pypdf.errors import LimitReachedError
    except ImportError:
        return fail("pdf_dependency_missing", "Install the PDF dependency with python -m pip install -r requirements.txt.")

    try:
        # Context-local limits also bound compressed streams before extraction.
        with apply_configuration(
            maximum_declared_stream_length=MAX_STREAM_BYTES,
            array_based_stream_maximum_output_length=MAX_STREAM_BYTES,
            zlib_maximum_output_length=MAX_STREAM_BYTES,
            lzw_maximum_output_length=MAX_STREAM_BYTES,
            run_length_maximum_output_length=MAX_STREAM_BYTES,
            brotli_maximum_output_length=MAX_STREAM_BYTES,
            stream_decoding_work_maximum_length=MAX_STREAM_BYTES * 4,
            page_tree_maximum_entries=1000,
            page_tree_maximum_page_entries=1000,
            xform_maximum_invocations_per_extraction=100,
        ):
            reader = PdfReader(BytesIO(raw_bytes), strict=False,
                               root_object_recovery_limit=1000, xref_stream_maximum_entries=100000)
            if reader.is_encrypted:
                return fail("encrypted_pdf", "Encrypted PDFs are not supported. Supply an unencrypted synthetic copy.")
            if len(reader.pages) > MAX_PAGES:
                return fail("pdf_limit", "PDFs can contain at most 50 pages.")
            lines, pages, text_size = [], [], 0
            for page_number, page in enumerate(reader.pages, 1):
                contents = page.get_contents()
                if contents is not None and len(contents.get_data()) > MAX_STREAM_BYTES:
                    return fail("pdf_limit", "PDF page content exceeds the extraction limit.")
                text = page.extract_text(extraction_mode="layout") or ""
                text_size += len(text)
                if text_size > MAX_TEXT_CHARS:
                    return fail("pdf_limit", "Extracted PDF text exceeds 256 KiB of characters.")
                page_lines = re.split(r"\r\n|\r|\n", text) if text else []
                if text.endswith(("\r", "\n")):
                    page_lines.pop()
                if len(lines) + len(page_lines) > MAX_LINES:
                    return fail("pdf_limit", "Extracted PDF text exceeds 10,000 lines.")
                start = len(lines) + 1
                for page_line, value in enumerate(page_lines, 1):
                    lines.append({"line_number": len(lines) + 1, "text": value,
                                  "page_number": page_number, "page_line_number": page_line})
                pages.append({"page_number": page_number, "line_start": start if page_lines else None,
                              "line_end": len(lines) if page_lines else None, "line_count": len(page_lines)})
    except LimitReachedError:
        return fail("pdf_limit", "PDF processing exceeds the safe extraction limits.")
    except Exception:
        # Malformed PDFs can raise several parser/codec exception types. Do not
        # echo their messages (or partially extracted content) to users or logs.
        return fail("invalid_pdf", "The PDF could not be read safely. Supply a readable, unencrypted text PDF.")

    extracted = "\n".join(line["text"] for line in lines)
    document.update(document_id="doc_" + hashlib.sha256(raw_bytes).hexdigest(),
                    status="ok" if extracted.strip() else "empty", text=extracted,
                    lines=lines, line_count=len(lines), format="pdf", encoding="extracted-text",
                    page_count=len(pages), pages=pages,
                    extraction={"library": "pypdf", "version": __version__, "mode": "layout"})
    return document
