"""Select one backend provider at startup. Never perform a connectivity probe."""

import os

from .gemini import GeminiBriefGenerator, ProviderUnavailable
from .groq import GroqBriefGenerator


class _InvalidConfiguration:
    enabled = True
    provider = "none"
    model = None

    def generate(self, documents, conflicts):
        raise ProviderUnavailable("invalid_configuration")


def brief_generator_from_environment():
    # Preserve explicit opt-in, even if either real key already exists.
    if os.environ.get("ICONTINUUM_AI_MODE", "deterministic") != "auto":
        return None
    provider = os.environ.get("ICONTINUUM_AI_PROVIDER", "auto")
    if provider not in {"auto", "groq", "gemini"}:
        return _InvalidConfiguration()
    if provider == "groq" or (provider == "auto" and os.environ.get("GROQ_API_KEY", "")):
        return GroqBriefGenerator.from_environment()
    return GeminiBriefGenerator.from_environment()
