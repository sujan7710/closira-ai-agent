"""SQLite persistence for the staff side: handoff tickets, leads and SOP gaps.

The agent itself stays storage-free; the web layer calls record_turn() after
every reply. One open ticket per conversation: later escalations in the same
conversation add a reason to it rather than opening duplicates, and the
transcript on an open ticket keeps updating so staff see the latest messages.
"""

import json
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',      -- open | closed
    category    TEXT NOT NULL,                     -- latest escalation category
    reasons     TEXT NOT NULL,                     -- JSON list of reasons
    transcript  TEXT NOT NULL,                     -- JSON list of [role, text]
    lead        TEXT NOT NULL,                     -- JSON object
    resolution  TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_open ON tickets (business_id, session_id, status);

CREATE TABLE IF NOT EXISTS leads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    fields      TEXT NOT NULL,                     -- JSON object
    complete    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    UNIQUE (business_id, session_id)
);

CREATE TABLE IF NOT EXISTS sop_gaps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    question    TEXT NOT NULL,
    normalized  TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gaps_business ON sop_gaps (business_id, normalized);
"""


def normalize_question(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s£']", " ", text.lower())).strip()


class Storage:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- writes from the chat flow ---------------------------------------------------

    def record_turn(self, state, reply):
        """Persist whatever this turn changed: ticket, SOP gap, lead."""
        biz, sid, now = state.business.id, state.session_id, time.time()
        transcript = json.dumps(state.transcript)
        lead = json.dumps(state.lead)

        with self._lock, self._conn() as c:
            open_ticket = c.execute(
                "SELECT id, reasons FROM tickets WHERE business_id=? AND session_id=? AND status='open'",
                (biz, sid),
            ).fetchone()

            if reply.escalated:
                if open_ticket:
                    reasons = json.loads(open_ticket["reasons"]) + [reply.reason]
                    c.execute(
                        "UPDATE tickets SET category=?, reasons=?, transcript=?, lead=?, updated_at=? WHERE id=?",
                        (reply.category, json.dumps(reasons), transcript, lead, now, open_ticket["id"]),
                    )
                else:
                    c.execute(
                        "INSERT INTO tickets (business_id, session_id, category, reasons, transcript, lead,"
                        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                        (biz, sid, reply.category, json.dumps([reply.reason]), transcript, lead, now, now),
                    )
            elif open_ticket:
                c.execute(
                    "UPDATE tickets SET transcript=?, lead=?, updated_at=? WHERE id=?",
                    (transcript, lead, now, open_ticket["id"]),
                )

            if reply.route == "sop_gap" or reply.category == "unanswered_limit":
                question = state.unanswered[-1]
                c.execute(
                    "INSERT INTO sop_gaps (business_id, session_id, question, normalized, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (biz, sid, question, normalize_question(question), now),
                )

            if state.lead:
                c.execute(
                    "INSERT INTO leads (business_id, session_id, fields, complete, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?)"
                    " ON CONFLICT (business_id, session_id) DO UPDATE SET"
                    " fields=excluded.fields, complete=excluded.complete, updated_at=excluded.updated_at",
                    (biz, sid, lead, int(state.qualification_complete), now, now),
                )

    # --- staff inbox ----------------------------------------------------------------------

    @staticmethod
    def _ticket(row):
        t = dict(row)
        t["reasons"] = json.loads(t["reasons"])
        t["transcript"] = json.loads(t["transcript"])
        t["lead"] = json.loads(t["lead"])
        return t

    def list_tickets(self, business_id=None, status="open"):
        sql, args = "SELECT * FROM tickets WHERE 1=1", []
        if business_id:
            sql += " AND business_id=?"
            args.append(business_id)
        if status in ("open", "closed"):
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY updated_at DESC"
        with self._conn() as c:
            return [self._ticket(r) for r in c.execute(sql, args)]

    def get_ticket(self, ticket_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        return self._ticket(row) if row else None

    def close_ticket(self, ticket_id, resolution):
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE tickets SET status='closed', resolution=?, updated_at=? WHERE id=? AND status='open'",
                (resolution.strip() or None, time.time(), ticket_id),
            )
            return cur.rowcount == 1

    def list_leads(self, business_id=None):
        sql, args = "SELECT * FROM leads", []
        if business_id:
            sql += " WHERE business_id=?"
            args.append(business_id)
        sql += " ORDER BY updated_at DESC"
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(sql, args)]
        for r in rows:
            r["fields"] = json.loads(r["fields"])
        return rows

    def gap_report(self, business_id=None, limit=20):
        """Most-asked questions the SOP could not answer, grouped by normalized text."""
        sql = ("SELECT normalized, MIN(question) AS example, COUNT(*) AS count,"
               " COUNT(DISTINCT session_id) AS conversations, MAX(created_at) AS last_asked"
               " FROM sop_gaps")
        args = []
        if business_id:
            sql += " WHERE business_id=?"
            args.append(business_id)
        sql += " GROUP BY normalized ORDER BY count DESC, last_asked DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def stats(self, business_id=None):
        where, args = ("WHERE business_id=?", [business_id]) if business_id else ("", [])
        with self._conn() as c:
            q = lambda sql: c.execute(sql, args).fetchone()[0]  # noqa: E731
            return {
                "open_tickets": q(f"SELECT COUNT(*) FROM tickets {where} {'AND' if where else 'WHERE'} status='open'"),
                "closed_tickets": q(f"SELECT COUNT(*) FROM tickets {where} {'AND' if where else 'WHERE'} status='closed'"),
                "complete_leads": q(f"SELECT COUNT(*) FROM leads {where} {'AND' if where else 'WHERE'} complete=1"),
                "partial_leads": q(f"SELECT COUNT(*) FROM leads {where} {'AND' if where else 'WHERE'} complete=0"),
                "sop_gaps": q(f"SELECT COUNT(*) FROM sop_gaps {where}"),
            }
