import logging
import os
import secrets
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session

from chatbot import get_response
from conversation import SessionStore

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("closira.app")

MAX_MESSAGE_LENGTH = 1000

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

store = SessionStore()


def _session_id():
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message")

    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "Message must be a non-empty string."}), 400
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": f"Message must be at most {MAX_MESSAGE_LENGTH} characters."}), 400

    state = store.get(_session_id())
    try:
        reply = get_response(state, message)
    except Exception:
        logger.exception("Unhandled error while handling chat message")
        return jsonify({"error": "Something went wrong. Please try again."}), 500

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
    store.reset(_session_id())
    session.pop("sid", None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
