"""Step 3a. The review app.   python app.py  ->  http://127.0.0.1:5000

Flask serves a small JSON API plus the built React screen in static/dist
(source in frontend/). A reviewer sees each proposed change with its evidence
and its red / yellow / green rule checks, then approves or rejects.

Approve (and the two-step Undo) are the ONLY things in this project that write to
the CRM, and the server enforces the rules verdict before they do:
    green   -> approve
    yellow  -> approve only with an explicit confirmation
    red     -> approve only with an override AND a typed reason (audited)
"""
import json

from flask import Flask, jsonify, request, send_from_directory

import pipeline
from datetime import date

from sync import checks, config, store, undo
from sync.apply import Conflict, apply_proposal
from sync.crm import CRM, CRMError

app = Flask(__name__, static_folder="static")
OPEN = ("pending", "failed", "conflict")

KIND_LABELS = {
    "CREATE": "New account", "RENAME": "Rename", "REPARENT": "Re-parent", "CHOW": "Change of ownership",
    "CHOW_LINK": "CHOW link", "DUPLICATE": "Duplicate", "FIX_ADDRESS": "Address fix",
    "FIX_CARE_TYPE": "Care type fix", "REACTIVATE": "Reactivate", "OFF_WEBSITE": "Off website",
}


def present(row):
    """A stored proposal plus its rule checks, ready for the screen."""
    evidence, actions = json.loads(row["evidence"]), json.loads(row["actions"])
    ev = checks.evaluate(row["kind"], evidence, actions)
    return dict(_undo_info(row, evidence, actions), **{
        "id": row["id"], "kind": row["kind"], "kind_label": KIND_LABELS.get(row["kind"], row["kind"]),
        "title": row["title"], "summary": row["summary"], "status": row["status"],
        "location": evidence.get("location"), "accounts": ev["accounts"], "reasons": evidence.get("reasons", []),
        "rules": ev["rules"], "verdict": ev["verdict"], "cautions": ev["cautions"], "actions": actions,
        "result": json.loads(row["result"]) if row["result"] else None,
        "decided_at": row["decided_at"], "decided_by": row["decided_by"], "reason": row["reason"],
    })


def _events(db, pid):
    return [dict(r) for r in db.execute("SELECT * FROM audit WHERE proposal_id=? ORDER BY id", (pid,))]


def _undo_info(row, evidence, actions):
    """What the screen needs to offer (and explain) a reversal."""
    if row["status"] not in ("applied", "undo_requested", "reversed"):
        return {}
    result = json.loads(row["result"]) if row["result"] else []
    _, preview = undo.plan(result, row["title"], "(reason)", date.today().isoformat(), evidence)
    db = store.connect()
    ev = _events(db, row["id"])
    asked = next((e for e in reversed(ev) if e["event"] == "undo_requested"), None)
    done = next((e for e in reversed(ev) if e["event"] == "undo_applied"), None)
    return {"undo": {
        "preview": preview,
        "related": undo.related(db.execute("SELECT * FROM proposals").fetchall(), row["id"], result, actions),
        "reason": asked["detail"] if asked and row["status"] in ("undo_requested", "reversed") else None,
        "requested_by": asked["actor"] if asked else None, "requested_at": asked["at"] if asked else None,
        "reversed_at": done["at"] if done and row["status"] == "reversed" else None,
    }}


@app.get("/")
def index():
    return send_from_directory("static/dist", "index.html")


@app.get("/api/state")
def state():
    db = store.connect()
    rows = [present(r) for r in db.execute("SELECT * FROM proposals WHERE status != 'stale' ORDER BY kind, title")]
    matches = []
    for r in db.execute("SELECT detail FROM matches ORDER BY slug"):
        m = json.loads(r["detail"])
        ev = checks.evaluate("MATCH", m["evidence"], [])
        matches.append({"location": m["location"], "account": m["account"], "basis": m["basis"],
                        "checks": ev["accounts"][0]["checks"], "rules": ev["rules"], "verdict": ev["verdict"]})
    return jsonify({
        "reviewer": config.REVIEWER, "min_reason": checks.MIN_OVERRIDE_REASON,
        "open": [p for p in rows if p["status"] in OPEN],
        "decided": sorted([p for p in rows if p["status"] in ("applied", "rejected", "undo_requested", "reversed")], key=lambda p: p["decided_at"] or "", reverse=True),
        "matches": matches,
        "runs": [dict(r) for r in db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 30")],
        "audit": [dict(r) for r in db.execute("SELECT a.*, p.title FROM audit a LEFT JOIN proposals p ON p.id=a.proposal_id ORDER BY a.id DESC LIMIT 100")],
        "field_rules": checks.FIELD_RULES, "safety_rules": checks.SAFETY_RULES, "min_undo_reason": undo.MIN_REASON,
    })


@app.post("/api/proposals/<int:pid>/approve")
def approve(pid):
    db = store.connect()
    row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if row is None or row["status"] not in OPEN:
        return jsonify(ok=False, error="That proposal is not open for review."), 409

    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip()
    actions = json.loads(row["actions"])
    verdict = checks.evaluate(row["kind"], json.loads(row["evidence"]), actions)["verdict"]

    # ---- the safety gate: enforced here, not just in the browser
    if verdict == checks.YELLOW and not body.get("confirm"):
        return jsonify(ok=False, need="confirm", error="Rules flagged cautions. Confirmation is required."), 409
    if verdict == checks.RED:
        if not body.get("override") or len(reason) < checks.MIN_OVERRIDE_REASON:
            return jsonify(ok=False, need="override",
                           error="Rules advise against this change. An override and a written reason are required."), 409
        store.audit(db, pid, config.REVIEWER, "override", reason)

    try:
        result = apply_proposal(CRM(), actions)        # <- the only CRM write in the project
        store.decide(db, pid, "applied", config.REVIEWER, reason=reason, result=result)
        return jsonify(ok=True, message="Written to the CRM: %s" % row["title"])
    except Conflict as e:
        store.decide(db, pid, "conflict", config.REVIEWER, reason=str(e))
        return jsonify(ok=False, error="Not written. %s" % e), 409
    except CRMError as e:
        store.decide(db, pid, "failed", config.REVIEWER, reason=str(e))
        return jsonify(ok=False, error="The CRM rejected the write. Proposal kept for retry. %s" % e), 502


@app.post("/api/proposals/<int:pid>/reject")
def reject(pid):
    db = store.connect()
    row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if row is None or row["status"] not in OPEN:
        return jsonify(ok=False, error="That proposal is not open for review."), 409
    store.decide(db, pid, "rejected", config.REVIEWER, reason=((request.get_json(silent=True) or {}).get("reason") or "").strip())
    return jsonify(ok=True, message="Rejected. It will not be proposed again: %s" % row["title"])


# ------------------------------------------------------------------ two-step undo
# Step 1  /undo/request   a written reason (nothing is written to the CRM)
# Step 2  /undo/confirm   a separate request: typed word UNDO + acknowledgement; this is the CRM write
# Either way the whole trail (who, when, why) lands in the audit table.

@app.post("/api/proposals/<int:pid>/undo/request")
def undo_request(pid):
    db = store.connect()
    row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if row is None or row["status"] != "applied":
        return jsonify(ok=False, error="Only an approved change can be undone."), 409
    reason = ((request.get_json(silent=True) or {}).get("reason") or "").strip()
    if len(reason) < undo.MIN_REASON:
        return jsonify(ok=False, need="reason", error="Say why this should be undone (at least %d characters)." % undo.MIN_REASON), 409
    actions, preview = undo.plan(json.loads(row["result"] or "[]"), row["title"], reason, date.today().isoformat(), json.loads(row["evidence"]))
    if not actions:
        return jsonify(ok=False, error="Nothing to reverse: the approval did not change the CRM."), 409
    store.set_status(db, pid, "undo_requested", config.REVIEWER, "undo_requested", reason)
    return jsonify(ok=True, message="Undo requested. Step 2 (confirm) is still needed before anything changes: %s" % row["title"])


@app.post("/api/proposals/<int:pid>/undo/cancel")
def undo_cancel(pid):
    db = store.connect()
    row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if row is None or row["status"] != "undo_requested":
        return jsonify(ok=False, error="There is no pending undo request for that change."), 409
    store.set_status(db, pid, "applied", config.REVIEWER, "undo_cancelled")
    return jsonify(ok=True, message="Undo request cancelled. The change stays in place: %s" % row["title"])


@app.post("/api/proposals/<int:pid>/undo/confirm")
def undo_confirm(pid):
    db = store.connect()
    row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if row is None or row["status"] != "undo_requested":
        return jsonify(ok=False, error="Step 1 comes first: request the undo and give a reason."), 409
    body = request.get_json(silent=True) or {}
    if (body.get("confirm_text") or "").strip().upper() != "UNDO" or not body.get("ack"):
        return jsonify(ok=False, need="confirm", error='Type UNDO and tick the acknowledgement to confirm.'), 409
    asked = next(e for e in reversed(_events(db, pid)) if e["event"] == "undo_requested")
    actions, _ = undo.plan(json.loads(row["result"] or "[]"), row["title"], asked["detail"], date.today().isoformat(), json.loads(row["evidence"]))
    try:
        result = apply_proposal(CRM(), actions)        # <- the reversal's only CRM write
        store.set_status(db, pid, "reversed", config.REVIEWER, "undo_applied", json.dumps(result))
        return jsonify(ok=True, message="Reversed in the CRM: %s" % row["title"])
    except Conflict as e:
        store.set_status(db, pid, "applied", config.REVIEWER, "undo_conflict", str(e))
        return jsonify(ok=False, error="Not undone. %s" % e), 409
    except CRMError as e:
        store.audit(db, pid, config.REVIEWER, "undo_failed", str(e)); db.commit()
        return jsonify(ok=False, error="The CRM rejected the reversal. The request is kept so you can retry. %s" % e), 502


@app.post("/api/proposals/<int:pid>/reopen")
def reopen(pid):
    """Send a reversed proposal back to the review queue (no CRM write)."""
    db = store.connect()
    row = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if row is None or row["status"] != "reversed":
        return jsonify(ok=False, error="Only a reversed change can be sent back to review."), 409
    store.set_status(db, pid, "pending", config.REVIEWER, "reopened")
    return jsonify(ok=True, message="Back in the review queue: %s" % row["title"])


@app.post("/api/run")
def run_now():
    try:
        s = pipeline.run()
        return jsonify(ok=True, message="Run #%(run)d: %(new)d new, %(skipped_decided)d already decided and skipped, %(matches)d clean matches." % s)
    except (SystemExit, Exception) as e:   # show the safety-valve abort instead of crashing the app
        return jsonify(ok=False, error="Pipeline did not complete: %s" % e), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
