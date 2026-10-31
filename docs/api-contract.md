# Team API contract, version 1.0

This is our team's proposed interface, not a Unissant-supplied standard. The
challenge clarification leaves schemas, synthetic data, and evaluation to each
team. Share this document with the Analysis and Audit Agent owners before their
integration. No particular model or external service is required by this API.

The backend serves the frontend and API from the same origin. Start with
`python -m backend`, then open `http://127.0.0.1:8000`. Requests and responses use
UTF-8 JSON. `api_version` identifies the API envelope; `schema_version` inside
each extracted document identifies the existing reader format.

## Working endpoints

| Method | Route | Result |
| --- | --- | --- |
| GET | `/api/health` | Agent availability and upload limits |
| GET | `/api/demo` | The three fictional documents read from disk |
| POST | `/api/documents` | Uploaded bytes processed by the Document Reader |
| POST | `/api/analysis` | Reserved integration route; currently HTTP 501 |

### Upload documents

```json
{
  "files": [
    {"file_name": "example.txt", "content_base64": "YWJj"}
  ]
}
```

`YWJj` encodes the original bytes `abc`. The browser reads `File.arrayBuffer()`
and encodes those bytes, preserving original line endings and UTF-8 byte order
marks. Do not decode and re-encode text before uploading if you need the ID to
match an original file. Base64 is a transport format, not encryption.

The response is HTTP 200 with this envelope:

```json
{
  "api_version": "1.0",
  "documents": [
    {
      "schema_version": "1.0",
      "document_id": "doc_ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
      "file_name": "example.txt",
      "source_path": "example.txt",
      "encoding": "utf-8",
      "status": "ok",
      "text": "abc",
      "line_count": 1,
      "lines": [{"line_number": 1, "text": "abc"}],
      "error": null
    }
  ]
}
```

The full reader field definitions remain in the root README. An empty file has
`status: "empty"`, a content ID, and zero lines. Invalid UTF-8 or unsupported
extensions produce per-file `status: "error"` results, so other files in the
request can still be returned. Identical byte content shares an ID, even with
different names. The API returns every submitted entry; the browser skips
identical copies in its workspace.

Limits: 1–12 files per request, 256 KiB per file, 2 MiB total decoded bytes,
10,000 source lines per file, and a 5 MiB JSON request body. A file name must be
a name rather than a server path. Uploads are processed in memory and discarded
after the response. The server provides no arbitrary local-file-reading route.
The browser keeps at most 12 documents in memory; refresh clears them.

### API errors

```json
{
  "api_version": "1.0",
  "error": {"code": "invalid_files", "message": "Provide between 1 and 12 files."}
}
```

Malformed requests return HTTP 400. Limit violations return 413; an incorrect
content type returns 415. Foreign Host/Origin or cross-site browser requests
return 403. Unknown routes return 404. Send `Content-Type: application/json`
and a valid `Content-Length`; chunked requests are not supported. Normal browser
`fetch()` and Python HTTP clients set these headers automatically. Each
connection has a 15-second timeout.

## Analysis Agent handoff

The browser can download this request for either application. Only `ok`
documents enter the handoff; empty and failed documents remain visible in the
reader workspace and full JSON export.

| Field | Type | Meaning |
| --- | --- | --- |
| `api_version` | string | `"1.0"` |
| `task` | string | `"brief"` or `"requirements"` |
| `documents` | array | Nonempty list of extracted reader documents above |

For example, using Python:

```python
from document_reader import read_document

request = {
    "api_version": "1.0",
    "task": "brief",
    "documents": [read_document("sample_documents/requirements.txt")],
}
```

Your teammate's connection point is
`backend/analysis.py::analyze_documents(request: dict) -> dict`. It currently
raises `AnalysisUnavailable`, which the API turns into HTTP 501 with error code
`analysis_not_connected`. It never returns invented analysis. The endpoint
currently validates only the task and a nonempty document list. Full input and
output validation, UI result rendering, and agent availability reporting must
be integrated alongside the real agent. Do not treat the stub as a completed
analysis workflow.

### Proposed analysis output schema

These are proposed fields for the team to agree on. This output is not yet
produced or validated by the application.

| Field | Type | Meaning |
| --- | --- | --- |
| `api_version` | string | `"1.0"` |
| `task` | string | Echo the requested application |
| `status` | string | `"completed"` for a successful real analysis |
| `claims` | array | Objects containing `claim_id`, `text`, and `citations` |
| `contradictions` | array | Objects containing `description` and at least two conflicting `citations` |
| `requirement_checks` | array | Objects containing `requirement_id`, `status` (`met`, `unmet`, or `unclear`), `explanation`, and `citations`; empty for a brief |
| `limitations` | array of strings | Missing evidence, model limits, or other relevant qualifications |
| `audit` | object | Initially `{ "status": "not_run", "flags": [] }`; only the Audit Agent can report its verification outcome |

Each citation has this exact shape:

```json
{
  "document_id": "doc_ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  "line_start": 1,
  "line_end": 1
}
```

Line ranges are inclusive, begin at 1, and must exist in the referenced
document. The Analysis Agent must preserve reader IDs and line numbers. The
Audit Agent must separately check whether the cited evidence actually supports
the claim; an existing line reference alone does not establish support. Retain
the exact source version alongside exported results.

## Local prototype boundary

The server binds to `127.0.0.1` and serves an allowlist of frontend assets.
It has no accounts, persistent storage, production hosting, or real analysis
or audit integration. No CORS configuration is needed because the UI and API
share one origin. It is intended for development on one computer; production
hosting needs a separate deployment design.
