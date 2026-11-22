"""Shared Groq settings and a connectivity check."""

import logging
import os

logger = logging.getLogger("closira.llm")


def groq_api_key():
    """GROQ_API_KEY with surrounding whitespace/quotes removed.

    Keys pasted into hosting dashboards often pick up a trailing space or quotes,
    which makes every call fail with 401 even though the key is right.
    """
    key = (os.getenv("GROQ_API_KEY") or "").strip().strip("\"'").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set")
    return key


def check_connection():
    """Return (ok, message). Lists models (no tokens used) and checks the configured ones exist."""
    try:
        from groq import Groq

        available = {m.id for m in Groq(api_key=groq_api_key(), timeout=10).models.list().data}
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:200]}"

    wanted = {
        os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        os.getenv("GROQ_CLASSIFIER_MODEL", "openai/gpt-oss-20b"),
        os.getenv("GROQ_EXTRACTOR_MODEL", os.getenv("GROQ_CLASSIFIER_MODEL", "openai/gpt-oss-20b")),
    }
    missing = sorted(wanted - available)
    if missing:
        return False, f"models not available to this key: {', '.join(missing)}"
    return True, "ok (" + ", ".join(sorted(wanted)) + ")"


def log_connection_check():
    ok, message = check_connection()
    if ok:
        logger.info("GROQ_CHECK %s", message)
    else:
        logger.error("GROQ_CHECK FAILED %s - every reply will fall back to a human handoff", message)
    return ok, message
