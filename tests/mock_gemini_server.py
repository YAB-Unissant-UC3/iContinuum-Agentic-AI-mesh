"""Offline browser-test server for Gemini or Groq synthetic fixtures.

Run: python tests/mock_gemini_server.py --port 8002
This never loads an environment key or connects to Google.
"""

import argparse
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.gemini import GeminiBriefGenerator
from backend.groq import GroqBriefGenerator
from backend.server import create_server


class MockResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.body[:limit]


def reply(request, timeout):
    body = json.loads(request.data)
    groq = "messages" in body
    data = json.loads(body["messages"][1]["content"] if groq else body["contents"][0]["parts"][0]["text"])
    claims = []
    for doc in data["source_evidence"][:4]:
        meaningful = [line for line in doc["lines"] if line["text"].strip()
                      and not line["text"].startswith(("FICTIONAL", "Project:", "Meeting date:"))]
        if not meaningful:
            meaningful = [line for line in doc["lines"] if line["text"].strip()]
        line = meaningful[0]
        claims.append({"section": "Overview", "text": "This synthetic source contributes evidence for the shared project brief. Its details should be reviewed alongside the other documents, and disagreements require a human decision.",
                       "citations": [{"document_id": doc["document_id"], "line_start": line["line_number"],
                                      "line_end": line["line_number"], "quote": line["text"]}]})
    if groq:
        return MockResponse({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps({"claims": claims})}}]})
    return MockResponse({"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"text": json.dumps({"claims": claims})}]}}]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--provider", choices=("gemini", "groq"), default="gemini")
    parser.add_argument("--fallback", action="store_true", help="Simulate a provider outage without a network request.")
    args = parser.parse_args()
    response = URLError("Offline test outage") if args.fallback else reply
    with tempfile.TemporaryDirectory() as folder, patch("backend.{}._send_request".format(args.provider), side_effect=response):
        provider = (GroqBriefGenerator("OFFLINE_TEST_FIXTURE_KEY", enabled=True) if args.provider == "groq"
                    else GeminiBriefGenerator("OFFLINE_TEST_FIXTURE_KEY", "gemini-mock-fixture", enabled=True))
        server = create_server(args.port, data_dir=folder, brief_generator=provider)
        print("MOCK ONLY: synthetic {} fixtures; no provider requests or real key. http://127.0.0.1:{}".format(args.provider, args.port), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
