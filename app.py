import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from business import BUSINESSES, DEFAULT_BUSINESS_ID, get_business
from chatbot import get_response
from conversation import SessionStore
from ratelimit import RateLimiter, parse_rate
from storage import Storage

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("closira.app")

MAX_MESSAGE_LENGTH = 1000
LOCAL_ADDRS = {"127.0.0.1", "::1", "localhost"}


def is_production():
    return os.getenv("APP_ENV", "development").lower() == "production"


app = Flask(__name__)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

if is_production():
    # Fail fast on missing config instead of running a half-secure demo.
    if not os.getenv("FLASK_SECRET_KEY"):
        raise RuntimeError("FLASK_SECRET_KEY must be set when APP_ENV=production")
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY must be set when APP_ENV=production")
    app.config.update(SESSION_COOKIE_SECURE=True)
    # Behind a hosting proxy (Render, Fly, nginx), trust one hop of X-Forwarded-* so
    # request.remote_addr is the real client (used by the rate limiter). Set
    # TRUST_PROXY=0 when clients connect directly, or they could spoof the header.
    if os.getenv("TRUST_PROXY", "1") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)

store = SessionStore()
_storages = {}
limiter = RateLimiter(
    per_client=parse_rate(os.getenv("CHAT_RATE_LIMIT", "20/60")),
    daily=int(os.getenv("CHAT_DAILY_LIMIT", "0")),
)


def get_storage():
    path = os.getenv("CLOSIRA_DB", "closira.db")
    if path not in _storages:
        _storages[path] = Storage(path)
    return _storages[path]


@app.template_filter("datetime")
def _fmt_datetime(ts):
    return datetime.fromtimestamp(ts).strftime("%d %b %Y, %H:%M")


def _session_id():
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


def _business_or_404(business_id):
    try:
        return get_business(business_id)
    except KeyError:
        abort(404, description=f"Unknown business '{business_id}'")


# ---------------------------------------------------------------------------
# Customer chat
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return redirect(url_for("chat_page", business_id=DEFAULT_BUSINESS_ID))


@app.route("/b/<business_id>")
def chat_page(business_id):
    biz = _business_or_404(business_id)
    return render_template("index.html", business=biz, businesses=BUSINESSES.values())


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "businesses": sorted(BUSINESSES)})


@app.route("/chat", methods=["POST"])
def chat():
    limited = limiter.check(request.remote_addr or "unknown")
    if limited:
        return jsonify({"error": limited}), 429

    data = request.get_json(silent=True) or {}
    message = data.get("message")

    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "Message must be a non-empty string."}), 400
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": f"Message must be at most {MAX_MESSAGE_LENGTH} characters."}), 400
    business_id = data.get("business", DEFAULT_BUSINESS_ID)
    if business_id not in BUSINESSES:
        return jsonify({"error": f"Unknown business '{business_id}'."}), 400

    state = store.get(_session_id(), get_business(business_id))
    try:
        reply = get_response(state, message)
    except Exception:
        logger.exception("Unhandled error while handling chat message")
        return jsonify({"error": "Something went wrong. Please try again."}), 500

    try:
        get_storage().record_turn(state, reply)
    except Exception:
        # Never fail the customer's chat because the staff-side database had a problem.
        logger.exception("Failed to persist turn business=%s session=%s", business_id, state.session_id)

    return jsonify({
        "response": reply.text,
        "escalated": reply.escalated,
        "reason": reply.reason,
        "route": reply.route,
        "category": reply.category,
        "source": reply.source,
        "confidence": reply.confidence,
    })


@app.route("/reset", methods=["POST"])
def reset():
    data = request.get_json(silent=True) or {}
    business_id = data.get("business", DEFAULT_BUSINESS_ID)
    if business_id in BUSINESSES:
        store.reset(_session_id(), get_business(business_id))
    session.pop("sid", None)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Staff inbox
# ---------------------------------------------------------------------------

def admin_required(view):
    """HTTP Basic auth with ADMIN_PASSWORD.

    Without a password the inbox only answers on localhost in development, and is
    disabled in production (behind a proxy every request can look local).
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        password = os.getenv("ADMIN_PASSWORD")
        if not password and is_production():
            abort(503, description="Staff inbox disabled: set ADMIN_PASSWORD.")
        if password:
            auth = request.authorization
            if not auth or not hmac.compare_digest(auth.password or "", password):
                return ("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="Closira staff"'})
        elif request.remote_addr not in LOCAL_ADDRS:
            abort(403, description="Set ADMIN_PASSWORD to use the staff inbox remotely.")
        return view(*args, **kwargs)
    return wrapper


def _csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.route("/admin")
@admin_required
def admin():
    business_id = request.args.get("business") or None
    if business_id and business_id not in BUSINESSES:
        abort(404)
    status = request.args.get("status", "open")
    s = get_storage()
    return render_template(
        "admin.html",
        businesses=BUSINESSES,
        business_id=business_id,
        status=status,
        stats=s.stats(business_id),
        tickets=s.list_tickets(business_id, status),
        leads=s.list_leads(business_id),
        gaps=s.gap_report(business_id),
        csrf_token=_csrf_token(),
        protected=bool(os.getenv("ADMIN_PASSWORD")),
    )


@app.route("/admin/tickets/<int:ticket_id>/close", methods=["POST"])
@admin_required
def close_ticket(ticket_id):
    token = request.form.get("csrf", "")
    if not hmac.compare_digest(token, session.get("csrf", "")):
        abort(400, description="Invalid form token. Reload the page and try again.")
    if not get_storage().close_ticket(ticket_id, request.form.get("resolution", "")):
        abort(404)
    logger.info("TICKET_CLOSED id=%s", ticket_id)
    next_url = request.form.get("next", "")
    if not next_url.startswith("/admin"):  # only redirect within the inbox (no open redirect)
        next_url = url_for("admin")
    return redirect(next_url)


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
