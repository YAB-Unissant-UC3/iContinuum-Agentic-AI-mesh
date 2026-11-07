# Phase 1: Gemini Brief Generator

Groq GPT OSS 20B is now the preferred configured provider. This document covers
the optional Gemini adapter; see [AI providers](ai-providers.md) for selection.
Use `ICONTINUUM_AI_PROVIDER=gemini` to select Gemini explicitly when both keys exist.

Implemented scope: an optional Gemini-generated project brief through the
existing shared API. Reader, deterministic Analysis/Audit behavior, Requirements
Checker, document RBAC, audit logs, and existing Manager buttons are preserved.
There are no new Python dependencies and no new approval buttons.

**Live generation is disabled by default. No real Gemini API request was made
during implementation or the mocked test run.** Your real key was not inspected.

## Model and configuration

The default model ID is `gemini-3.8-flash`; `GEMINI_MODEL` still overrides it.
The adapter keeps the existing `v1beta/models/{model}:generateContent` endpoint
and citation schema. Google's [3.8 migration guide](https://ai.google.dev/gemini-api/docs/latest-model)
recommends removing sampling overrides. For the exact `gemini-3.8-flash` ID,
the adapter omits temperature/top-p/top-k and sends
`generationConfig.thinkingConfig.thinkingLevel: "low"`, using Google's
[generateContent reasoning format](https://ai.google.dev/gemini-api/docs/generate-content/thinking).
Explicit overrides to other models keep their previous request settings
(temperature 0.2, without a thinking-level override); their compatibility must
be checked separately. No Interactions API migration or substitute-model retry
is included. Project access, quota, generation quality, and latency remain
unverified until a separately approved live test.

| Environment variable | Behavior |
| --- | --- |
| `GEMINI_API_KEY` | Backend-only credential; read only when CLI mode is `auto` |
| `GEMINI_MODEL` | Optional model ID; defaults to `gemini-3.8-flash` |
| `GEMINI_TIMEOUT_SECONDS` | Optional provider socket timeout; defaults to `60`; decimal whole seconds from `10` through `120` inclusive |
| `ICONTINUUM_AI_MODE` | `deterministic` by default; explicit `auto` enables Gemini for briefs with fallback |

The key is sent in the HTTPS `x-goog-api-key` header, never a URL. Request
headers and raw provider exceptions/bodies are not logged or returned. Redirects
are disabled. No `.env` file or frontend credential is needed. The adapter uses
Python's standard `urllib.request` and `json` modules, not an installed SDK.

Environment variables in PowerShell are inherited by a backend started from
that same session. Restart the backend to apply a configuration change. Do not
print or paste your key to check it.

An existing `GEMINI_MODEL` setting takes precedence over the new default.
Invalid timeout values (including fractions, empty values, and out-of-range
numbers) cause labeled `invalid_configuration` fallback before transmission;
the raw configuration value is never returned or logged. The timeout is a
socket timeout, not a strict total wall-clock deadline. A longer timeout and
low reasoning do not guarantee provider availability or fast responses.

## Request flow and evidence boundaries

1. The server authenticates the session and resolves all selected IDs against
   its canonical store. Any access denial or altered snapshot stops processing
   before the provider is invoked.
2. The Reader's document IDs and original numbered lines are validated. Only
   selected, authorized evidence is serialized for Gemini. Filenames, account
   credentials, session tokens, and unrelated documents are not sent.
3. A separate system instruction requests a coherent roughly one-page brief
   (400–550 words), ordered into Overview, Scope and approach, Requirements and
   conflicts, and Next steps. Sparse evidence may produce a shorter brief; it
   must not be padded with invented facts.
4. Every factual paragraph/claim requires original document IDs, inclusive
   line ranges, and exact supporting quotes. JSON structured output is requested,
   then bounded and validated locally. Model-provided audit/review fields cannot
   override server-owned state.
5. Audit checks source membership, range validity, exact quotes, numeric values,
   and obvious unsupported compliance/resolution assertions. Session and source
   access are rechecked before saving or returning the result.

The network wait occurs outside the shared workspace lock. Once an authorized
request has been sent to Google, it cannot be recalled by subsequent logout;
however, an expired/revoked session cannot retrieve the completed result.

Document content is explicitly untrusted data, never system instructions.
Generation has no tools, browsing, filesystem access, or function execution.
Prompt-injection resistance is not a guarantee: strict references and human
review remain necessary.

## Conflicts, audit, and Manager review

The existing retention detector runs independently of Gemini and attaches its
conflicts to **both** brief and Requirements Checker output. The 30-day/90-day
discrepancy remains cited even if the model omits it or tries to return no
conflicts. Human approval does not establish reconciliation.

| Automated status | Meaning | Existing Manager action |
| --- | --- | --- |
| `passed` | Deterministic extract/rule checks passed | Approve or reject with a note |
| `needs_review` | Gemini draft has review warnings, but no detected hard citation/support error | Approve or reject with a note after inspecting evidence |
| `flagged` | Invalid/missing reference, wrong quote, unsupported number, or another detected hard error | Approval blocked; rejection available |

All Gemini statements receive a semantic-review warning. A valid citation does
not prove that a paraphrase is supported. Questionable non-numeric assertions
may be indistinguishable from good paraphrases to these checks. Managers must
inspect them; there is no automatic accuracy certification or second-model
verification. Unknown-source draft statements are withheld rather than resolved
against other documents. Automated statuses/flags remain unchanged after review,
with `audit_status_at_review` recorded alongside the human decision.

## Bounds and fallback

One request, no retries, a configurable socket timeout (60 seconds by default,
10-120 seconds inclusive), up to 80,000 serialized
input characters, 8,192 output tokens, 128 KiB response bytes, and 24 claims.
Citations can span at most 20 source lines; multi-line quotes join Reader line
text with `\n`, including blank lines. Long inputs fall back rather than silently
discarding evidence. Approximate output length outside 300–650 words is flagged
for review; outputs over 850 words are rejected as unusable responses.

Missing configuration, 429 quota responses, API failures, timeouts, blocked or
malformed/truncated responses, and credential echoes use a labeled deterministic
fallback with a fixed, non-sensitive `fallback_reason`. Structurally valid but
incorrect citations stay visibly flagged; they do not receive a clean Gemini
audit by switching modes. Logs contain metadata, model, and safe reason codes,
not prompts, responses, credentials, or source text.

HTTP error bodies have a separate **8 KiB, single-read** limit. Only the safe
`provider_diagnostics` fields documented in [the API contract](api-contract.md#safe-provider-diagnostics)
are returned and recorded in the existing audit event. Unrecognized Google
status/reason strings are discarded. Messages, raw bodies, headers, and URLs
are never copied into responses or logs. Failure to parse diagnostics still
preserves the original HTTP classification and deterministic fallback.

| Provider HTTP status | Fallback reason |
| --- | --- |
| 400 | `invalid_request`; `failed_precondition` for Google's `FAILED_PRECONDITION`; `authentication_failed` for known invalid/expired/missing-key reasons |
| 401 | `authentication_failed` |
| 402 | `billing_required` |
| 403 | `permission_denied` |
| 404 | `generation_not_found` (does not establish an invalid model ID) |
| 408, 504 | `provider_timeout` |
| 413 | `request_too_large` |
| 429 | `quota_exceeded` |
| Other HTTP errors, including 500/503 | `provider_unavailable` |

HTTP status remains the primary classification; the separate Google fields
preserve structured details, including any disagreement with HTTP status.
There are no automatic retries, endpoint/schema changes, or substitute models.

## Offline tests

From the repository root:

```powershell
& .\.runtime\python\python.exe -B -m unittest discover -s tests -v
node --check frontend/app.js
```

With installed Python, substitute `python` for the prepared runtime command.
Tests inject fake providers/keys and mock the external transport. Existing test
servers are deterministic even if real environment variables are set. Tests
cover coherent-output structure, paraphrases, citations/ranges/quotes, unsupported
claims, conflicts, injected document instructions, role/permission denial before
provider invocation, post-generation session revocation, API failures, review
transitions, and response/log key redaction. Passing these tests does not measure
live model quality, project eligibility, or Gemini latency.

For an optional **offline, mocked** browser test, start this test server in
one terminal (it never reads an environment key or contacts Google):

```powershell
& .\.runtime\python\python.exe -B tests/mock_gemini_server.py --port 8002
```

With installed Chrome and Node 22+, run in another terminal:

```powershell
node tests/browser_smoke.mjs http://127.0.0.1:8002 --mock-gemini
```

The reported model is `gemini-mock-fixture`; this is a UI fixture, not a live
Gemini result or an evaluation of model quality. Stop the test server with Ctrl+C.

## Controlled live test: only after separate explicit approval

Do not perform this step until live testing is approved. It will send the
selected synthetic evidence to Google and may consume API quota.

1. Use the PowerShell session where `GEMINI_API_KEY` is already set. Leave its
   value untouched and unprinted. The commands below explicitly select 3.8 to
   avoid retaining an older `GEMINI_MODEL` override.
2. Start an opt-in backend on a separate local port:

   ```powershell
   Set-Location C:\Projects\iContinuum-Agentic-AI-mesh
   $env:GEMINI_MODEL = 'gemini-3.8-flash'
   $env:GEMINI_TIMEOUT_SECONDS = '60'
   $env:ICONTINUUM_AI_PROVIDER = 'gemini'
   $env:ICONTINUUM_AI_MODE = 'auto'
   & .\.runtime\python\python.exe -B -m backend --port 8003
   ```

   Stop any older server in its own terminal with Ctrl+C before retrying. Port
   8003 must be free; this fresh instance loads the diagnostic changes and the
   environment from this PowerShell session. Startup makes no Gemini request.
3. Open `http://127.0.0.1:8003`. Sign in as Analyst (`analyst` /
   `AnalystDemo!2026`), load the three public
   fictional examples, select Brief Generator, and click Run analysis **once**.
   Startup and example loading do not call Gemini.
4. Check `mode`, `model`, factual citations, the one-page narrative, the visible
   30-day/90-day conflict, and `audit.status`. Gemini drafts should require review.
   A fallback is not a successful live generation. Click **Download result JSON**
   and inspect `fallback_reason` and `provider_diagnostics` (or **Show audit trail**).
   A 404 now reports `generation_not_found`, with the observed HTTP status and
   any allowlisted Google status/reason. This alone does not diagnose model
   validity, schema compatibility, or project access. Share only these safe
   fields for troubleshooting, not the complete evidence export. Do not switch
   models or retry automatically.
5. Sign in as Manager, reopen the run, inspect cited evidence, and approve or
   reject with a note. Confirm the automated audit status is unchanged.
6. Stop the test server with Ctrl+C, then disable live generation:

   ```powershell
   $env:ICONTINUUM_AI_MODE = 'deterministic'
   ```

The existing demo guide supplies credentials and the rest of the shared workflow.
Phase 2 remains a [separate unimplemented plan](phase2-plan.md).
