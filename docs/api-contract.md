# Team API contract, version 1.0

This is our team's implemented demo interface, not a Unissant-supplied standard. The
challenge clarification leaves schemas, synthetic data, and evaluation to each
team. Analysis and audit default to clearly labeled deterministic demo mode.
The AI Brief Generator requires explicit backend opt-in; Groq GPT OSS 20B is
preferred when its key is configured, with optional Gemini. The Requirements
Checker remains deterministic. See [AI providers](ai-providers.md)
for provider configuration and [the demo guide](demo-guide.md) for
credentials, startup commands, permissions, and the presentation sequence.

The backend serves the frontend and API from the same origin. Start with
`python -m backend`, then open `http://127.0.0.1:8000`. Requests and responses use
UTF-8 JSON. `api_version` identifies the API envelope; `schema_version` inside
each extracted document identifies the existing reader format.

## Working endpoints

| Method | Route | Result |
| --- | --- | --- |
| GET | `/api/health` | Selected provider/model, local agent readiness, and upload limits; no live provider probe |
| GET | `/api/session` | Current user, or `null` if signed out |
| POST | `/api/login` | Authenticate with `username` and `password`; sets session cookie |
| POST | `/api/logout` | Revoke session and clear cookie |
| GET | `/api/demo` | Authorized examples: three for Analyst, four for Manager |
| GET | `/api/documents` | Authorized document records |
| GET | `/api/documents/{document_id}` | One authorized source, or HTTP 403 |
| POST | `/api/documents` | Upload, read, and register documents with server-owned permissions |
| POST | `/api/analysis` | Run shared Analysis and Audit Agents; briefs optionally use the selected AI provider |
| GET | `/api/analyses` | Accessible saved run summaries |
| GET | `/api/analysis/{analysis_id}` | Authorized result, including review status |
| GET | `/api/analysis/{analysis_id}/audit` | Authorized metadata-only audit events |
| POST | `/api/analysis/{analysis_id}/review` | Manager-only `decision` and required `comment` |

Document and analysis routes require an authenticated session. Roles come from
server-side account records, never request bodies or headers. Seeded public
documents are shared; standard uploads belong to their uploader and Managers.
Restricted documents are Manager-only. The server checks document permissions
before returning text, analyzing evidence, or retrieving stored results/events.

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
a name rather than a server path. Uploads are processed and retained in server
memory until restart. The server provides no arbitrary local-file-reading route.
The browser keeps at most 12 documents in its current view; refresh clears that
view. Canonical documents and results stay in server memory until restart.
Successful reads are registered so analyses can refer to their IDs. Add
`"access": "restricted"` beside `files` for a Manager-only upload; the default
is `"public"` (uploader and Managers). Existing permissions cannot be downgraded
by resubmitting identical bytes. Managers have no unrestricted filesystem route.

### API errors

```json
{
  "api_version": "1.0",
  "error": {"code": "invalid_files", "message": "Provide between 1 and 12 files."}
}
```

Malformed requests return HTTP 400. Missing/expired authentication returns 401;
document or role denial returns 403. A flagged result cannot be approved (409).
Limit violations return 413; an incorrect
content type returns 415. Foreign Host/Origin or cross-site browser requests
return 403. Unknown routes return 404. Send `Content-Type: application/json`
and a valid `Content-Length`; chunked requests are not supported. Normal browser
`fetch()` and Python HTTP clients set these headers automatically. Each
connection has a 15-second timeout.

## Analysis Agent handoff

The browser can download evidence or submit an analysis request for either application. Only `ok`
documents enter the handoff; empty and failed documents remain visible in the
reader workspace and full JSON export.

| Field | Type | Meaning |
| --- | --- | --- |
| `api_version` | string | `"1.0"` |
| `task` | string | `"brief"` or `"requirements"` |
| `document_ids` | array | 1–12 unique server-registered document IDs |
| `requirements` | array | Required for `requirements`: 1–30 nonempty strings, each up to 1,000 characters |

HTTP example after login and example loading:

```json
{
  "api_version": "1.0",
  "task": "requirements",
  "document_ids": ["doc_REPLACE_WITH_AN_ACTUAL_SERVER_ID"],
  "requirements": ["audit records", "quantum encryption"]
}
```

The ID above is an explanatory placeholder. Use IDs returned by the server.
For compatibility, `documents` snapshots can replace `document_ids`; the server
still resolves their IDs and checks every permission before comparing snapshots
with canonical evidence. Caller-supplied text, access fields, and roles cannot
override server records.

For example, using Python:

```python
from document_reader import read_document

request = {
    "api_version": "1.0",
    "task": "brief",
    "documents": [read_document("sample_documents/requirements.txt")],
}
```

`backend/analysis.py::analyze_documents(request: dict) -> dict` now adapts
validated Reader documents to the existing mesh Analysis and Audit Agents.
The Python example above is an internal helper call, not an authentication
bypass through HTTP. Requirements-mode helper calls also need `requirements`.
The HTTP server supplies authorized canonical documents to this helper and
stores the audited result. Reader IDs and line records are checked before use.

### Analysis output schema

These fields are returned by the integrated workflow. Deterministic citations
are single-line extracts. AI citations may span up to 20 inclusive lines,
with exact quotes joined using `\n`; original source text remains unchanged.

Groq generation uses provider JSON-object mode with explicit local validation
of the existing claims/citation structure before normalization. Schema-invalid
content is rejected with labeled deterministic fallback; it is not repaired.
Structurally valid drafts with incorrect citation IDs, ranges, or quotes are
still flagged by the unchanged auditor. Gemini generation is unchanged.

| Field | Type | Meaning |
| --- | --- | --- |
| `api_version` | string | `"1.0"` |
| `analysis_id`, `created_at` | strings | Server-generated run ID and UTC timestamp |
| `mode`, `mode_label` | strings | `"deterministic_demo"`, `"groq"`, or `"gemini"`, with an honest human-readable label |
| `provider` | optional string | `groq` or `gemini` for a structurally usable AI draft |
| `attempted_provider`, `attempted_model` | optional | Selected AI attempt, including fallback; `none`/null for invalid provider configuration |
| `model`, `brief_word_count` | optional | Model ID and narrative word count for AI results |
| `fallback_reason` | optional string | Sanitized reason code when an attempted provider path falls back |
| `provider_diagnostics` | optional object | Safe metadata for a provider HTTP failure or a local Groq validation failure; also included in `audit_event` |
| `document_ids` | array | Canonical input versions used by this run |
| `task` | string | Echo the requested application |
| `status` | string | `"completed"` for a successful real analysis |
| `claims` | array | `claim_id`, `text`, `citations`; AI drafts also supply an allowlisted narrative `section` |
| `contradictions` | array | Objects containing `description` and at least two conflicting `citations` |
| `requirement_checks` | array | `requirement_id`, `text`, `status`, `explanation`, `citations`; status remains `unclear` because lexical matches do not establish compliance |
| `limitations` | array of strings | Missing evidence, model limits, or other relevant qualifications |
| `audit` | object | `status` (`passed`/`needs_review`/`flagged`), flags with `severity`, `checked_at`, `method`, and `limitations` |
| `audit_event` | object | Event ID, run ID, actor, role, UTC timestamp, source IDs, evidence hash, audit status, and flag codes |
| `review` | object | Initially `pending`; after Manager review, `approved`/`rejected` plus actor, timestamp, comment, and `audit_status_at_review` |

Each citation has this exact shape:

```json
{
  "document_id": "doc_ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  "line_start": 1,
  "line_end": 1,
  "quote": "abc"
}
```

The UI supports copying inclusive source ranges starting at 1. Automatically
generated demo citations use one line (`line_start == line_end`) and an exact
`quote`. Audit checks exact quote/claim support and reruns the retention rules
for conflicts. It does not perform general semantic verification. Retain exact
source versions alongside downloaded results.

Manager review body: `{"decision":"approve","comment":"Reviewed source evidence."}`
or `"reject"` with a note. Approval requires a passed audit or a Groq/Gemini draft
with warning-only `needs_review` status. Hard errors remain blocked. Conflicts are not
automatically resolved by approval. Each decision is appended to the audit
trail, while automated audit status remains separate.

### Safe provider diagnostics

HTTP failures return the existing successful deterministic fallback response
(HTTP 200 from this app), with the provider's status recorded separately:

```json
{
  "fallback_reason": "generation_not_found",
  "provider_diagnostics": {
    "http_status": 404,
    "google_status": "NOT_FOUND",
    "google_error_code": 404,
    "google_reason": null,
    "model_id": "gemini-3.8-flash",
    "api_version": "v1beta",
    "operation": "generateContent",
    "error_body_state": "parsed"
  }
}
```

The adapter reads at most 8 KiB of an HTTP error body, once, then closes it.
`google_status` and `google_reason` are fixed allowlisted values; unknown or
unreadable values become `null`. `google_error_code` is a validated numeric
provider field, separate from the observed HTTP status. `error_body_state` is
`parsed`, `unparseable`, `limit_reached`, or `unreadable`. A diagnostic model ID
is omitted (`null`) if it contains the credential. Raw provider messages, bodies,
headers, URLs, and source text are never added to diagnostics or the audit log.
Inspect these fields using Download result JSON or Show audit trail. Missing
configuration and non-HTTP failures do not invent provider HTTP diagnostics.

Local Groq parsing/validation failures retain `fallback_reason: invalid_response`
and add only `{"provider":"groq","failure_stage":"structure_validation",
"failure_category":"invalid_section"}` (illustrative values). Stages and
categories come from closed server-owned allowlists, documented in
[AI providers](ai-providers.md#local-parsing-and-validation-diagnostics).
There is no fabricated HTTP status or copied model/exception text. The same
object appears in the result, saved run, and existing audit event/trail.
`truncated_response` requires an explicit provider `finish_reason: length`;
incomplete JSON alone is `invalid_json`. Raw responses, unknown field names,
invalid values, document text, exception messages, and credentials are excluded.
Existing HTTP diagnostics and all validation/audit decisions are unchanged.

Groq uses the same HTTP fallback behavior, with `provider: groq`, `http_status`,
allowlisted `provider_error_code`/`provider_error_type` (unknown values null),
`model_id: openai/gpt-oss-20b`, `api_version: openai/v1`,
`operation: chat.completions`, and `error_body_state`. The same 8 KiB limit and
redaction rules apply. Provider and attempted-model metadata are recorded in
the existing audit event; source text and provider messages are excluded.

Groq diagnostics add only safe fields: `response_content_type` (allowlisted
normalized MIME type, `other`, or null), `response_body_bytes` (at most 8,192,
null on read failure), `body_category` (`json`/`html`/`plain_text`/`empty`/
`undecodable`, or null on read failure), `edge_error_code` (recognized `1010`
only, otherwise null), and `failure_category`. For HTTP 403, that category is
`forbidden_unclassified`, `edge_block_suspected`, `provider_permission`, or
`model_permission`. A recognized 400/422 `json_validate_failed` uses
`failure_category: output_validation` and `fallback_reason: invalid_response`,
with the HTTP status/code retained; other statuses use null. These are observations about the
bounded response prefix, not independent verification of the response origin.

Unexplained Groq 403 responses now use `fallback_reason: http_forbidden`.
Recognized Groq permission errors retain `permission_denied`; a model-permission
classification requires `model_permission_blocked_org` or
`model_permission_blocked_project`. The generic `permissions_error` type alone
does not confirm a model restriction. No raw bodies, error messages, headers,
authorization values, or document text are added to diagnostics.

`generation_not_found` replaces the earlier blanket `model_unavailable` label
for HTTP 404. A 404 alone does not establish that the model name is invalid.
Audit checks, fallback citations, and Manager review permissions are unchanged.

## Local prototype boundary

The server binds to `127.0.0.1` and serves an allowlist of frontend assets.
It uses synthetic accounts and server-side sessions, with in-memory documents
and results. `.runtime/audit.jsonl` persists metadata-only events and is ignored
by Git. Sessions and runs reset at restart; the old log remains, but its runs
are not rehydrated. No CORS configuration is needed because the UI and API share
one origin. This is development on one computer, with no production hosting,
database, or tamper-proof log. AI providers are optional and backend-only; credentials
are never included in this API. Model availability is not verified by `/api/health`.
