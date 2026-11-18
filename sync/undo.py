"""Reversing an approved change.

An approved proposal stores exactly what it wrote (`result`): for every patch, the
old and new value of each field; for every create, the new account's id. That is all
we need to build the reverse, so nothing is guessed.

Rules of the reversal
  * Field changes are set back to their old values.
  * The API has no delete, so an account the proposal CREATED is set Inactive instead.
  * Notes are never restored from an old copy (that would erase later notes). A
    dated "Reversed" note is appended, so the history stays complete.
  * Each step carries an `expect` of what the CRM must look like now. If someone
    changed it since, nothing is written (apply_proposal raises Conflict).
  * The steps use the same writer as Approve (apply.apply_proposal), so they get the
    same checks: precondition, idempotence, read-back verification.
"""
import json

MIN_REASON = 10   # characters; same bar as overriding a red verdict


def _names(evidence):
    return {a["account"]["account_id"]: a["account"]["name"] for a in (evidence or {}).get("accounts", [])}


def plan(result, title, reason, today, evidence=None):
    """Return (actions, preview). `actions` run through apply_proposal; `preview` is what the reviewer reads."""
    tag = "[bellhaven-sync %s] " % today
    names, actions, preview = _names(evidence), [], []
    for entry in reversed(result or []):                      # undo in the opposite order
        if entry.get("op") == "create" and entry.get("result") == "created":
            fields = entry.get("fields", {})
            nm = fields.get("name", entry["account_id"])
            actions.append({"op": "patch", "account_id": entry["account_id"],
                            "fields": {"status": "Inactive",
                                       "note_append": tag + "Deactivated: this account was created by '%s' and that change was reversed. Reason: %s" % (title, reason)},
                            "expect": {"status": fields.get("status", "Active")}})
            preview.append({"account_id": entry["account_id"], "account": nm,
                            "label": "Account created by this change is deactivated (the API cannot delete accounts)",
                            "changes": [{"field": "status", "from": fields.get("status", "Active"), "to": "Inactive"}]})
        elif entry.get("op") == "patch" and entry.get("result") == "updated":
            changed = {k: v for k, v in entry["changed"].items() if k != "note"}
            if not changed:
                continue
            actions.append({"op": "patch", "account_id": entry["account_id"],
                            "fields": dict({k: v["from"] for k, v in changed.items()},
                                           note_append=tag + "Reversed '%s'. Reason: %s" % (title, reason)),
                            "expect": {k: v["to"] for k, v in changed.items()}})
            preview.append({"account_id": entry["account_id"], "account": names.get(entry["account_id"], entry["account_id"]),
                            "label": "Fields set back",
                            "changes": [{"field": k, "from": v["to"], "to": v["from"]} for k, v in changed.items()]})
        # "already existed, reused" and "already in target state" wrote nothing, so there is nothing to reverse
    return actions, preview


def touched_ids(result, actions):
    ids = set()
    for e in result or []:
        if e.get("account_id"): ids.add(e["account_id"])
    for a in actions or []:
        if a.get("account_id"): ids.add(a["account_id"])
        for v in a.get("fields", {}).values():
            if isinstance(v, str): ids.add(v)
    return ids


def related(rows, pid, result, actions):
    """Other approved changes that touch the same accounts. Undoing one of a linked set can leave the rest inconsistent."""
    mine = touched_ids(result, actions)
    out = []
    for r in rows:
        if r["id"] == pid or r["status"] not in ("applied", "undo_requested"):
            continue
        theirs = touched_ids(json.loads(r["result"]) if r["result"] else [], json.loads(r["actions"]))
        if mine & theirs:
            out.append(r["title"])
    return out
