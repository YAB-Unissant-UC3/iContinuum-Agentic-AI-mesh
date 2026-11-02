"""Read UTF-8 text files without summarizing or changing their contents."""

import hashlib
from pathlib import Path
import re
from typing import Union


def _empty_document(path: Path) -> dict:
    return {
        "schema_version": "1.0",
        "document_id": None,
        "file_name": path.name,
        "source_path": str(path),
        "encoding": "utf-8",
        "status": "error",
        "text": "",
        "line_count": 0,
        "lines": [],
        "error": None,
    }


def read_document(file_path: Union[str, Path]) -> dict:
    """Read a local file. IDs identify exact bytes, independent of location."""
    path = Path(file_path)
    document = _empty_document(path)
    if path.suffix.lower() != ".txt":
        document["error"] = {
            "code": "unsupported_file_type",
            "message": "Only .txt files are supported.",
        }
        return document

    try:
        # Reading bytes avoids automatically changing Windows line endings.
        raw_bytes = path.read_bytes()
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            code = "file_not_found"
        elif isinstance(exc, PermissionError):
            code = "permission_denied"
        else:
            code = "read_error"
        document["error"] = {"code": code, "message": str(exc)}
        return document

    return _decode_document(document, raw_bytes)


def read_document_bytes(file_name: str, raw_bytes: bytes) -> dict:
    """Read an upload in memory using the same format and IDs as local files.

    No upload is saved to disk. The source path is the supplied file name.
    """
    document = _empty_document(Path(file_name))
    if Path(file_name).suffix.lower() != ".txt":
        document["error"] = {
            "code": "unsupported_file_type",
            "message": "Only .txt files are supported.",
        }
        return document
    return _decode_document(document, raw_bytes)


def _decode_document(document: dict, raw_bytes: bytes) -> dict:
    try:
        # Strict decoding reports invalid UTF-8 instead of replacing evidence.
        original_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        document["error"] = {
            "code": "invalid_encoding",
            "message": "The file is not valid UTF-8. Save it as UTF-8 and retry.",
        }
        return document

    # Split only at actual line endings, preserving blank lines and whitespace.
    line_texts = re.split(r"\r\n|\r|\n", original_text) if original_text else []
    if original_text.endswith(("\r", "\n")):
        # A final line ending does not create an additional source line.
        line_texts.pop()

    document.update(
        document_id="doc_" + hashlib.sha256(raw_bytes).hexdigest(),
        status="ok" if original_text else "empty",
        text=original_text,
        line_count=len(line_texts),
        lines=[
            {"line_number": number, "text": line_text}
            for number, line_text in enumerate(line_texts, start=1)
        ],
    )
    return document
