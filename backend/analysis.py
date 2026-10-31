"""The team-owned integration point; no model or sample analysis is called here.

Your teammate can replace analyze_documents() when their agent is ready.
See docs/api-contract.md for the request and required result format.
"""


class AnalysisUnavailable(Exception):
    """Raised until the real Analysis Agent has been connected."""


def analyze_documents(request: dict) -> dict:
    raise AnalysisUnavailable("The Analysis Agent has not been connected yet.")
