# Test data and evaluation notes

Use these notes when presenting the PoC. Describe extraction tests separately
from future analysis and audit quality. The organizers have not supplied a
common dataset or answer key; these fixtures and expected locations are ours.

## Data

Three fictional, manually authored UTF-8 text documents describe a Cedar Bridge
document review pilot. Each contains 10 source lines, for 30 lines in total.
They contain no real customer records. The `sample_documents/` folder holds the
exact files used by the demo.

| Document | Intended evidence |
| --- | --- |
| `project_brief.txt` | Shared backend, plain-text scope, launch date, local operation |
| `requirements.txt` | Seven requirements; line 9 requires 30-day audit retention |
| `meeting_notes.txt` | Line 8 requests 90-day audit retention; line 9 notes it is unresolved |

The retention disagreement is a future Analysis Agent test case. Loading these
files currently shows the original statements; it does not detect or resolve
their disagreement automatically.

## Current evaluation method

Run from the repository root:

```powershell
python -m unittest discover -s tests -v
node --check frontend/app.js
```

The Python suite checks exact content equality, blank lines and whitespace,
CRLF/LF/CR endings, repeatable full SHA-256 IDs, renamed and changed files,
Unicode and UTF-8 marks, empty/unreadable files, and command-line output.
API tests start a real HTTP server on a temporary loopback port and verify
uploads, source identity across disk and API reads, mixed successful and failed
documents, request validation, limits, same-origin handling, static routes,
and the explicit unavailable response for the unconnected Analysis Agent.
Tests do not call an LLM or external API.

Report the test runner's actual test count and pass/fail output for the revision
being demonstrated. This is a check of reader and API behavior, not a measure
of model accuracy. JavaScript syntax checking is not a substitute for browser
interaction testing.

Local verification on October 30, 2026: **30 Python tests passed** using Python
3.13.16, and the JavaScript syntax check passed. An installed Chrome browser in
headless mode also exercised the real UI and API: examples, uploads, duplicate
handling, empty/invalid files, literal HTML display, line-range citations and
clipboard copying, JSON preview/download, both handoff downloads, removal, and
clearing. Desktop and 390-pixel layouts were inspected, with no page overflow
at the narrow size and no browser errors during that run. This is local
functional verification, not cross-browser or accessibility certification.

## Manual browser checklist

1. Start `python -m backend` and open `http://127.0.0.1:8000`.
2. Load the examples: expect 3 documents, 30 source lines, and 3 ready for handoff.
3. Select requirements line 9 and meeting notes line 8; compare their statements.
4. Copy a citation and verify its ID and inclusive line range against JSON.
5. Shift-click two source lines to select and copy a citation range.
6. Upload the same original example: expect a skipped identical copy.
7. Upload an empty `.txt` file and an invalid UTF-8 `.txt` file: expect visible
   empty/error states. A failed file must not enter the analysis handoff.
8. Download reader JSON, then select each application and download its analysis
   request. Verify `task` is `brief` or `requirements` as selected.
9. Remove a document, clear the workspace, and refresh; no uploads should remain.
10. Check keyboard navigation and a narrow screen. File names and contents
    should be displayed as text, including strings resembling HTML.

## Assumptions and limitations

- Small English-language synthetic examples do not establish performance on
  real, multilingual, lengthy, or adversarial document collections.
- Only UTF-8 `.txt` input is supported. No PDF, Word, scanned-image, or OCR claims.
- IDs identify exact bytes. Git line-ending conversion or edits can create a
  new version ID. The example line numbers stay the same with CRLF or LF.
- The HTTP prototype has documented upload limits and runs only locally. Data
  is held in memory, with no database, authentication, or saved workspaces.
- The browser displays source references; it does not judge whether a claim
  is supported. Analysis and Audit Agent quality remain unevaluated until
  those agents are integrated.
- No latency, concurrency, security certification, model accuracy, requirement
  recall, or contradiction-detection score is claimed by these automated tests.

## Later team evaluation

Before evaluating generated results, agree on manually reviewed expected
claims, contradictions, and requirement outcomes. Record the model/version,
settings, exact document IDs, repeat runs, and failures. Measure citation
location validity separately from evidence support, and report the numerator
and denominator for every score. Include unclear/missing-evidence cases and
document the Audit Agent's decision rules.
