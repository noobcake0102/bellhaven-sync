"""Step 3b. Write ONE approved proposal to the CRM.

This is the only code path that changes the CRM, and it is only ever called
from the review app's Approve button. Each write is wrapped in three checks:

  1. PRECONDITIONS  Re-read the account and confirm it still looks the way it
                    did when the proposal was made (`expect`). For a re-parent
                    that includes revenue and AR, so the billing SOP is enforced
                    at the moment of writing, not just when the proposal was built.
  2. IDEMPOTENCE    If the CRM already has the target values, do nothing. A
                    create first looks for an account already at that address
                    under that parent, so a retry cannot create a second copy.
  3. VERIFY         Re-read after writing and confirm the change landed.
"""
from .crm import CRMError
from .matcher import norm_street


class Conflict(Exception):
    """The CRM changed since the proposal was made. Nothing was written."""


def apply_proposal(crm, actions):
    """Run a proposal's actions in order. Returns a list of what happened."""
    log, saved = [], {}
    for act in actions:
        fields = {k: (saved[v[1:]] if isinstance(v, str) and v.startswith("$") else v)
                  for k, v in act["fields"].items()}

        if act["op"] == "create":
            existing = [a for a in crm.accounts()
                        if a["parent_id"] == fields["parent_id"]
                        and a["billing_state"] == fields["billing_state"]
                        and norm_street(a["billing_street"]) == norm_street(fields["billing_street"])
                        and not a.get("duplicate_of_account") and not a.get("chow_current_account")]
            if existing:
                acct = existing[0]
                log.append({"op": "create", "account_id": acct["account_id"], "result": "already existed, reused"})
            else:
                acct = crm.create_account(fields)
                log.append({"op": "create", "account_id": acct["account_id"], "result": "created", "fields": fields})
            saved[act.get("save_as", "new_id")] = acct["account_id"]
            continue

        # ---- patch
        acct_id = act["account_id"]
        current = crm.get_account(acct_id)

        note_add = fields.pop("note_append", None)
        if note_add and note_add not in (current.get("note") or ""):
            fields["note"] = ((current.get("note") or "") + "\n" + note_add).strip()

        todo = {k: v for k, v in fields.items() if current.get(k) != v}
        if not [k for k in todo if k != "note"]:
            log.append({"op": "patch", "account_id": acct_id, "result": "already in target state, nothing written"})
            continue

        for k, expected in act.get("expect", {}).items():
            if current.get(k) != expected:
                raise Conflict("%s.%s is now %r, but the proposal was built when it was %r. "
                               "Nothing written; the next pipeline run will re-evaluate."
                               % (acct_id, k, current.get(k), expected))

        crm.update_account(acct_id, todo)

        after = crm.get_account(acct_id)
        bad = {k: after.get(k) for k, v in todo.items() if after.get(k) != v}
        if bad:
            raise CRMError("Write to %s did not stick for %s" % (acct_id, bad))
        log.append({"op": "patch", "account_id": acct_id, "result": "updated",
                    "changed": {k: {"from": current.get(k), "to": v} for k, v in todo.items()}})
    return log
