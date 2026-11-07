# Brief Generator providers

The shared Reader -> Analysis -> Audit workflow supports Groq GPT OSS 20B,
optional Gemini, and deterministic extracts. The Requirements Checker remains
deterministic; its Phase 2 evidence-matrix plan is not implemented here.
The AI adapters use the Python standard library; PDF extraction adds `pypdf`
(install `requirements.txt`). No live provider request was made
during this implementation; all provider verification used mocks.

## Selection and configuration

Live generation remains disabled by default, even when keys already exist.
The CLI reads provider configuration at startup; restart after changing it.

| Variable | Behavior |
| --- | --- |
| `ICONTINUUM_AI_MODE` | `deterministic` by default; `auto` enables one selected AI provider for briefs |
| `ICONTINUUM_AI_PROVIDER` | `auto` by default; `groq` and `gemini` explicitly select a provider |
| `GROQ_API_KEY` | Backend-only environment credential; never saved to a file or returned |
| `GROQ_TIMEOUT_SECONDS` | Provider socket timeout, default `60`; decimal whole seconds `10`-`120` inclusive |
| `GEMINI_API_KEY` | Optional Gemini backend credential |
| `GEMINI_MODEL` | Optional override, default `gemini-3.8-flash` |
| `GEMINI_TIMEOUT_SECONDS` | Same timeout rules, default `60` |

In `auto` mode with provider selection `auto`, a nonempty `GROQ_API_KEY`
selects Groq first. Otherwise the existing Gemini adapter is selected. Missing
keys produce `missing_configuration` deterministic fallback. An explicit
selection never switches providers because its key is missing. Unknown provider
names and invalid timeout values produce `invalid_configuration` fallback.
Deterministic mode does not read either API key.

There is one generation attempt and no automatic retry, model substitution,
or Groq-to-Gemini failover. Provider errors fall back to deterministic extracts
so documents are not silently transmitted to a second service.

## Groq request and evidence

The fixed model is `openai/gpt-oss-20b`, using
`POST https://api.groq.com/openai/v1/chat/completions`. The key travels only in
the HTTPS Authorization header. Redirects are disabled.

The request explicitly sends `User-Agent: iContinuum-PoC/1.0` and
`Accept: application/json`. These identify this application rather than relying
on urllib's default client signature; they do not guarantee an edge filter will
accept the request.

The Groq adapter now requests `response_format.type: json_schema` with
`json_schema.name: icontinuum_brief`, `strict: true`, and a Groq-specific schema.
This replaces the earlier JSON Object Mode experiment. It retains the existing
citation contract, low reasoning effort, no returned reasoning, no tools,
no streaming, and at most 8,192 completion tokens. The model and generation
settings are retained; Groq-only citation guidance is described below.
Strict Structured Outputs is documented for GPT OSS 20B in Groq's
[structured-output guide](https://console.groq.com/docs/structured-outputs) and
[reasoning guide](https://console.groq.com/docs/reasoning).

`GROQ_BRIEF_SCHEMA` is a deep copy of the shared `BRIEF_SCHEMA`. It preserves
every required field, data type, section enum, and `additionalProperties: false`
on all objects. Only array `minItems`/`maxItems` are omitted from the Groq
provider-facing copy to limit schema-subset compatibility risks. The shared
Gemini schema keeps those bounds, and the unchanged local Groq validator still
enforces every count, length, type, and section rule. Provider schema adherence
does not prove that a source supports a claim; citation auditing and Manager
review still apply. Malformed responses are never repaired or trusted merely
because strict mode was requested.

The earlier token-budget experiment raised the cap from 4,096 to 8,192; this
strict-mode experiment keeps that allowance. It does not establish why earlier
HTTP `json_validate_failed` errors occurred or guarantee live success. The
850-word narrative limit, 128 KiB response-byte limit, field-specific diagnostics,
single-attempt deterministic fallback, and Gemini code/request are unchanged.
A larger token allowance may increase latency or quota consumption. No live
provider request was made for this experiment; actual account compatibility,
latency, output quality, and failure rate remain unverified.

The shared instruction asks for a coherent brief of about 400-550 words in four
sections. Sparse evidence may yield fewer words; invented padding is forbidden.
Every factual claim must cite original document IDs, inclusive line numbers,
and exact quotes. Documents and embedded instructions are untrusted data.

Groq adds explicit JSON-only instructions: the root has only a `claims` array;
each claim has exactly `section`, `text`, and `citations`; each citation has
exactly `document_id`, `line_start`, `line_end`, and `quote`. The four section
names are Overview, Scope and approach, Requirements and conflicts, and Next
steps. Four to six paragraphs are a target, not permission to invent content.

Groq citation guidance prefers one nonblank source line when sufficient, or a
short contiguous span (usually 1-3 lines) when necessary. This is a preference,
not a new hard range limit. Noncontiguous evidence should use separate citations.
Quotes must preserve all source text, indentation, trailing spaces, and blank
lines in the inclusive range, joined by escaped newlines. A blank first/last
line contributes a leading/trailing newline; no extra terminal newline is added.
For example, `meeting_notes.txt` line 4 is blank: a quote for lines 4-7 must
include its initial newline. The three sentences alone match lines 5-7 instead.
This guidance applies to future generation only; existing quotations and audit
failures are never automatically repaired or removed. Prompt adherence and
semantic support still require a separately approved live test and human review.

Before normalization, a Groq-specific local validator rejects missing/extra
fields, wrong types, invalid sections, and count/length violations. Bounds are
1-24 claims, 1-8 citations per claim, 4,000 characters per nonblank claim text,
128 per document ID, 10,000 per quote, and 850 narrative words total. Original
line numbers must be JSON integers (booleans are rejected). Duplicate JSON
keys, non-finite numbers, invalid UTF-8 strings, code fences, incomplete JSON,
and trailing prose are rejected, not repaired. A non-`stop` finish reason,
including `length`, triggers fallback even if the content parses as JSON.

Malformed structure, including absent or empty citation arrays, results in a
labeled `invalid_response` deterministic fallback. Structurally valid drafts
with fabricated source IDs, incorrect ranges, or wrong quotes still reach the
unchanged auditor and remain visibly flagged. A valid structure is not an
accuracy guarantee. The server never rescues a provider's `failed_generation`
error content as a successful AI draft.

Authorization and canonical source resolution happen before transmission.
Session and document access are checked again before returning/saving results.
Only selected, authorized source IDs/lines and known conflicts are sent; account
credentials, filenames, unrelated documents, and session tokens are not sent.
The adapters refuse a source payload that contains their own credential.
If that credential would also appear in fallback extracts, quoted output is
withheld and the audit is flagged. This does not scan unrelated uploads or
turn the Reader into a general secret-detection service; keep fixtures synthetic.

## Results, audit, and human review

`GET /api/health` reports `brief_provider`, `brief_model`, and mode such as
`groq_with_fallback`. This shows selection, not a successful connectivity test.
Startup, login, loading examples, and health checks never call either provider.

| Result | Meaning |
| --- | --- |
| `mode: groq`, `provider: groq`, `model: openai/gpt-oss-20b` | Groq returned a structurally usable draft; human review remains required |
| `mode: gemini`, `provider: gemini` | Optional Gemini returned a structurally usable draft |
| `mode: deterministic_demo`, with `fallback_reason` | A selected AI path failed; output is deterministic source extracts |
| `mode: deterministic_demo`, without a fallback reason | AI generation was disabled or the task was Requirements Checker |

Attempted AI paths also include `attempted_provider` and `attempted_model`.
Provider/model metadata is recorded in the existing audit event. Download result
JSON or inspect the existing result heading/banner to distinguish the modes.

The same auditor verifies original references, exact quotes, numeric support,
and obvious unsupported compliance/resolution claims for both providers. All AI
claims receive semantic-review warnings. Valid references do not establish
that a paraphrase is true. Invalid citations and detected unsupported facts stay
flagged; they are not hidden by switching to extract mode. The independent
30-day/90-day retention discrepancy remains cited even if an AI omits it.

Existing Manager approve/reject buttons work for both providers. Warning-only
`needs_review` drafts may be reviewed with a note; hard `flagged` failures cannot
be approved. Approval never changes the automated audit status or resolves a
source conflict automatically.

## Bounds and safe diagnostics

Limits remain 80,000 serialized input characters, 128 KiB success response,
24 claims, and 20 source lines per citation range. HTTP error responses are
read once up to 8 KiB, then closed. Groq diagnostics contain only fixed fields:
provider, HTTP status, allowlisted error code/type, model ID, API version,
operation, and parsing state. Raw messages, generated-error content, headers,
URLs, reasoning, source text, and credentials are not returned or logged.
Missing/unrecognized error fields are null. Existing Gemini diagnostics remain.

Groq HTTP diagnostics additionally include:

| Field | Safe values/meaning |
| --- | --- |
| `response_content_type` | Fixed allowlist of common JSON/HTML/text/binary MIME types; parameters removed, unknown types `other`, unavailable header null |
| `response_body_bytes` | Bytes actually read, at most 8,192; null on read failure, not the full response size |
| `body_category` | `json`, `html`, `plain_text`, `empty`, or `undecodable`; null on read failure |
| `edge_error_code` | Currently only the recognized string `1010`, otherwise null |
| `failure_category` | For 403: `forbidden_unclassified`, `edge_block_suspected`, `provider_permission`, or `model_permission`; for a recognized 400/422 `json_validate_failed`: `output_validation`; otherwise null |

Categories describe only the bounded response prefix. `undecodable` means the
prefix could not be decoded as UTF-8. Valid JSON with an unexpected envelope is
still categorized as `json`, while the existing `error_body_state` can remain
`unparseable` because a Groq `error` object was not present.

An unexplained Groq 403 now has `fallback_reason: http_forbidden`, rather than
asserting a permission problem. Recognized permission errors retain
`permission_denied`. The documented `permissions_error` type and
`model_permission_blocked_org` / `model_permission_blocked_project` codes are
allowlisted. Model-specific classification requires one of those model codes;
a general permission type alone does not establish a model restriction.

A standalone plain-text `error code: 1010`, or a matching Cloudflare-marked HTML
error, is recorded only as a suspected edge block. No response-origin claim is
made. Unknown markers are discarded. Raw response bodies, messages, headers,
and surrounding text remain excluded from results and logs.

Groq HTTP 400/422 with `provider_error_code: json_validate_failed` now maps to
`fallback_reason: invalid_response` and `failure_category: output_validation`.
The observed HTTP status and provider code remain in diagnostics. Other 400
errors retain `invalid_request`. Error messages and rejected model text are
never returned or logged. This compatibility change does not prove the cause
of the earlier strict-schema failure or guarantee live generation success.

## Local parsing and validation diagnostics

Local Groq failures retain `fallback_reason: invalid_response` and now include
three base diagnostic fields. For example (illustrative, not a finding
about any previous run):

```json
{
  "provider": "groq",
  "failure_stage": "structure_validation",
  "failure_category": "invalid_section"
}
```

The existing result download, saved run, and audit event/trail carry the same
`provider_diagnostics` object. Local diagnostics do not invent an HTTP status.
Previously saved runs without these fields cannot reveal the precise cause
retroactively. Restarting the backend loads the update; a new separately
approved live run would be needed to diagnose a real provider response.

Stages are a closed allowlist:

| Stage | Where processing failed |
| --- | --- |
| `response_read` | Reading the bounded provider response |
| `response_decode` | Decoding response bytes as UTF-8 |
| `response_json` | Parsing the outer response JSON |
| `response_envelope` | Accessing expected choice/message containers |
| `completion` | Checking completion status and unexpected tool calls |
| `content_json` | Parsing the generated message's JSON object |
| `structure_validation` | Checking claims/citations against the local contract |
| `normalization` | Converting validated claims into the shared result format |
| `local_processing` | Safe fallback stage when a more specific stage is unavailable |

Categories are also a closed allowlist:

| Category | Meaning |
| --- | --- |
| `invalid_json` | JSON syntax, non-finite numbers, excessive nesting, fences, or trailing prose rejected |
| `duplicate_field` | Duplicate JSON key detected; key name is not recorded |
| `missing_field`, `extra_field` | Required/allowed fields do not match; names are not recorded |
| `invalid_type` | A value or container has the wrong type |
| `invalid_section` | Section is not one of the four allowed strings |
| `count_limit` | Claim/citation count is outside bounds, or expected response choices are empty |
| `length_limit` | A character or narrative-word limit was exceeded |
| `blank_text` | Claim text is empty or whitespace only |
| `invalid_encoding` | UTF-8 decoding or string encoding failed |
| `response_size_limit` | Response exceeded the existing 128 KiB bound |
| `truncated_response` | Provider explicitly returned `finish_reason: length` |
| `unexpected_finish_reason` | Completion did not stop normally; raw status is not recorded |
| `unexpected_tool_call` | An unexpected tool-call field was present |
| `normalization_failed` | Shared normalization rejected an otherwise validated payload |
| `validation_failed` | Safe generic category for an unclassified local validation failure |

Incomplete JSON alone is `invalid_json`, not proof of token truncation. When
several structural defects exist, the first checked violation is recorded;
missing fields take precedence over extra fields at the same object. Only
allowlisted stage/category strings are emitted. No unknown names, invalid
values, exception messages, response fragments, generated/document text, or
credentials are included. HTTP failures retain their existing richer safe
diagnostics and are not overwritten by these local codes.

For `structure_validation / invalid_type`, three additional fields identify
the first type mismatch without recording its value. For example (illustrative):

```json
{
  "provider": "groq",
  "failure_stage": "structure_validation",
  "failure_category": "invalid_type",
  "failure_field": "citation.line_start",
  "expected_type": "integer",
  "actual_type": "string"
}
```

`failure_field` is a fixed server-owned schema location, never an unknown
model-provided field name. Its expected type comes from this closed mapping:

| Schema location | Expected type |
| --- | --- |
| `root`, `claim`, `citation` | `object` |
| `claims`, `claim.citations` | `array` |
| `claim.section`, `claim.text`, `citation.document_id`, `citation.quote` | `string` |
| `citation.line_start`, `citation.line_end` | `integer` |

`actual_type` is one of `object`, `array`, `string`, `integer`, `number`,
`boolean`, `null`, or `unknown`. `number` denotes a JSON value decoded as a
Python float, including `1.0`; it remains invalid for citation line numbers.
Booleans are tagged separately from integers. `unknown` is a safe tag for an
internal non-JSON Python object; no Python class name or representation is used.
Unknown schema locations/type tags are omitted rather than copied into output.
Other failure stages/categories keep their existing diagnostics.

The three additional fields propagate through downloaded result JSON, saved
runs, audit events/trails, and the local audit log. They do not include array
indices, model values, nested keys, text, or credentials. Validation acceptance,
failure precedence, and citation checks are unchanged; no types are coerced.
Existing saved runs are not retroactively enriched. Restart the backend before
an explicitly approved controlled live test; this diagnostic update alone does
not guarantee that Groq will generate a usable brief.

The diagnostic additions themselves do not change provider/model choice,
prompt, validation rules, citation auditing, RBAC, Manager review, deterministic
fallback, or Gemini code. The strict-mode experiment described above changes
only Groq's provider-facing response format/schema.

The timeout is per socket operation, not a strict total duration. Provider quota,
access, latency, complete schema compatibility, and real output quality remain
unverified by mocks. Structured JSON and prompt instructions do not guarantee
semantic correctness or prompt-injection resistance. The demo uses synthetic
data, in-memory documents/results, and metadata-only local JSONL audit records.

## Start with Groq

Stop an older backend with Ctrl+C. In the PowerShell session where
`GROQ_API_KEY` is already set, leave its value unprinted and run:

```powershell
Set-Location C:\Projects\iContinuum-Agentic-AI-mesh
$env:ICONTINUUM_AI_MODE = 'auto'
$env:ICONTINUUM_AI_PROVIDER = 'auto'
& .\.runtime\python\python.exe -B -m backend --port 8000
```

Open `http://127.0.0.1:8000`, sign in, load synthetic examples, and choose Brief
Generator. Clicking Run analysis in this mode sends selected authorized
evidence to the selected provider and may consume quota. This was not executed
during implementation. To force Gemini instead, set
`$env:ICONTINUUM_AI_PROVIDER = 'gemini'` before restarting. To return to offline
extracts, set `$env:ICONTINUUM_AI_MODE = 'deterministic'` and restart.

## One controlled live retry after approval

No live retry was performed during the JSON-output compatibility update. After live testing
is approved, use the same PowerShell session where `GROQ_API_KEY` is already
set; leave its value untouched and unprinted. Start a fresh backend:

```powershell
Set-Location C:\Projects\iContinuum-Agentic-AI-mesh
$env:ICONTINUUM_AI_MODE = 'auto'
$env:ICONTINUUM_AI_PROVIDER = 'groq'
& .\.runtime\python\python.exe -B -m backend --port 8003
```

Open `http://127.0.0.1:8003`, sign in as `analyst` / `AnalystDemo!2026`, load the
three public fictional examples, choose Brief Generator, and click Run analysis
**once**. Startup, login, health checks, and example loading do not call Groq.
Port 8003 must be free; stop an older backend in its own terminal if necessary.

Download result JSON. `mode: groq` identifies a provider-generated draft needing
human review. A fallback remains `deterministic_demo`; inspect `fallback_reason`
and `provider_diagnostics`. Share only those safe fields for troubleshooting.
An unexplained 403 should report `http_forbidden`; an edge marker is a clue,
not proof. If Groq reports `json_validate_failed` again, expect
`fallback_reason: invalid_response` and `failure_category: output_validation`.
Do not switch parameters, providers, or repeat requests automatically.

Stop with Ctrl+C, then set `$env:ICONTINUUM_AI_MODE = 'deterministic'`. A future
backend restart is needed to apply the offline mode.

## Offline verification

Citation-guidance/label-spacing verification: all **161 Python tests passed**,
including **60 Groq tests**. Four new regressions cover C004's omitted leading
blank line, exact 4-7 and 5-7 spans, single/separate citations, retained support
for ranges longer than three lines, exact whitespace, and Manager approval
blocking without repairing stored output. Both JavaScript syntax checks and
the Chrome workflows for mocked Groq, mocked Gemini, simulated provider outage,
and deterministic mode passed. Citation checks cover text separation, wrapping,
non-overlap, correct source navigation, and mobile keyboard activation. No live
provider requests were made; prompt adherence still needs a controlled live
test, and semantic support still needs human review.

Strict Structured Outputs verification: all **157 Python tests passed**,
including **56 Groq tests**. Three new regression tests verify the independent
provider schema, retained required/type/enum/closed-object rules, omitted
provider-only array bounds, unchanged local validation, and unchanged Gemini
schema/request. Existing mocked one-page AI briefs, invalid outputs, provider
errors, safe diagnostics, citation auditing, RBAC, Manager review, and fallback
tests also passed. No live provider requests were made; restart the backend
before a separately approved controlled live test.

The 8,192-token budget experiment passed all **154 Python tests**, including
all **53 Groq tests**. Existing citation, audit, RBAC, field-diagnostic, and
fallback tests passed; live provider behavior remains untested for this change.

Field-specific type diagnostics verification: **154 Python tests passed**,
including all **53 Groq tests**. Four new regression tests cover type mismatches
at all 11 schema locations, closed diagnostic allowlists, nested-value/key
redaction, unchanged failure order, and rejection without normalization or
coercion. The HTTP persistence test also verifies the additional fields in the
result JSON, saved run, audit event/trail, and audit log. No live provider
requests were made; generation settings and validation rules are unchanged.

Groq local-validation diagnostics verification: **149 Python tests passed**
and both JavaScript syntax checks passed. Nine new tests cover fixed failure
categories, safe redaction, HTTP diagnostic preservation, and propagation
through result JSON, saved runs, audit events, and the audit log. An earlier
suite run encountered a Windows localhost connection error in an existing
access-control test; the complete rerun passed without changes. No live
provider requests were made. Request settings and Gemini code are unchanged.

Groq JSON-object compatibility verification: **140 Python tests passed** and
both JavaScript syntax checks passed. Ten new tests cover strict local
structure/bounds, malformed and duplicate-key JSON, valid one-page output,
bad citations, truncation, output-validation errors, and safe fallback. No
live provider requests were made. Gemini code and citation audit are unchanged.

Groq 403 diagnostic update verification: **130 Python tests passed** and both
JavaScript syntax checks passed. This includes eight new diagnostic/transport
tests; the urllib header test uses a fake HTTPS handler and prohibits socket
connections. No live Groq or Gemini request was made for this update.

Verification on November 6, 2026: **122 Python tests passed**, including 22
Groq/provider-selection tests. Both JavaScript syntax checks and the mocked
Chrome workflows for Groq and Gemini passed. Browser checks covered uploads,
citations, conflicts, downloads, audit trail, Manager approve/reject, restricted
API denial, and narrow layouts. No live provider requests were made. These are
functional integration checks, not measured model-quality scores.

```powershell
& .\.runtime\python\python.exe -B -m unittest discover -s tests -v
node --check frontend/app.js
node --check tests/browser_smoke.mjs
```

For an offline Groq UI fixture, run this server in a separate terminal:

```powershell
& .\.runtime\python\python.exe -B tests/mock_gemini_server.py --provider groq --port 8002
```

Then run `node tests/browser_smoke.mjs http://127.0.0.1:8002 --mock-groq` with
Chrome installed. The test server uses fake credentials and patched transport,
never the environment key or a provider API. Its apparent Groq draft is a
synthetic fixture, not evidence of a real generation. Stop it with Ctrl+C.
