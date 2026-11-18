"""Local state (SQLite): the review queue, every decision, and an audit log.

This is what makes re-runs safe. Every proposal has a fingerprint (a hash of
its `key`, i.e. WHAT is being decided). The fingerprint column is UNIQUE, so a
decision that has already been made can never be queued a second time.

Proposal statuses
    pending    waiting for a reviewer
    applied    approved and written to the CRM          (final)
    rejected   reviewer said no                         (final, remembered forever)
    failed     approved, but the CRM write errored      (retryable)
    conflict   approved, but the CRM had changed since  (re-opened by the next run)
    stale      a later run no longer proposes it        (re-opened if it comes back)
    undo_requested  step 1 of a reversal was filed         (waits for step 2 or a cancel)
    reversed   an approved change was undone               (final; can be sent back to review)
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from . import config

FINAL = ("applied", "rejected", "reversed", "undo_requested")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, started_at TEXT, locations INTEGER, accounts INTEGER,
    new_proposals INTEGER, skipped_decided INTEGER, matches INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE, kind TEXT, title TEXT, summary TEXT,
    confidence TEXT, slug TEXT, account_id TEXT, evidence TEXT, actions TEXT,
    status TEXT DEFAULT 'pending', first_run INTEGER, last_run INTEGER,
    decided_at TEXT, decided_by TEXT, reason TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS matches (
    slug TEXT PRIMARY KEY, account_id TEXT, detail TEXT, last_run INTEGER);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, at TEXT, proposal_id INTEGER, actor TEXT, event TEXT, detail TEXT);
"""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def fingerprint(key):
    return hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(config.DB_PATH))
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def save_run(db, locations, accounts, proposals, matches):
    """Record a pipeline run. Returns counts for the log line."""
    cur = db.execute("INSERT INTO runs (started_at, locations, accounts) VALUES (?,?,?)",
                     (now(), len(locations), len(accounts)))
    run_id = cur.lastrowid
    new = skipped = 0

    for p in proposals:
        fp = fingerprint(p["key"])
        row = db.execute("SELECT id, status FROM proposals WHERE fingerprint=?", (fp,)).fetchone()
        payload = (p["kind"], p["title"], p["summary"], p["confidence"], p["slug"], p["account_id"],
                   json.dumps(p["evidence"]), json.dumps(p["actions"]))
        if row is None:
            db.execute("INSERT INTO proposals (kind,title,summary,confidence,slug,account_id,evidence,actions,"
                       "fingerprint,first_run,last_run) VALUES (?,?,?,?,?,?,?,?,?,?,?)", payload + (fp, run_id, run_id))
            new += 1
        elif row["status"] in FINAL:
            # THE IDEMPOTENCY RULE: already decided -> never queue it again.
            db.execute("UPDATE proposals SET last_run=? WHERE id=?", (run_id, row["id"]))
            skipped += 1
        else:
            # Still open (pending/failed) or re-opened (conflict/stale): refresh with today's evidence.
            status = row["status"] if row["status"] in ("pending", "failed") else "pending"
            db.execute("UPDATE proposals SET kind=?,title=?,summary=?,confidence=?,slug=?,account_id=?,evidence=?,actions=?,"
                       "status=?,last_run=? WHERE id=?", payload + (status, run_id, row["id"]))

    # Anything still pending that this run did not produce is no longer true.
    db.execute("UPDATE proposals SET status='stale' WHERE status='pending' AND last_run<?", (run_id,))

    db.execute("DELETE FROM matches")
    for m in matches:
        db.execute("INSERT INTO matches VALUES (?,?,?,?)",
                   (m["slug"], m["account"]["account_id"], json.dumps(m), run_id))

    db.execute("UPDATE runs SET new_proposals=?, skipped_decided=?, matches=? WHERE id=?",
               (new, skipped, len(matches), run_id))
    db.commit()
    return {"run": run_id, "new": new, "skipped_decided": skipped, "matches": len(matches)}


def last_location_count(db):
    row = db.execute("SELECT locations FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return row["locations"] if row else None


def audit(db, proposal_id, actor, event, detail=""):
    db.execute("INSERT INTO audit (at, proposal_id, actor, event, detail) VALUES (?,?,?,?,?)",
               (now(), proposal_id, actor, event, detail if isinstance(detail, str) else json.dumps(detail)))


def decide(db, proposal_id, status, actor, reason="", result=None):
    db.execute("UPDATE proposals SET status=?, decided_at=?, decided_by=?, reason=?, result=? WHERE id=?",
               (status, now(), actor, reason, json.dumps(result) if result is not None else None, proposal_id))
    audit(db, proposal_id, actor, status, reason or (result or ""))
    db.commit()


def set_status(db, proposal_id, status, actor, event, detail=""):
    """Change status without touching `result` (which holds what the original approval wrote)."""
    db.execute("UPDATE proposals SET status=? WHERE id=?", (status, proposal_id))
    audit(db, proposal_id, actor, event, detail)
    db.commit()
