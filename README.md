# iContinuum-Agentic-AI-mesh

Proof of concept for our Unissant Challenge X UC2 Project. Three specialized agents will
share evidence through a Python backend for a Brief Generator and a Requirements
Checker:

1. **Document Reader:** extracts original text, document IDs, and source lines.
2. **Analysis Agent:** produces cited source extracts and flags explicit retention conflicts.
3. **Audit Agent:** validates exact evidence support and records audit information.

The local prototype includes the Document Reader, a browser workspace, and a
Python API, authentication, role permissions, and Manager review. It runs in
**deterministic demo mode by default**, with a backend-only AI Brief Generator:
Groq GPT OSS 20B is preferred when configured, and Gemini is optional.
Both preserve deterministic fallback. No third-party Python packages
or frontend build step are needed. Live generation requires explicit opt-in.
The API is
independent of model choice; it does not require Unissant's model.

**Start here:** [full-workflow demo guide](docs/demo-guide.md), including exact
commands, demo credentials, document swapping, limitations, and a ten-minute
presentation sequence. No database or new Python dependencies are needed.

See [AI providers](docs/ai-providers.md) for selection, configuration, audit/review
semantics, mocked tests, and startup steps. [Gemini Phase 1](docs/gemini-phase1.md)
retains the optional Gemini details. No live provider request
has been made during implementation. The Requirements Checker remains
deterministic; [Phase 2](docs/phase2-plan.md) is a plan only.

## Open the local frontend and API

From this repository folder, run:

```powershell
python -m backend
```

Keep that terminal running and open **http://127.0.0.1:8000** in your browser.
Press **Ctrl+C** in the terminal to stop. If port 8000 is busy, run
`python -m backend --port 8001` and open the printed address.

The **frontend** is the page you interact with. The **API** is the Python layer
that receives its requests and calls the reader. One Python command starts
both; Node.js, npm, and extra Python packages are not needed to use the app.

Sign in as `analyst` / `AnalystDemo!2026` or `manager` / `ManagerDemo!2026`.
These are synthetic local-demo accounts, not production credentials.

You can upload UTF-8 `.txt` files, load authorized fictional examples, inspect
numbered lines, copy a source citation (Shift-click for a range), remove files,
and download JSON. Select Brief Generator or Requirements Checker to download
an analysis request or run the integrated analysis. Each result includes cited
extracts, audit status, and pending human review. Managers can reopen runs,
approve/reject them with notes, and access restricted synthetic documents.
The Requirements Checker flags the sample's 30-day versus 90-day retention
conflict. Matching words alone never count as proof of compliance.

Uploads and results stay in server memory until restart; refreshing clears
the page view, and saved runs can be reopened after login. Audit metadata
persists in the ignored `.runtime/audit.jsonl` file. Limits are 12 documents,
256 KiB and 10,000 lines per file, and
2 MiB total per upload request. Identical contents are skipped in the browser.

- [Full-workflow demo guide](docs/demo-guide.md)
- [Team API contract and analysis output](docs/api-contract.md)
- [Synthetic data, evaluation method, and limitations](docs/evaluation.md)

The challenge organizers do not supply a common schema, dataset, or answer key;
these documents describe our implementation and evaluation. The connection point is
`backend/analysis.py::analyze_documents()`.

### Folder guide

```text
backend/             Local server, upload API, and analysis connection point
frontend/            HTML page, CSS styling, and browser JavaScript
document_reader/     Shared extraction code and original command-line reader
mesh/                Existing deterministic agents and retention-conflict rules
sample_documents/    Original three sources, restricted example, access manifest
tests/               Reader and HTTP API tests
docs/                Team interface contract and evaluation notes
```

## Setup

Use Python 3.9 or newer. In PowerShell, open the repository folder and check:

```powershell
python --version
```

If your computer uses the Windows Python launcher, try `py --version` and replace
`python` with `py` in the commands below. If neither command reports a Python
version, install [Python for Windows](https://www.python.org/downloads/windows/)
before running the reader. No `pip install` is needed.

## Read a document

Run these commands from the repository root (the folder containing this README):

```powershell
python -m document_reader sample_documents/project_brief.txt
```

`-m document_reader` tells Python to run our reader package. The final argument
is the file to read. The command prints structured JSON in the terminal.

Read all three synthetic documents together by listing their paths explicitly:

```powershell
python -m document_reader sample_documents/project_brief.txt sample_documents/requirements.txt sample_documents/meeting_notes.txt
```

Use quotes around paths containing spaces. To save the JSON to a file in
PowerShell:

```powershell
python -m document_reader sample_documents/project_brief.txt | Out-File -Encoding utf8 reader_output.json
```

## Use the reader from another agent

```python
import json
from document_reader import read_document

document = read_document("sample_documents/requirements.txt")
print(json.dumps(document, indent=2))

if document["status"] == "ok":
    # Source line 9 is at list position 8 because Python lists start at zero.
    source_line = document["lines"][8]
    citation = {
        "document_id": document["document_id"],
        "line_start": source_line["line_number"],
        "line_end": source_line["line_number"],
    }
    print(citation)
    print(source_line["text"])
```

`read_document()` returns a Python dictionary: named fields containing the
document data. `json.dumps()` turns that dictionary into JSON text. The command
line wraps one or more results in a `documents` list.

## Result format

For a UTF-8 file named `example.txt` containing exactly `abc` with no final line
ending, the command-line result is:

```json
{
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
      "lines": [
        {"line_number": 1, "text": "abc"}
      ],
      "error": null
    }
  ]
}
```

- **`document_id`:** `doc_` followed by the full SHA-256 fingerprint of the file
  bytes. It is repeatable across runs and computers. Renaming or moving a file
  keeps its ID; identical copies share an ID. Editing text, encoding, or line
  endings changes the ID. These IDs identify document versions, so retain the
  original files or results when saving citations. SHA-256 collisions are
  theoretically possible but extremely unlikely.
- **`text`:** the complete decoded original, including spaces, blank lines, and
  original line endings. A UTF-8 byte order mark, if present, is also retained.
  JSON escapes such as `\n`, `\r`, or `\u00e9` restore the original characters
  when parsed; they do not change the evidence.
- **`lines`:** source text with line numbers starting at **1**. Line text omits
  the ending itself, while `text` preserves it. Windows CRLF, Unix LF, and CR
  endings are supported. A final line ending does not add a phantom empty line;
  actual blank lines are retained. No whitespace is stripped.
- **`source_path`:** the path supplied by the caller, kept for locating the
  source. The path does not affect the ID.
- **`status`:** `ok` for readable nonempty text, `empty` for zero-byte files, or
  `error` for failures. Whitespace-only files retain their text and have `ok`
  status. Empty files still receive a content ID, with no source lines.
- **`error`:** `null` on success or an object with a `code` and `message`.
  Codes are `file_not_found`, `permission_denied`, `read_error`,
  `invalid_encoding`, and `unsupported_file_type`. Failed reads have a null
  document ID, empty text, and no lines; they never return partial evidence.

The command finishes with exit code `0` when every file is readable (including
empty files), `1` if any file fails, and `2` for incorrect command arguments.
With multiple files, one failure does not prevent the others from being read.

## Synthetic test documents and citations

All three files in `sample_documents/` are fictional, created for this PoC:

| File | Purpose |
| --- | --- |
| `project_brief.txt` | Project goals, shared backend, and launch date |
| `requirements.txt` | Numbered requirements, including 30-day audit retention |
| `meeting_notes.txt` | Meeting notes requesting 90-day audit retention |

The retention statements deliberately disagree: `requirements.txt` line **9**
says 30 days, while `meeting_notes.txt` line **8** says 90 days. The reader
preserves these statements for the future Analysis Agent; it does not interpret
them. The Audit Agent can later look up each document ID and cited line range
to check a generated claim.

## Run the automated tests

```powershell
python -m unittest discover -s tests -v
```

`unittest` is Python's built-in testing tool. The tests check exact text and
line preservation, repeatable IDs, changed contents, Unicode, empty files,
missing and unreadable files, unsupported types, and command-line JSON output.
They also verify the source locations of the fictional conflicting statements
and exercise the API over real local HTTP requests. Temporary test files and
test servers are cleaned up automatically. If Node.js is installed, you can
check JavaScript syntax with `node --check frontend/app.js`. See the evaluation
notes for the manual browser checklist.

## Current scope

This version reads UTF-8 `.txt` files into memory and exposes the reader through
a local browser workspace and API. It does not yet support PDFs, Word documents,
OCR, automatic folder scanning, large-file streaming, durable workspaces, or
production accounts. The server is a local development prototype. Summaries
are capped at 12 verbatim extracts; conflict detection covers explicit retention
durations only. Audit validates exact single-line extracts and the supported
rules, not general semantic truth. See the demo guide for full limitations.
## Original project proposal (historical)

The notes below are retained from the original team proposal. Technology and
status statements in this section describe that earlier plan, not the current
demo. The implemented workflow and run instructions above take precedence.

Unissant Challenge X — iContinuum Agentic AI Mesh

Project Overview:
This project is a proof of concept for a reusable, secure, multi-agent AI workflow that analyzes documents and produces source-cited results.

Goals:
Extract information from synthetic documents.
Identify important facts and conflicting evidence.
Generate summaries with traceable citations.
Enforce role-based document access.
Record audit information and support human review.
Support two applications through one shared API: a brief generator and a requirements checker.


Proposed Architecture:
Document Agent: Extracts text and preserves document IDs and source passages.
Analysis Agent: Analyzes evidence, detects conflicts, and produces cited findings.
Audit Agent: Validates citations, flags unsupported claims, and records audit information.
The Python backend will coordinate these agents and enforce access controls.


Planned Technologies:
Python, FastAPI, GitHub, pytest, Unissant-hosted LLM (pending access) - GPT-OSS-20b, Streamlit or another lightweight frontend


Current Status:
Initial planning and repository setup. Architecture and interfaces are subject to refinement.
Data and Security
Use only synthetic or approved public documents. No real government data, PII, CUI, or production credentials.
Can test security later on with prompt injection and testing authentication based on user role.


Next Steps:
Create sample documents.
Build the document reader.
Define the shared evidence format.
Implement analysis and audit modules.
Connect the modules through one API.
Develop and test both client applications.
