"""Read UTF-8 text files without summarizing or changing their contents."""

import hashlib
from pathlib import Path
import re
from typing import Union


def read_document(file_path: Union[str, Path]) -> dict:
    """Return a JSON-ready document, including safe results for read failures.

    IDs identify exact file contents, independent of the file name or location.
    Identical copies share an ID; any byte change produces a different ID.
    Line numbers start at 1. CRLF, LF, and CR each end a source line.
    """
    path = Path(file_path)
    document = {
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
