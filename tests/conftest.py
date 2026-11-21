import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chatbot  # noqa: E402
import classifier  # noqa: E402
import extractor  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch, tmp_path):
    """No test may reach Groq: drop the API key and any cached clients.

    Any un-faked LLM call then fails with 'GROQ_API_KEY is not set'. Also points
    the database at a per-test temp file.
    """
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(chatbot, "_llm", None)
    monkeypatch.setattr(classifier, "_classifiers", {})
    monkeypatch.setattr(extractor, "_extractors", {})
    monkeypatch.setenv("CLOSIRA_DB", str(tmp_path / "test.db"))
