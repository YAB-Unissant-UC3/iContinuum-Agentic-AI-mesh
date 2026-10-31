"""Small, localhost-only development server. No third-party dependencies."""

import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from document_reader import read_document, read_document_bytes
from .analysis import AnalysisUnavailable, analyze_documents


ROOT = Path(__file__).resolve().parents[1]
MAX_FILES = 12
MAX_FILE_BYTES = 256 * 1024
MAX_REQUEST_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_LINES_PER_FILE = 10000
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


class RequestError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status


def _documents_response(documents):
    return {"api_version": "1.0", "documents": documents}


def _read_uploads(payload):
    files = payload.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise RequestError("invalid_files", "Provide between 1 and 12 files.")
    decoded = []
    total = 0
    for item in files:
        if not isinstance(item, dict):
            raise RequestError("invalid_file", "Each file must be an object.")
        name = item.get("file_name")
        if (not isinstance(name, str) or not name.strip() or len(name) > 255
                or any(character in name for character in '/\\:\x00')
                or any(ord(character) < 32 for character in name)):
            raise RequestError("invalid_filename", "Supply a file name without a directory path.")
        encoded = item.get("content_base64")
        if not isinstance(encoded, str):
            raise RequestError("invalid_content", "content_base64 must be a base64 string.")
        if len(encoded) > 4 * ((MAX_FILE_BYTES + 2) // 3):
            raise RequestError("file_too_large", "Each file must be 256 KiB or smaller.", 413)
        try:
            raw_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise RequestError("invalid_base64", "File content is not valid base64.")
        total += len(raw_bytes)
        if len(raw_bytes) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise RequestError("file_too_large", "Use files up to 256 KiB, with 2 MiB total per request.", 413)
        endings = len(re.findall(rb"\r\n|\r|\n", raw_bytes))
        lines = endings + int(bool(raw_bytes) and not raw_bytes.endswith((b"\r", b"\n")))
        if lines > MAX_LINES_PER_FILE:
            raise RequestError("too_many_lines", "Each file can contain at most 10,000 lines.", 413)
        decoded.append((name, raw_bytes))
    return _documents_response([read_document_bytes(name, data) for name, data in decoded])


class WorkspaceHandler(BaseHTTPRequestHandler):
    # HTTP/1.0 closes connections after each response, including rejected bodies.
    server_version = "iContinuumLocal/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format_string, *args):
        # Do not log uploaded document contents or user-supplied URL paths.
        pass

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8"))

    def _error(self, error):
        self._json(error.status, {"api_version": "1.0", "error": {
            "code": error.code, "message": error.message,
        }})

    def _check_local_request(self):
        port = self.server.server_address[1]
        hosts = {"127.0.0.1:{}".format(port), "localhost:{}".format(port)}
        if port == 80:
            hosts.update({"127.0.0.1", "localhost"})
        host_headers = self.headers.get_all("Host", [])
        if len(host_headers) != 1 or host_headers[0] not in hosts:
            raise RequestError("invalid_host", "Use the local workspace address.", 403)
        origin = self.headers.get("Origin")
        if origin is not None and origin != "http://" + host_headers[0]:
            raise RequestError("invalid_origin", "Open the workspace from this server.", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise RequestError("invalid_origin", "Cross-site requests are not supported.", 403)

    def do_GET(self):
        try:
            self._check_local_request()
            path = urlsplit(self.path).path
            if path == "/api/health":
                self._json(200, {
                    "api_version": "1.0", "status": "ok",
                    "agents": {"reader": "ready", "analysis": "not_connected", "audit": "not_connected"},
                    "limits": {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES,
                               "max_total_bytes": MAX_TOTAL_BYTES, "max_lines_per_file": MAX_LINES_PER_FILE},
                })
            elif path == "/api/demo":
                documents = [read_document(ROOT / "sample_documents" / name) for name in (
                    "project_brief.txt", "requirements.txt", "meeting_notes.txt",
                )]
                for document in documents:
                    document["source_path"] = "sample_documents/" + document["file_name"]
                self._json(200, _documents_response(documents))
            elif path in STATIC_FILES:
                name, content_type = STATIC_FILES[path]
                self._send(200, (ROOT / "frontend" / name).read_bytes(), content_type)
            elif path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            else:
                raise RequestError("not_found", "This route does not exist.", 404)
        except RequestError as exc:
            self._error(exc)

    def _read_json(self):
        if self.headers.get("Transfer-Encoding") is not None:
            raise RequestError("unsupported_transfer", "Use a Content-Length header.")
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise RequestError("unsupported_media_type", "Send application/json.", 415)
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
            raise RequestError("invalid_length", "Supply a valid Content-Length.")
        if len(lengths[0]) > 10:
            raise RequestError("request_too_large", "The JSON request exceeds 5 MiB.", 413)
        length = int(lengths[0])
        if length > MAX_REQUEST_BYTES:
            raise RequestError("request_too_large", "The JSON request exceeds 5 MiB.", 413)
        try:
            raw_body = self.rfile.read(length)
            if len(raw_body) != length:
                raise RequestError("invalid_body", "The request body is incomplete.")
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise RequestError("invalid_json", "Send a valid UTF-8 JSON object.")
        except TimeoutError:
            raise RequestError("request_timeout", "The upload took too long.", 408)
        if not isinstance(payload, dict):
            raise RequestError("invalid_json", "The JSON body must be an object.")
        return payload

    def do_POST(self):
        try:
            self._check_local_request()
            path = urlsplit(self.path).path
            if path not in {"/api/documents", "/api/analysis"}:
                raise RequestError("not_found", "This route does not exist.", 404)
            payload = self._read_json()
            if path == "/api/documents":
                self._json(200, _read_uploads(payload))
            else:
                if payload.get("task") not in ("brief", "requirements"):
                    raise RequestError("invalid_task", "task must be brief or requirements.")
                if not isinstance(payload.get("documents"), list) or not payload["documents"]:
                    raise RequestError("invalid_documents", "Provide extracted documents.")
                try:
                    result = analyze_documents(payload)
                except AnalysisUnavailable as exc:
                    raise RequestError("analysis_not_connected", str(exc), 501)
                # The real agent and its output validation will be integrated together.
                self._json(200, result)
        except RequestError as exc:
            self._error(exc)


def create_server(port=8000):
    """Bind only to this computer; port 0 is useful for automated tests."""
    return ThreadingHTTPServer(("127.0.0.1", port), WorkspaceHandler)
