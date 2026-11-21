"""Production-mode behaviour, health check and rate limiting."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import app as app_module
from ratelimit import RateLimiter, parse_rate

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client():
    return app_module.app.test_client()


def test_healthz(client):
    data = client.get("/healthz").get_json()
    assert data["status"] == "ok"
    assert {"bloom", "brightside"} <= set(data["businesses"])


def test_chat_rate_limited_per_client(client, monkeypatch):
    monkeypatch.setattr(app_module, "limiter", RateLimiter(per_client=(2, 60)))
    monkeypatch.setenv("ROUTER_MODE", "rules")
    assert client.post("/chat", json={"message": "hello"}).status_code == 200
    assert client.post("/chat", json={"message": "hello"}).status_code == 200
    res = client.post("/chat", json={"message": "hello"})
    assert res.status_code == 429 and "too quickly" in res.get_json()["error"]
    # A different client is unaffected.
    other = client.post("/chat", json={"message": "hello"}, environ_base={"REMOTE_ADDR": "198.51.100.7"})
    assert other.status_code == 200


def test_daily_cap():
    limiter = RateLimiter(daily=2)
    assert limiter.check("a") is None
    assert limiter.check("b") is None
    assert "daily" in limiter.check("c")


def test_sliding_window_expires(monkeypatch):
    import ratelimit

    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    limiter = RateLimiter(per_client=(1, 10))
    assert limiter.check("a") is None
    assert limiter.check("a") is not None
    now[0] += 11
    assert limiter.check("a") is None


@pytest.mark.parametrize("spec, expected", [("20/60", (20, 60.0)), ("5", (5, 60.0)), ("0", None), ("", None)])
def test_parse_rate(spec, expected):
    assert parse_rate(spec) == expected


def test_admin_disabled_in_production_without_password(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert client.get("/admin").status_code == 503  # even from localhost


def _import_app(env):
    full_env = {k: v for k, v in os.environ.items() if k not in ("FLASK_SECRET_KEY", "GROQ_API_KEY")}
    full_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", "import app"], cwd=ROOT, env=full_env, capture_output=True, text=True,
    )


def test_production_requires_secret_key():
    # Set it to empty rather than unsetting it: load_dotenv never overrides an existing
    # variable, so a developer's .env can't satisfy the check.
    res = _import_app({"APP_ENV": "production", "GROQ_API_KEY": "x", "FLASK_SECRET_KEY": ""})
    assert res.returncode != 0
    assert "FLASK_SECRET_KEY must be set" in res.stderr


def test_production_starts_with_config():
    res = _import_app({"APP_ENV": "production", "GROQ_API_KEY": "x", "FLASK_SECRET_KEY": "s"})
    assert res.returncode == 0, res.stderr



@pytest.mark.parametrize("trust_proxy, second_status", [("0", "429"), ("1", "200")])
def test_forwarded_for_only_trusted_behind_proxy(trust_proxy, second_status):
    """Two requests from the same socket claiming different X-Forwarded-For IPs, 1 msg/min limit.

    Without proxy trust the header is ignored, so the second request is the same client (429).
    With proxy trust each forwarded IP is its own client (200).
    """
    code = textwrap.dedent("""
        import app
        app.limiter = app.RateLimiter(per_client=(1, 60))
        c = app.app.test_client()
        for ip in ("203.0.113.5", "203.0.113.6"):
            r = c.post("/chat", json={"message": "hello"}, headers={"X-Forwarded-For": ip})
        print(r.status_code)
    """)
    env = {**os.environ, "APP_ENV": "production", "GROQ_API_KEY": "x", "FLASK_SECRET_KEY": "s",
           "TRUST_PROXY": trust_proxy, "ROUTER_MODE": "rules", "CLOSIRA_DB": ":memory:"}
    res = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().splitlines()[-1] == second_status
