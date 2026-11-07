# Full-workflow demo guide

This synthetic demonstration defaults to **deterministic demo mode (no LLM)**:
source extracts, lexical evidence retrieval, explicit retention rules, and an
exact-source audit. Do not describe fallback extracts as model-generated analysis.
Groq GPT OSS 20B and optional Gemini briefs are implemented but disabled until explicitly
configured. See [AI providers](ai-providers.md); live testing requires separate
approval. Requirements Checker behavior is unchanged.

## Run the application

From the repository root, with Python 3.9 or newer installed:

```powershell
python --version
python -m backend
```

Open **http://127.0.0.1:8000**. Keep the terminal running; Ctrl+C stops it.
No `pip install`, npm installation, database, API key, or model is required.
If your Python command is `py`, substitute `py` for `python`.

On the development computer, an ignored portable runtime is also prepared at
`.runtime/python/python.exe`. It is not included in Git clones. If normal
Python is unavailable, use these exact PowerShell commands instead:

```powershell
& .\.runtime\python\python.exe -B -m backend
```

In another terminal, run the tests with:

```powershell
& .\.runtime\python\python.exe -B -m unittest discover -s tests -v
```

If the port is occupied, stop your earlier server or use another port:

```powershell
python -m backend --port 8001
```

Then open **http://127.0.0.1:8001**. The server refuses to share a port with
another server. An old running process must be restarted to pick up Python changes.

## Demo accounts

| Username | Password | Permissions |
| --- | --- | --- |
| `analyst` | `AnalystDemo!2026` | Shared public examples, own standard uploads, analysis, own results and audit events |
| `manager` | `ManagerDemo!2026` | All demo documents and runs, restricted uploads, approve/reject |

These are intentionally published synthetic-demo credentials, not production
accounts. Sessions last four hours or until logout/server restart. Signing out
clears the page's document text and results. A Manager can reopen an Analyst's
saved run using the run selector and **Open result**.

## Run the tests

```powershell
python -m unittest discover -s tests -v
```

This needs no separately running application. Each HTTP test uses an isolated
local server, and audit logs go to temporary directories. The suite covers the
Reader, mesh agents, adapter, audit, authentication, canonical evidence, direct
API access denial, approvals/rejections, and document-manifest swapping.

Optional browser checks with Node 22+ and Chrome installed at its standard
Windows location, with the application running:

```powershell
node --check frontend/app.js
node tests/browser_smoke.mjs
```

For another port: `node tests/browser_smoke.mjs http://127.0.0.1:8001`.
The script uses a temporary headless browser profile and saves screenshots and
downloads in the printed temporary directory. It creates synthetic demo runs
and uploads in the running server. It needs permission to launch Chrome.

## Ten-minute presentation

| Time | Action and point to explain |
| --- | --- |
| 0:00–1:00 | Show the three-agent status and deterministic-mode label. Explain that the Reader preserves evidence, Analysis selects extracts and flags explicit conflicts, and Audit checks the returned claims. |
| 1:00–2:00 | Sign in as Analyst and load fictional documents. Expect the original three documents and 30 lines. Select a source, switch to JSON, and explain IDs and line numbers. |
| 2:00–3:00 | Run Brief Generator. Show cited extracts, audit passed, and human review pending. Follow a citation back to the original line. |
| 3:00–4:30 | Select Requirements Checker; leave `audit records` and `quantum encryption` in the input. Run it. Show the 30-day versus 90-day retention conflict, citing requirements line 9 and meeting-notes line 8. Explain that missing evidence is `unclear`, not automatically unmet. |
| 4:30–5:30 | Download result JSON and show the audit trail. Note the actor, timestamp, source IDs, evidence fingerprint, and audit status. Automated audit is separate from human approval. |
| 5:30–7:00 | Sign out and sign in as Manager. Select the Analyst's requirements run and open it. Enter a review note and approve, then optionally reject with a different note to show the decision history. Source conflicts remain visible. |
| 7:00–8:00 | Clear the page and load examples as Manager. Expect four documents, including Manager-only notes. Open the restricted source, then sign out to show the text disappears. |
| 8:00–9:00 | Show the direct API denial below, or run the focused access test. Explain that backend checks enforce permissions even if someone bypasses the UI. |
| 9:00–10:00 | Upload a synthetic `.txt` file or show the manifest used to swap documents. State the limitations and show the passing automated test summary. |

### Show direct API access denial

This focused automated test proves that an Analyst cannot retrieve restricted
text or submit its ID for analysis, even with forged role/access metadata:

```powershell
python -m unittest discover -s tests -p test_workflow.py -k direct_restricted -v
```

For a live API demonstration in PowerShell, while the application is running:

```powershell
$base = 'http://127.0.0.1:8000'
$analystSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$managerSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-RestMethod "$base/api/login" -Method Post -WebSession $analystSession -ContentType 'application/json' -Body '{"username":"analyst","password":"AnalystDemo!2026"}'
Invoke-RestMethod "$base/api/login" -Method Post -WebSession $managerSession -ContentType 'application/json' -Body '{"username":"manager","password":"ManagerDemo!2026"}'
$restricted = (Invoke-RestMethod "$base/api/demo" -WebSession $managerSession).documents | Where-Object access -eq 'restricted' | Select-Object -First 1
try {
    Invoke-RestMethod "$base/api/documents/$($restricted.document_id)" -WebSession $analystSession
} catch {
    Write-Output ("Expected access denial. HTTP status: " + [int]$_.Exception.Response.StatusCode)
}
```

Expected status: **403**, with no restricted source text in the response.

## Swap test documents

The original three files remain unchanged. `sample_documents/manifest.json`
defines which files load and their trusted roles. Paths are relative to that
folder; restricted files live in its `restricted/` subfolder.

```json
{
  "documents": [
    {"path": "public.txt", "allowed_roles": ["analyst", "manager"]},
    {"path": "restricted/notes.txt", "allowed_roles": ["manager"]}
  ]
}
```

Copy your synthetic files and a manifest into another folder, then start:

```powershell
python -m backend --sample-dir "C:\path\to\synthetic-set"
```

Restart after editing the manifest or source files. Identical bytes share an ID;
use distinct file contents for different access classifications. Managers can
also choose **Restricted: Manager only** before uploading a new synthetic file.
Standard uploads belong to the uploader and Managers; seeded public examples
are shared with both accounts. Document text and client-supplied role fields
cannot grant access. A restriction cannot retract copies already downloaded.

## Storage and limits

Sessions, uploads, and analysis results are held in server memory. A refresh or
logout clears the page, but permitted runs can be reopened until server restart.
The metadata-only audit log persists in `.runtime/audit.jsonl`, ignored by Git.
It contains no source text, passwords, session tokens, or review-note text.
Choose another log folder with `--data-dir "C:\path\to\demo-logs"`.
After restart, the log remains but earlier runs cannot be reopened through the
app; retain downloaded results for presentation records.

Existing upload limits remain: 12 documents per request, 256 KiB and 10,000
lines per file, and 2 MiB decoded bytes total. Demo storage is bounded to 100
documents and 100 analyses per process; restart to clear the in-memory records.

## Known limitations

- Deterministic briefs are capped at 12 verbatim extracts. Optional Gemini drafts
  require human semantic review; see the Phase 1 guide for bounds and fallback.
- Conflict detection checks explicit record/log retention durations in hours,
  days, and weeks. It cannot reliably resolve context, amendments, different
  scopes, or arbitrary contradictions. All reported conflicts need human review.
- Requirement matching uses words, not semantic compliance reasoning. Checks
  remain `unclear`, whether matching evidence is present or absent.
- Deterministic audit checks exact single-line extracts and supported conflict rules.
  Audit passed does not establish general truth or legal/regulatory compliance.
- Manager approval records a decision, not an automatic resolution. Hard-flagged
  analyses cannot be approved, but may be rejected. A Gemini draft with warning-only
  `needs_review` status can be approved with a note; its audit status stays unchanged.
- Accounts, HTTP sessions, and the editable JSONL file are for a localhost demo.
  No production identity system, HTTPS hosting, tamper-proof ledger, database,
  or PDF/Word/OCR is provided. The optional Gemini integration sends only selected,
  authorized synthetic evidence. Synthetic data only.
