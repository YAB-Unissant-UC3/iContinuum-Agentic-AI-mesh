# TXT and PDF support

Use Python 3.10+ and install `python -m pip install -r requirements.txt`.
The only dependency is pinned `pypdf==7.0.0`. The existing ignored portable
runtime already has it installed. Start with `python -m backend` or
`& .\.runtime\python\python.exe -B -m backend`. Restart an older server to load
these changes. TXT extraction, provider configuration, review, and fallback
are unchanged; live AI remains an explicit opt-in.

## Story documents and permissions

The five fictional story documents are registered alongside the four original
examples. Analyst sample loading returns seven documents; Manager loading
returns nine. The DOC numbers in filenames are human labels; canonical
`doc_...` IDs are SHA-256 hashes of original file bytes.

| File | Format / pages | Roles |
| --- | --- | --- |
| DOC-001_statement_ajmain.txt | UTF-8 TXT | Analyst, Manager |
| DOC-002_statement_saaiem.pdf | PDF / 2 | Analyst, Manager |
| DOC-003_statement_rifat.txt | UTF-8 TXT | Analyst, Manager |
| DOC-004_eyewitness_priya.pdf | PDF / 1 | Analyst, Manager |
| DOC-005_police_report.pdf | PDF / 2 | Manager only |

The manifest supplies server-owned ACLs. Samples are indexed by raw-byte hash
without text extraction; permissions are checked before parsing and returning
text. Every selected ID and every upload identity is checked before any member
of that batch is extracted. A renamed copy of the police PDF retains its ID
and is denied to Analysts. A Manager cannot reclassify it as public by uploading
the same bytes. Source, analysis, result history, and audit routes enforce ACLs;
PDFs are not public static assets. The frontend role indicator has no authority.

Uploads with different bytes are new document versions. This prototype has no
general content-based DLP: edited/re-encoded copies or copied passages cannot
reliably inherit a source's restriction. The local repository is also outside
the HTTP permission boundary. Use synthetic data only.

## Extraction and citations

pypdf extracts each page with `extraction_mode="layout"`. It retains aligned
table rows without summarizing text. Each line has a global number and PDF page
and page-local line numbers. A PDF's `text` is the global lines joined with
newlines; pages with no extracted text have empty mappings. The extraction
library version and mode are included for reproducibility.

Existing citation fields remain compatible: document ID, inclusive global
`line_start`/`line_end`, and `quote`. AI providers use that same contract. After
auditing, the server adds `page_references` from the source map, and the UI shows
page-local ranges. Clicking a citation highlights the exact global source lines.
Copied citations include both representations. Audit compares the entire quote,
including spaces and blank lines, against those exact extracted lines. It does
not fix quotations. Forged page references fail audit. A valid AI quote still
requires semantic review, and Manager approval never clears automated failures.

The analysis helper re-extracts PDF originals supplied privately by the
authorized workspace and compares text, identity, page maps, and extraction
metadata. Raw PDF bytes never enter provider payloads or result JSON. Documents
remain untrusted evidence under the existing provider instructions.

## Limits and unsupported inputs

- Existing upload limits: 256 KiB per file, 2 MiB per request, 12 files,
  10,000 extracted lines, and 5 MiB JSON request bodies.
- PDF limits: 50 pages; 256 KiB extracted characters; 4 MiB decoded stream/page
  contents; bounded parser/decompression work. Failures return fixed safe errors
  and discard partial text. Parser recovery messages are not logged.
- Encrypted PDFs are rejected; no password handling. Malformed PDFs are rejected
  when extraction cannot recover safely. pypdf recovers the supplied PDFs'
  cross-reference formatting defects without changing their original files.
- No OCR, DOCX, image interpretation, attachments, or active PDF content execution.
  An entirely blank/image-only PDF is `empty` and cannot be analyzed. Mixed PDFs
  expose empty-page mappings; images and other visual evidence need human review.
- Extracted lines are parser-derived, not original printed line numbers. Fonts,
  columns, rotated text, and complex tables can lose meaning or reading order.
  Long layout whitespace can consume the existing AI input budget and trigger
  deterministic fallback. No guarantee of semantic citation support is made.

## Synthetic evaluation

Run `python -m unittest discover -s tests -v`. Tests use all five originals,
generated blank/encrypted/oversized/malformed PDFs, and mocked AI transports.
They verify stable IDs, page counts, per-page text equality, blank-line and
whitespace-sensitive quotes, page tampering, unauthorized direct requests and
renamed uploads before extraction, provider payload isolation, review safeguards,
and fallback. Existing TXT and 30-day/90-day conflict tests remain in the suite.

The police-table regression checks the role/name/description/contact header,
Ajmain/red hoodie, Saaiem/gray beanie, and Rifat/green jacket in their respective
rows, plus the witness name, description, and fictional contact in one row.
It preserves the report's spelling `Priya Nandkumar`; no factual correction is
inferred from another document. Narrative and page-two disposition are retained.
These fixture checks establish extraction consistency for this dataset, not
general table understanding or contradiction accuracy. Visually compare the
original PDF table during showcase preparation.

`node --check frontend/app.js` and `node --check tests/browser_smoke.mjs` check
syntax. The existing browser suite now checks PDF uploads, page citations,
clipboard/JSON provenance, Manager review, and direct police-report API denial
at desktop and mobile widths. Use the offline server, for example:

```powershell
python tests/mock_gemini_server.py --provider groq --port 8031
# In another terminal; Node and Chrome are required:
node tests/browser_smoke.mjs http://127.0.0.1:8031 --mock-groq
```

Use `--provider gemini` / `--mock-gemini` for Gemini; add `--fallback` to the
server and `--mock-fallback` to the browser command to simulate an outage.
These fixtures use no real API key or external provider requests.
