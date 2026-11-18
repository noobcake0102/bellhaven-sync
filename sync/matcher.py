"""Step 2. Match website locations to CRM accounts and decide what should change.

This module is pure logic: lists in, proposals out. It never calls the network
and never writes anything, which is what makes it easy to test and to trust.

THE CORE IDEA
    A facility's name and owner change. Its building does not. So the identity
    of a facility is its normalised street address, and the name is only
    supporting evidence. A name match with a conflicting street address is NOT
    a match (e.g. "Amberly Manor" in Colorado, "Union Square Senior Living" on
    a different street).

EVERY PROPOSAL IS A DICT
    kind        what sort of change (RENAME, REPARENT, CHOW, CREATE, ...)
    key         the identity of the decision, used to avoid re-proposing it
    title/summary/confidence/evidence   what the reviewer sees
    actions     the exact API writes that approval will perform
"""
import re
from difflib import SequenceMatcher

from . import config

# ---------------------------------------------------------------- normalising

STREET_WORDS = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd", "drive": "dr",
    "lane": "ln", "court": "ct", "place": "pl", "highway": "hwy", "parkway": "pkwy",
    "pk": "pike", "circle": "cir", "terrace": "ter", "saint": "st",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
}
NAME_WORDS = {"rehab": "rehabilitation", "centre": "center", "healthcare": "health care", "&": "and"}
PO_BOX = re.compile(r"^\s*p\.?\s*o\.?\s*box\b", re.I)


def norm_street(s):
    """'1250 Northwest Franklin St.' and '1250 NW Franklin Street' -> '1250 nw franklin st'"""
    tokens = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
    return " ".join(STREET_WORDS.get(t, t) for t in tokens)


def norm_name(s):
    s = (s or "").lower().replace("&", " and ")
    tokens = re.sub(r"[^a-z0-9 ]", " ", s).split()
    tokens = [NAME_WORDS.get(t, t) for t in tokens]
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    return " ".join(tokens)


def name_sim(a, b):
    """0..1 similarity of two names after normalising."""
    return round(SequenceMatcher(None, norm_name(a), norm_name(b)).ratio(), 2)


def digits(s):
    return re.sub(r"\D", "", s or "")


def is_physical(street):
    return bool((street or "").strip()) and not PO_BOX.match(street)


# ------------------------------------------------------------ small predicates

def is_retired(a):
    """Already resolved by an earlier run: a duplicate, or a pre-CHOW billing record."""
    return bool(a.get("duplicate_of_account") or a.get("chow_current_account"))


def has_open_billing(a):
    """The SOP test. Revenue history AND money still owed -> billing needs this record untouched."""
    return (a.get("lifetime_revenue") or 0) > 0 and (a.get("outstanding_ar") or 0) > 0


def same_place(loc, a):
    """Address identity: same normalised street in the same state, plus zip OR city agreeing.
    'zip OR city' lets a one-digit zip typo still match, and then get fixed."""
    return (is_physical(a["billing_street"])
            and norm_street(a["billing_street"]) == norm_street(loc["street"])
            and a["billing_state"] == loc["state"]
            and (a["billing_zip"] == loc["zip"] or a["billing_city"].lower() == loc["city"].lower()))


def same_address(a, b):
    return (is_physical(a["billing_street"]) and is_physical(b["billing_street"])
            and norm_street(a["billing_street"]) == norm_street(b["billing_street"])
            and a["billing_state"] == b["billing_state"])


def fallback_match(loc, a):
    """Only for accounts with no usable street (PO Box / blank): same city and state,
    plus a near-identical name or the same phone number."""
    if is_physical(a["billing_street"]):
        return False  # a real, different street is a veto, however similar the name
    if a["billing_state"] != loc["state"] or a["billing_city"].lower() != loc["city"].lower():
        return False
    return name_sim(loc["name"], a["name"]) >= 0.85 or (digits(loc["phone"]) and digits(loc["phone"]) == digits(a["phone"]))


# ------------------------------------------------------------------ the matcher

def build_proposals(locations, accounts, contacts, today):
    """Return (proposals, matches). `matches` are confident no-change links, kept for the audit trail."""
    by_id = {a["account_id"]: a for a in accounts}

    operator = [a for a in accounts if a["name"].startswith(config.OPERATOR_NAME) and not a["parent_id"]]
    if len(operator) != 1:
        raise RuntimeError("Expected exactly one '%s' parent account, found %d" % (config.OPERATOR_NAME, len(operator)))
    op_id, op_name = operator[0]["account_id"], operator[0]["name"]

    parent_ids = {a["parent_id"] for a in accounts if a["parent_id"]} | {op_id}
    facilities = [a for a in accounts if a["account_id"] not in parent_ids and "(Parent Account)" not in a["name"]]
    live = [a for a in facilities if not is_retired(a)]

    contact_names = {}
    for c in contacts:
        if c.get("is_active", True):
            contact_names.setdefault(c["account_id"], set()).add(c["name"].lower())

    tag = "[bellhaven-sync %s] " % today
    proposals, matches, claimed = [], [], set()

    def pname(a):
        return a.get("parent_name") or "no parent"

    ctx = {}   # facts about the current match that the review rules (sync/checks.py) need

    def enrich(loc, involved):
        """Attach contact facts to each account shown as evidence."""
        out = []
        for item in involved:
            names = contact_names.get(item["account"]["account_id"], set())
            out.append(dict(item, n_contacts=len(names),
                            admin_match=bool(loc) and loc["administrator"].lower() in names))
        return out

    def add(kind, key, title, summary, confidence, loc, involved, reasons, actions, account_id=None):
        proposals.append({
            "kind": kind, "key": key, "title": title, "summary": summary, "confidence": confidence,
            "slug": loc["slug"] if loc else None, "account_id": account_id,
            "evidence": {"location": loc, "accounts": enrich(loc, involved), "reasons": reasons,
                         "meta": dict(ctx, operator_id=op_id, operator_name=op_name)},
            "actions": actions,
        })

    def rank(loc, a):
        """Which copy of a facility should survive? Higher tuple wins. Returns (score, reasons)."""
        phone = bool(digits(loc["phone"])) and digits(loc["phone"]) == digits(a["phone"])
        admin = loc["administrator"].lower() in contact_names.get(a["account_id"], set())
        score = (
            a["parent_id"] == op_id,                       # already under the right parent
            has_open_billing(a),                           # live billing should stay on the live record
            phone, admin,                                  # corroborated by the website
            (a.get("lifetime_revenue") or 0) > 0,
            len(contact_names.get(a["account_id"], ())),   # more relationship data attached
            a["status"] == "Active",
            name_sim(loc["name"], a["name"]),
        )
        why = []
        if score[0]: why.append("already under %s" % op_name)
        if score[1]: why.append("has revenue and outstanding AR")
        if phone: why.append("phone matches website")
        if admin: why.append("website administrator %s is a contact" % loc["administrator"])
        if score[5]: why.append("%d contact(s)" % score[5])
        return score, why

    # ---- pass 1: every website location -------------------------------------
    for loc in locations:
        cands = [a for a in live if same_place(loc, a)]
        basis = "address"
        if not cands:
            cands = [a for a in live if fallback_match(loc, a)]
            basis = "name + city (CRM street is not a physical address)"

        near = [a for a in live if a not in cands and (
            (a["billing_city"].lower() == loc["city"].lower() and a["billing_state"] == loc["state"])
            or name_sim(loc["name"], a["name"]) >= 0.9)]
        near_ev = [{"role": "not a match", "account": a,
                    "why": "name similarity %.2f, but street '%s, %s %s' conflicts with the website address"
                           % (name_sim(loc["name"], a["name"]), a["billing_street"], a["billing_city"], a["billing_state"])}
                   for a in near]

        ctx.clear()
        ctx.update(basis=basis, n_at_address=len(cands), near=len(near), clear_winner=True)

        # -- no CRM account at this address -> create one
        if not cands:
            fields = new_account_fields(loc, op_id)
            fields["note"] = tag + "Created from %s. No CRM account existed at this address." % loc["url"]
            reasons = ["No live CRM account at %s, %s %s %s." % (loc["street"], loc["city"], loc["state"], loc["zip"])]
            if near:
                reasons.append("%d similar-looking account(s) were considered and rejected because their street address differs." % len(near))
            add("CREATE", ["CREATE", norm_street(loc["street"]), loc["zip"]],
                "Create account: %s" % loc["name"],
                "On the website, not in the CRM. Create under %s." % op_name,
                "medium" if near else "high", loc, near_ev, reasons,
                [{"op": "create", "fields": fields, "save_as": "new_id"}])
            continue

        ranked = sorted(cands, key=lambda a: (rank(loc, a)[0], a["account_id"]), reverse=True)
        best, losers = ranked[0], ranked[1:]
        best_why = rank(loc, best)[1]
        clear_winner = not losers or rank(loc, best)[0][:6] != rank(loc, losers[0])[0][:6]
        conf = "high" if (basis == "address" and clear_winner) else "medium"
        ctx.update(clear_winner=clear_winner)
        claimed.update(a["account_id"] for a in cands)

        phone_ok = digits(loc["phone"]) == digits(best["phone"])
        reasons = ["Matched on %s." % basis,
                   "Name similarity %.2f." % name_sim(loc["name"], best["name"]),
                   "Phone %s the website." % ("matches" if phone_ok else "differs from")]
        if losers:
            reasons.append("%d CRM accounts share this address. Kept %s because: %s."
                           % (len(cands), best["account_id"],
                              "; ".join(best_why) if (best_why and clear_winner) else
                              "no signal separates them, so this is a deterministic tie-break. Reviewer should sanity-check"))
        involved = [{"role": "matched", "account": best, "why": "; ".join(best_why)}]
        involved += [{"role": "same address", "account": l, "why": ""} for l in losers]

        # -- wrong parent: the SOP decides HOW we move it
        chow_pending = False
        if best["parent_id"] != op_id:
            sop = ("lifetime_revenue=%s, outstanding_ar=%s" % (best["lifetime_revenue"], best["outstanding_ar"]))
            if has_open_billing(best):
                chow_pending = True
                fields = new_account_fields(loc, op_id)
                fields["note"] = tag + "Created for change of ownership. Previous account %s (%s) is preserved for billing." % (best["account_id"], pname(best))
                add("CHOW", ["CHOW", best["account_id"], op_id],
                    "Change of ownership: %s" % loc["name"],
                    "CRM has this facility under %s. It has revenue AND outstanding AR, so the SOP says: leave the old account untouched, "
                    "create a new account under %s, and point the old one at it." % (pname(best), op_name),
                    conf, loc, involved,
                    reasons + ["SOP check: %s -> revenue history AND AR > 0 -> do NOT re-parent." % sop],
                    [{"op": "create", "fields": fields, "save_as": "new_id"},
                     {"op": "patch", "account_id": best["account_id"],
                      "fields": {"chow_current_account": "$new_id"},
                      "expect": {"chow_current_account": "", "parent_id": best["parent_id"]}}],
                    best["account_id"])
            else:
                add("REPARENT", ["REPARENT", best["account_id"], op_id],
                    "Re-parent: %s" % best["name"],
                    "Move from %s to %s." % (pname(best), op_name),
                    conf, loc, involved,
                    reasons + ["SOP check: %s -> not (revenue AND AR > 0) -> safe to re-parent directly." % sop],
                    [{"op": "patch", "account_id": best["account_id"],
                      "fields": {"parent_id": op_id,
                                 "note_append": tag + "Re-parented from %s to %s; facility is listed on the Bellhaven website (%s)." % (pname(best), op_name, loc["url"])},
                      # re-checked at approval time: if billing changed since the proposal, the write is refused
                      "expect": {"parent_id": best["parent_id"], "lifetime_revenue": best["lifetime_revenue"],
                                 "outstanding_ar": best["outstanding_ar"]}}],
                    best["account_id"])

        # -- field fixes on the surviving account (skipped for CHOW: the old record must stay exactly as is)
        fixed = chow_pending
        if not chow_pending:
            if best["name"].strip() != loc["name"]:
                sim = name_sim(loc["name"], best["name"])
                add("RENAME", ["RENAME", best["account_id"], loc["name"]],
                    "Rename: %s -> %s" % (best["name"], loc["name"]),
                    "CRM name is %s." % ("a spelling variant of the website name" if sim >= 0.9 else "outdated; the website now uses a different name"),
                    conf, loc, involved, reasons,
                    [{"op": "patch", "account_id": best["account_id"],
                      "fields": {"name": loc["name"],
                                 "note_append": tag + "Renamed from '%s' to match the Bellhaven website." % best["name"]},
                      "expect": {"name": best["name"]}}],
                    best["account_id"])
                fixed = True

            addr_fix = {}
            if best["billing_zip"] != loc["zip"]: addr_fix["billing_zip"] = loc["zip"]
            if best["billing_city"].lower() != loc["city"].lower(): addr_fix["billing_city"] = loc["city"]
            if addr_fix:
                add("FIX_ADDRESS", ["FIX_ADDRESS", best["account_id"], sorted(addr_fix.items())],
                    "Fix address: %s" % best["name"],
                    "Street matches the website but %s does not." % " and ".join(k.replace("billing_", "") for k in addr_fix),
                    conf, loc, involved, reasons,
                    [{"op": "patch", "account_id": best["account_id"],
                      "fields": dict(addr_fix, note_append=tag + "Corrected %s from the Bellhaven website." % ", ".join(
                          "%s %s -> %s" % (k.replace("billing_", ""), best[k], v) for k, v in addr_fix.items())),
                      "expect": {k: best[k] for k in addr_fix}}],
                    best["account_id"])
                fixed = True

            if best["care_type"] not in loc["care_crm"] and loc["care_crm"]:
                add("FIX_CARE_TYPE", ["FIX_CARE_TYPE", best["account_id"], loc["care_crm"][0]],
                    "Fix care type: %s" % best["name"],
                    "CRM says '%s'; website lists %s." % (best["care_type"], ", ".join(loc["care_site"])),
                    conf, loc, involved, reasons,
                    [{"op": "patch", "account_id": best["account_id"], "fields": {"care_type": loc["care_crm"][0]},
                      "expect": {"care_type": best["care_type"]}}],
                    best["account_id"])
                fixed = True

            if best["status"] != "Active":
                add("REACTIVATE", ["REACTIVATE", best["account_id"]],
                    "Reactivate: %s" % best["name"],
                    "CRM status is '%s' but the facility is listed on the website." % best["status"],
                    conf, loc, involved, reasons,
                    [{"op": "patch", "account_id": best["account_id"],
                      "fields": {"status": "Active", "note_append": tag + "Set Active; listed on the Bellhaven website."},
                      "expect": {"status": best["status"]}}],
                    best["account_id"])
                fixed = True

        if not fixed and best["parent_id"] == op_id:
            matches.append({"slug": loc["slug"], "location": loc, "account": best,
                            "basis": basis, "reasons": reasons,
                            "evidence": {"location": loc, "accounts": enrich(loc, involved[:1]), "reasons": reasons,
                                         "meta": dict(ctx, operator_id=op_id, operator_name=op_name)}})

        # -- the other copies at this address are duplicates of the survivor
        # (if the survivor itself needs a CHOW, wait: next run the new account exists and becomes the survivor)
        if not chow_pending:
            for l in losers:
                dup_involved = [{"role": "survivor", "account": best, "why": "; ".join(best_why)},
                                {"role": "duplicate", "account": l, "why": "same normalised address as the survivor"}]
                if has_open_billing(l):
                    # never deactivate a record billing still needs; link it instead
                    add("CHOW_LINK", ["CHOW_LINK", l["account_id"], best["account_id"]],
                        "Link old-owner record: %s" % l["name"],
                        "Same facility as %s but with open billing, so it is preserved and pointed at the current account." % best["name"],
                        conf, loc, dup_involved, reasons,
                        [{"op": "patch", "account_id": l["account_id"], "fields": {"chow_current_account": best["account_id"]},
                          "expect": {"chow_current_account": ""}}], l["account_id"])
                else:
                    add("DUPLICATE", ["DUPLICATE", l["account_id"], best["account_id"]],
                        "Duplicate: %s (%s)" % (l["name"], pname(l)),
                        "Same building as %s. Mark Inactive and point at the surviving account." % best["name"],
                        conf, loc, dup_involved, reasons,
                        [{"op": "patch", "account_id": l["account_id"],
                          "fields": {"duplicate_of_account": best["account_id"], "status": "Inactive",
                                     "note_append": tag + "Duplicate of %s (%s): same facility at %s. Stale record from a previous name/owner."
                                                    % (best["account_id"], loc["name"], loc["street"])},
                          "expect": {"duplicate_of_account": ""}}], l["account_id"])

    # ---- pass 2: accounts under the operator that the website no longer lists
    for a in live:
        if a["parent_id"] != op_id or a["account_id"] in claimed:
            continue
        successors = [b for b in live if b["account_id"] != a["account_id"] and b["parent_id"] != op_id and same_address(a, b)]
        ctx.clear()
        ctx.update(basis="off website", n_at_address=1, near=0, clear_winner=True, successor=bool(successors))
        base_reason = ["%s is under %s in the CRM but is not on the Bellhaven website (%d locations scraped)." % (a["name"], op_name, len(locations))]
        if successors:
            b = successors[0]
            involved = [{"role": "off website", "account": a, "why": ""},
                        {"role": "current owner's account", "account": b, "why": "same address, under %s" % pname(b)}]
            reasons = base_reason + ["The CRM already has an account at the same address under %s, which points to a sale." % pname(b),
                                     "SOP check: lifetime_revenue=%s, outstanding_ar=%s." % (a["lifetime_revenue"], a["outstanding_ar"])]
            if has_open_billing(a):
                add("CHOW_LINK", ["CHOW_LINK", a["account_id"], b["account_id"]],
                    "Sold: %s -> %s" % (a["name"], pname(b)),
                    "Facility left Bellhaven. Revenue AND outstanding AR, so the old account is left untouched and pointed at the new owner's "
                    "existing account instead of creating a second one.",
                    "high", None, involved, reasons,
                    [{"op": "patch", "account_id": a["account_id"], "fields": {"chow_current_account": b["account_id"]},
                      "expect": {"chow_current_account": "", "parent_id": op_id}}], a["account_id"])
            else:
                add("DUPLICATE", ["DUPLICATE", a["account_id"], b["account_id"]],
                    "Sold: %s -> %s" % (a["name"], pname(b)),
                    "Facility left Bellhaven and the new owner's account already exists. No open billing, so retire this copy.",
                    "high", None, involved, reasons,
                    [{"op": "patch", "account_id": a["account_id"],
                      "fields": {"duplicate_of_account": b["account_id"], "status": "Inactive",
                                 "note_append": tag + "No longer on the Bellhaven website; superseded by %s (%s)." % (b["account_id"], b["name"])},
                      "expect": {"duplicate_of_account": ""}}], a["account_id"])
        elif a["status"] != "Needs Review":
            add("OFF_WEBSITE", ["OFF_WEBSITE", a["account_id"]],
                "No longer on website: %s" % a["name"],
                "Not listed on the website and no successor account found. Flag for a human; we do not know the new owner, so the parent is left alone.",
                "medium", None, [{"role": "off website", "account": a, "why": ""}],
                base_reason + ["No other CRM account shares its address, so there is no evidence of who owns it now (sold, closed, or a website omission)."],
                [{"op": "patch", "account_id": a["account_id"],
                  "fields": {"status": "Needs Review",
                             "note_append": tag + "Not listed on the Bellhaven website. Possible sale or closure; confirm ownership before outreach."},
                  "expect": {"status": a["status"]}}], a["account_id"])

    return proposals, matches


def new_account_fields(loc, parent_id):
    return {
        "name": loc["name"], "parent_id": parent_id,
        "billing_street": loc["street"], "billing_city": loc["city"],
        "billing_state": loc["state"], "billing_zip": loc["zip"],
        "care_type": loc["care_crm"][0] if loc["care_crm"] else "",
        "status": "Active", "phone": loc["phone"],
    }
