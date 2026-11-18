"""The review rules: red / yellow / green.

Two layers, both computed from the evidence stored with a proposal:

  FIELD CHECKS   one colour per data point, website vs CRM (street, city, zip, ...)
  SAFETY RULES   a handful of predefined rules about the change as a whole

The verdict is the worst colour among the SAFETY RULES. Field checks do not
set the verdict directly, because a red field is often the very thing being
fixed (a wrong zip, an outdated name). They feed the rules instead.

  green   rules passed            -> one click to approve
  yellow  check before approving  -> reviewer must confirm in a dialog
  red     rules advise against    -> reviewer must tick an override and type a reason

The review app enforces this on the server, so it is a control, not a hint.
To change a rule, change it here: the app and the Rules tab read this file.
"""
from .matcher import digits, has_open_billing, is_physical, name_sim, norm_street

GREEN, YELLOW, RED, NA = "green", "yellow", "red", "na"
RANK = {NA: 0, GREEN: 1, YELLOW: 2, RED: 3}

NAME_VARIANT = 0.9       # at or above: same name, different spelling
MIN_OVERRIDE_REASON = 10  # characters a reviewer must type to override a red verdict

# ---- shown on the Rules tab -------------------------------------------------
FIELD_RULES = [
    {"field": "Street", "green": "Same after tidying abbreviations (St/Street, NW/Northwest)", "yellow": "CRM street is a PO Box or blank", "red": "Different street"},
    {"field": "City", "green": "Same", "yellow": "", "red": "Different"},
    {"field": "State", "green": "Same", "yellow": "", "red": "Different"},
    {"field": "Zip", "green": "Same", "yellow": "", "red": "Different"},
    {"field": "Name", "green": "Identical", "yellow": "Spelling variant (similarity %.0f%% or more)" % (NAME_VARIANT * 100), "red": "Different name"},
    {"field": "Care type", "green": "CRM value is one of the website's offerings", "yellow": "", "red": "Not offered on the website"},
    {"field": "Phone", "green": "Same", "yellow": "Different (phone is never written by this tool)", "red": ""},
    {"field": "Administrator", "green": "Website administrator is a contact on the account", "yellow": "Not among the account's contacts, or no contacts", "red": ""},
    {"field": "Parent", "green": "Under the operator's parent account", "yellow": "No parent", "red": "Under a different parent"},
    {"field": "Status", "green": "Active", "yellow": "Needs Review", "red": "Inactive"},
]
SAFETY_RULES = [
    {"id": "identity", "label": "Same building", "green": "Street, city, state and zip all agree", "yellow": "Street agrees but zip or city does not, or the CRM has no physical street", "red": "Street or state disagrees"},
    {"id": "second_signal", "label": "Second signal", "green": "Name, phone or administrator also agrees", "yellow": "Matched on address alone", "red": ""},
    {"id": "one_record", "label": "One record per building", "green": "Only one live CRM account at this address", "yellow": "Several accounts, with a clear survivor", "red": "Several accounts and nothing separates them"},
    {"id": "billing", "label": "Billing SOP", "green": "Complies: an account with revenue and outstanding AR is never re-parented or deactivated", "yellow": "", "red": "Would move or retire an account billing still needs"},
    {"id": "lookalike", "label": "No look-alike account", "green": "No similar account elsewhere", "yellow": "A similar account exists at a different address", "red": ""},
    {"id": "source", "label": "Evidence of ownership", "green": "Listed on the website, or a successor account exists", "yellow": "Only evidence is absence from the website", "red": ""},
    {"id": "reversible", "label": "Can be undone", "green": "A field change that can be changed back", "yellow": "Creates an account, and the API has no delete", "red": ""},
]


def check(field, website, crm, level, note=""):
    return {"field": field, "website": website, "crm": crm, "level": level, "note": note}


def field_checks(loc, acct, item, meta):
    """One coloured check per data point for one CRM account."""
    out = []
    if loc:
        st = acct["billing_street"]
        if not is_physical(st):
            out.append(check("Street", loc["street"], st or "(blank)", YELLOW, "Not a physical address"))
        elif norm_street(st) == norm_street(loc["street"]):
            out.append(check("Street", loc["street"], st, GREEN, "Identical" if st == loc["street"] else "Same after tidying"))
        else:
            out.append(check("Street", loc["street"], st, RED, "Different street"))

        for label, wk, ck in (("City", "city", "billing_city"), ("State", "state", "billing_state"), ("Zip", "zip", "billing_zip")):
            same = str(acct[ck]).strip().lower() == str(loc[wk]).strip().lower()
            out.append(check(label, loc[wk], acct[ck], GREEN if same else RED, "Same" if same else "Different"))

        sim = name_sim(loc["name"], acct["name"])
        if acct["name"].strip() == loc["name"]:
            out.append(check("Name", loc["name"], acct["name"], GREEN, "Identical"))
        elif sim >= NAME_VARIANT:
            out.append(check("Name", loc["name"], acct["name"], YELLOW, "Spelling variant, %d%% similar" % (sim * 100)))
        else:
            out.append(check("Name", loc["name"], acct["name"], RED, "Different name, %d%% similar" % (sim * 100)))

        care_ok = acct["care_type"] in loc["care_crm"]
        out.append(check("Care type", ", ".join(loc["care_crm"]), acct["care_type"] or "(blank)", GREEN if care_ok else RED,
                         "Offered on the website" if care_ok else "Not on the website"))

        phone_ok = bool(digits(loc["phone"])) and digits(loc["phone"]) == digits(acct["phone"])
        out.append(check("Phone", loc["phone"], acct["phone"], GREEN if phone_ok else YELLOW, "Same" if phone_ok else "Different (not written)"))

        if item.get("admin_match"):
            out.append(check("Administrator", loc["administrator"], "is a contact", GREEN, "On the account"))
        else:
            n = item.get("n_contacts", 0)
            out.append(check("Administrator", loc["administrator"], "%d contact(s)" % n, YELLOW,
                             "Not among its contacts" if n else "No contacts to compare"))

    op = meta.get("operator_id")
    if acct["parent_id"] == op:
        out.append(check("Parent", meta.get("operator_name", ""), acct["parent_name"], GREEN, "Operator's parent"))
    elif not acct["parent_id"]:
        out.append(check("Parent", meta.get("operator_name", ""), "(none)", YELLOW, "No parent"))
    else:
        out.append(check("Parent", meta.get("operator_name", ""), acct["parent_name"], RED, "Different parent"))

    level = {"Active": GREEN, "Needs Review": YELLOW}.get(acct["status"], RED)
    out.append(check("Status", "Active" if loc else "", acct["status"], level, acct["status"]))
    return out


def _level(checks, field):
    return next((c["level"] for c in checks if c["field"] == field), NA)


def evaluate(kind, evidence, actions):
    """Return {"accounts": [...with checks], "rules": [...], "verdict": colour, "cautions": [...]}."""
    loc, meta = evidence.get("location"), evidence.get("meta", {})
    accounts = [dict(item, checks=field_checks(loc, item["account"], item, meta)) for item in evidence.get("accounts", [])]
    main = next((a for a in accounts if a["role"] in ("matched", "survivor")), None)
    target = next((a for a in accounts if a["role"] in ("duplicate", "off website")), main)
    rules = []

    def rule(rid, level, note):
        label = next(r["label"] for r in SAFETY_RULES if r["id"] == rid)
        rules.append({"id": rid, "label": label, "level": level, "note": note})

    # -- same building
    if main and loc:
        c = main["checks"]
        if _level(c, "Street") == RED or _level(c, "State") == RED:
            rule("identity", RED, "Street or state disagrees with the website")
        elif _level(c, "Street") == YELLOW:
            rule("identity", YELLOW, "CRM has no physical street; matched on name and city")
        elif RED in (_level(c, "Zip"), _level(c, "City")):
            rule("identity", YELLOW, "Street agrees, but zip or city differs")
        else:
            rule("identity", GREEN, "Street, city, state and zip all agree")
        signals = [f for f in ("Name", "Phone", "Administrator") if _level(c, f) == GREEN or (f == "Name" and _level(c, f) == YELLOW)]
        rule("second_signal", GREEN if signals else YELLOW,
             ("%s also agree%s" % (", ".join(signals).lower(), "s" if len(signals) == 1 else "")) if signals else "Nothing but the address ties these together")

    # -- one record per building
    n = meta.get("n_at_address", 1)
    if kind != "CREATE" and loc:
        if n <= 1:
            rule("one_record", GREEN, "Only one live account at this address")
        elif meta.get("clear_winner", True):
            rule("one_record", YELLOW, "%d accounts share this address; the survivor is clear" % n)
        else:
            rule("one_record", RED, "%d accounts share this address and nothing separates them; the survivor was a tie-break" % n)

    # -- billing SOP (re-derived here, independent of the matcher, as a second check)
    patched = [a for a in actions if a["op"] == "patch"]
    by_id = {a["account"]["account_id"]: a["account"] for a in accounts}
    violations = []
    for act in patched:
        acct = by_id.get(act["account_id"])
        if acct and has_open_billing(acct):
            touched = set(act["fields"]) - {"chow_current_account"}
            if touched:
                violations.append("%s has revenue and outstanding AR but %s would change" % (acct["name"], ", ".join(sorted(touched))))
    if violations:
        rule("billing", RED, "; ".join(violations))
    elif kind in ("REPARENT", "CHOW", "CHOW_LINK", "DUPLICATE"):
        t = (target or main or {}).get("account", {})
        rule("billing", GREEN, "Open billing, so the old record is preserved and linked" if kind in ("CHOW", "CHOW_LINK")
             else "No open billing on %s (revenue $%s, AR $%s)" % (t.get("name", "the account"), "{:,.0f}".format(t.get("lifetime_revenue") or 0), "{:,.0f}".format(t.get("outstanding_ar") or 0)))

    # -- look-alikes, evidence, reversibility
    if kind == "CREATE":
        near = meta.get("near", 0)
        rule("lookalike", YELLOW if near else GREEN,
             "%d similar account(s) exist at a different address; confirm it is a different building" % near if near else "No similar account in the CRM")
    if kind == "OFF_WEBSITE":
        rule("source", YELLOW, "Missing from the website and no successor account; could be a sale, a closure or a website omission")
    elif kind in ("CHOW_LINK", "DUPLICATE") and not loc:
        rule("source", GREEN, "Another parent already has an account at this address")
    creates = any(a["op"] == "create" for a in actions)
    rule("reversible", YELLOW if creates else GREEN,
         "Creates an account; the API cannot delete it, only deactivate" if creates else "Field change; can be set back")

    verdict = max((r["level"] for r in rules), key=lambda l: RANK[l], default=GREEN)
    cautions = [r for r in rules if r["level"] in (YELLOW, RED)]
    return {"accounts": accounts, "rules": rules, "verdict": verdict, "cautions": cautions}
