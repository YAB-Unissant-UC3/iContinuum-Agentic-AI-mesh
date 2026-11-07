# Phase 2 plan: not implemented

For the November 7 showcase, explain which features were implemented and which
remain proposals. UTF-8 `.txt` support and standalone reusable services meet the
provided UC2 clarifications. PDF/OCR and GPT-OSS 20B are not required. The team
defines its own API contract, data, and evaluation method.

## Grounded Requirements Checker

After separate approval, extend the current checker with Gemini evidence
evaluation. Preserve the existing permission boundary, original citations,
deterministic fallback, audit trail, and human review.

Proposed outcomes:

| Outcome | Proposed meaning |
| --- | --- |
| `supported` | Cited evidence supports the requirement being satisfied |
| `contradicted` | Cited evidence directly indicates the requirement is not satisfied |
| `conflicting` | Sources support incompatible accounts; cite both sides |
| `unclear` | Missing, ambiguous, insufficient, or unverifiable evidence |

Finding a requirement statement is not proof of fulfillment. Every decision
needs evidence and a qualified explanation. Automated citation validity must
remain separate from semantic support and Manager judgment. Until implemented,
the existing checker keeps lexical matching and `unclear` statuses.

## Small synthetic evaluation suite

Prepare manually reviewed `.txt` cases and expected answers for supported,
contradicted, conflicting, and unclear requirements; different retention units;
irrelevant facts; prompt injection; and Manager-only evidence. Record exact
document hashes and source lines. Use separate development and evaluation cases
where practical; do not count model-authored expectations as an independent key.

Planned measurements, each with its numerator/denominator and failure examples:

- Citation-location validity and exact-quote validity.
- Human-reviewed claim support, including unsupported/uncertain claims.
- Conflict detection: expected versus found conflicts, false positives, and misses.
- Access denial: direct source, result, audit, spoofed-role, and pre-provider tests.
- Processing time: local preprocessing, provider wait, audit, total duration, and
  fallback reason, measured separately for deterministic and Gemini runs.

Record model ID, configuration, prompt version, input document IDs, repeat runs,
outages, and manual review rules. Report small sample sizes, synthetic-only data,
latency variability, model nondeterminism, and rubric uncertainty. Test pass rate
is not a model-accuracy score. No such benchmark or Gemini requirements extension
is implemented by Phase 1.
