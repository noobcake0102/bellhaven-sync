"""Run with:  python -m pytest -q      (no network: uses a saved snapshot and a fake CRM)"""
import copy
import json
from pathlib import Path

import pytest

from sync import config, store
from sync.apply import Conflict, apply_proposal
from sync.matcher import build_proposals, has_open_billing, name_sim, norm_street

FIX = Path(__file__).parent / "fixtures"
load = lambda n: json.loads((FIX / n).read_text())


class FakeCRM:
    """In-memory stand-in for the CRM API, so the write path can be tested safely."""
    def __init__(self):
        self.a = {x["account_id"]: x for x in load("accounts.json")}
        self.writes = 0
    def accounts(self): return copy.deepcopy(list(self.a.values()))
    def contacts(self): return load("contacts.json")
    def get_account(self, i): return copy.deepcopy(self.a[i])
    def update_account(self, i, f):
        self.a[i].update(f); self.writes += 1
        if "parent_id" in f: self.a[i]["parent_name"] = self.a[f["parent_id"]]["name"] if f["parent_id"] in self.a else ""
        return self.a[i]
    def create_account(self, f):
        i = "001NEW%04d" % len(self.a); self.writes += 1
        base = dict(account_id=i, parent_name=self.a[f["parent_id"]]["name"], lifetime_revenue=0, outstanding_ar=0,
                    chow_current_account="", duplicate_of_account="", note="", created_by_candidate=True)
        self.a[i] = dict(base, **f)
        return self.a[i]


def proposals_for(crm):
    return build_proposals(load("locations.json"), crm.accounts(), crm.contacts(), "2026-11-16")


def by_kind(props, kind):
    return [p for p in props if p["kind"] == kind]


# ---- normalisation -------------------------------------------------------
def test_street_normalisation():
    assert norm_street("1250 Northwest Franklin St") == norm_street("1250 NW Franklin Street")
    assert norm_street("199 Barks Road West") == norm_street("199 Barks Rd W")
    assert norm_street("3313 Wilmington Pk") == norm_street("3313 Wilmington Pike")
    assert norm_street("150 River St") != norm_street("150 River Rd")

def test_name_similarity():
    assert name_sim("Bellhaven Rehab and Nursing of Grove City", "Bellhaven Rehabilitation & Nursing of Grove City") == 1.0
    assert name_sim("Sunny Acres Retirement Home", "Bellhaven Willow Creek") < 0.5

def test_sop_predicate():
    assert has_open_billing({"lifetime_revenue": 100, "outstanding_ar": 1})
    assert not has_open_billing({"lifetime_revenue": 100, "outstanding_ar": 0})
    assert not has_open_billing({"lifetime_revenue": 0, "outstanding_ar": 50})


# ---- matching decisions on the real snapshot ------------------------------
def test_scrape_snapshot_has_every_location_once():
    locs = load("locations.json")
    assert len(locs) == 35 and len({l["slug"] for l in locs}) == 35
    assert any(l["slug"] == "bellhaven-meadows-of-findlay" for l in locs)   # only linked from the home page

def test_name_match_with_wrong_address_is_not_a_match():
    props, _ = proposals_for(FakeCRM())
    created = {p["evidence"]["location"]["name"] for p in by_kind(props, "CREATE")}
    assert created == {"Amberly Manor", "Bellhaven at Union Square", "Bellhaven of Batavia", "Bellhaven of Carlisle"}

def test_sop_chow_vs_direct_reparent():
    props, _ = proposals_for(FakeCRM())
    assert {p["evidence"]["location"]["city"] for p in by_kind(props, "CHOW")} == {"Marietta", "Tiffin"}       # revenue AND AR
    assert {p["evidence"]["location"]["city"] for p in by_kind(props, "REPARENT")} == {"Lima", "Findlay", "Zanesville", "Kettering"}
    for p in by_kind(props, "CHOW"):       # old account: only the CHOW pointer is touched
        assert p["actions"][1]["fields"] == {"chow_current_account": "$new_id"}

def test_sold_facility_links_to_existing_new_owner_account():
    props, _ = proposals_for(FakeCRM())
    link = by_kind(props, "CHOW_LINK")
    assert len(link) == 1 and "Sandusky" in link[0]["title"]
    assert [a["op"] for a in link[0]["actions"]] == ["patch"]            # no second account created

def test_off_website_without_successor_goes_to_needs_review():
    props, _ = proposals_for(FakeCRM())
    assert {p["actions"][0]["fields"]["status"] for p in by_kind(props, "OFF_WEBSITE")} == {"Needs Review"}
    assert len(by_kind(props, "OFF_WEBSITE")) == 2


# ---- applying and re-running ----------------------------------------------
def test_approve_everything_then_rerun_proposes_nothing():
    crm = FakeCRM()
    props, _ = proposals_for(crm)
    for p in props:
        apply_proposal(crm, p["actions"])
    again, matches = proposals_for(crm)
    assert again == []                       # the CRM now agrees with the website
    assert len(matches) == 35                # every location has exactly one clean account

def test_applying_twice_writes_nothing_the_second_time():
    crm = FakeCRM()
    props, _ = proposals_for(crm)
    for p in props: apply_proposal(crm, p["actions"])
    before = crm.writes
    for p in props: apply_proposal(crm, p["actions"])
    assert crm.writes == before

def test_reparent_is_refused_if_billing_changed_after_proposal():
    crm = FakeCRM()
    props, _ = proposals_for(crm)
    lima = [p for p in by_kind(props, "REPARENT") if "Lima" in p["title"]][0]
    crm.a[lima["account_id"]]["outstanding_ar"] = 500      # AR appears between proposal and approval
    with pytest.raises(Conflict):
        apply_proposal(crm, lima["actions"])
    assert crm.writes == 0

def test_rejected_proposals_are_not_requeued(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db, crm = store.connect(), FakeCRM()
    props, matches = proposals_for(crm)
    first = store.save_run(db, [], crm.accounts(), props, matches)
    assert first["new"] == len(props)
    for row in db.execute("SELECT id FROM proposals").fetchall():
        store.decide(db, row["id"], "rejected", "test")
    second = store.save_run(db, [], crm.accounts(), props, matches)
    assert second["new"] == 0 and second["skipped_decided"] == len(props)
    assert db.execute("SELECT COUNT(*) FROM proposals WHERE status='pending'").fetchone()[0] == 0


# ---- red / yellow / green rules and the approval gate -----------------------
from sync import checks


def verdicts():
    props, _ = proposals_for(FakeCRM())
    return {p["title"]: checks.evaluate(p["kind"], p["evidence"], p["actions"]) for p in props}

def test_field_checks_colour_each_data_point():
    v = verdicts()
    zipfix = v["Fix address: Bellhaven of Portsmouth"]["accounts"][0]["checks"]
    level = {c["field"]: c["level"] for c in zipfix}
    assert level["Zip"] == "red" and level["Street"] == "green" and level["City"] == "green"

def test_verdicts_follow_the_rules():
    v = verdicts()
    assert v["Re-parent: Bellhaven Crossings of Lima"]["verdict"] == "green"
    assert v["Fix address: Bellhaven of Portsmouth"]["verdict"] == "yellow"            # zip disagrees
    assert v["Create account: Bellhaven at Union Square"]["verdict"] == "yellow"       # look-alike + cannot be deleted
    assert {t for t, e in v.items() if e["verdict"] == "red"} == {t for t in v if "Kettering" in t}   # arbitrary survivor

def test_billing_rule_goes_red_if_a_protected_account_would_change():
    props, _ = proposals_for(FakeCRM())
    chow = by_kind(props, "CHOW")[0]
    bad = [{"op": "patch", "account_id": chow["account_id"], "fields": {"parent_id": "X"}}]     # a re-parent the SOP forbids
    ev = checks.evaluate("REPARENT", chow["evidence"], bad)
    assert ev["verdict"] == "red" and any(r["id"] == "billing" and r["level"] == "red" for r in ev["rules"])

def test_server_refuses_yellow_without_confirm_and_red_without_override(tmp_path, monkeypatch):
    import app as webapp
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    crm = FakeCRM()
    monkeypatch.setattr(webapp, "CRM", lambda: crm)
    props, matches = proposals_for(crm)
    store.save_run(store.connect(), load("locations.json"), crm.accounts(), props, matches)
    client = webapp.app.test_client()
    state = client.get("/api/state").get_json()
    pick = lambda v: next(p for p in state["open"] if p["verdict"] == v)
    yellow, red, green = pick("yellow"), pick("red"), pick("green")

    assert client.post("/api/proposals/%d/approve" % yellow["id"], json={}).status_code == 409
    assert client.post("/api/proposals/%d/approve" % red["id"], json={"confirm": True}).status_code == 409
    assert client.post("/api/proposals/%d/approve" % red["id"], json={"override": True, "reason": "ok"}).status_code == 409   # reason too short
    assert crm.writes == 0                                                    # nothing reached the CRM

    assert client.post("/api/proposals/%d/approve" % green["id"], json={}).get_json()["ok"]
    assert client.post("/api/proposals/%d/approve" % yellow["id"], json={"confirm": True}).get_json()["ok"]
    assert client.post("/api/proposals/%d/approve" % red["id"], json={"override": True, "reason": "Confirmed survivor with corporate office"}).get_json()["ok"]
    audit = client.get("/api/state").get_json()["audit"]
    assert any(a["event"] == "override" and "corporate office" in a["detail"] for a in audit)


# ---- undo: the reverse of an approved change ---------------------------------
from sync import undo


def _without_note(a):
    return {k: v for k, v in a.items() if k != "note"}


def test_every_kind_of_change_can_be_undone_and_the_crm_returns_to_how_it_was():
    crm = FakeCRM()
    props, _ = proposals_for(crm)
    for p in props:
        before = {i: _without_note(a) for i, a in crm.a.items()}
        result = apply_proposal(crm, p["actions"])
        actions, preview = undo.plan(result, p["title"], "testing the reversal", "2026-11-17", p["evidence"])
        assert actions and preview, p["title"]                       # every approval wrote something, so it can be reversed
        apply_proposal(crm, actions)
        for i, was in before.items():                                 # existing accounts: every field except the note is back
            assert _without_note(crm.a[i]) == was, (p["title"], i)
        for i in set(crm.a) - set(before):                            # created accounts cannot be deleted, so they are Inactive
            assert crm.a[i]["status"] == "Inactive"
        # the history is kept: a dated "Reversed" or "Deactivated" note exists on something we touched
        assert any("testing the reversal" in (crm.a[x["account_id"]].get("note") or "") for x in actions)

def test_undo_is_refused_if_the_crm_changed_after_approval():
    crm = FakeCRM()
    props, _ = proposals_for(crm)
    rename = by_kind(props, "RENAME")[0]
    result = apply_proposal(crm, rename["actions"])
    crm.a[rename["account_id"]]["name"] = "Somebody edited this by hand"
    actions, _ = undo.plan(result, rename["title"], "undo please", "2026-11-17", rename["evidence"])
    writes = crm.writes
    with pytest.raises(Conflict):
        apply_proposal(crm, actions)
    assert crm.writes == writes

def test_undo_keeps_earlier_notes_instead_of_restoring_an_old_copy():
    crm = FakeCRM()
    props, _ = proposals_for(crm)
    p = by_kind(props, "RENAME")[0]
    result = apply_proposal(crm, p["actions"])
    crm.a[p["account_id"]]["note"] += "\nCall made by a person after the rename."
    actions, _ = undo.plan(result, p["title"], "undo please", "2026-11-17", p["evidence"])
    apply_proposal(crm, actions)
    note = crm.a[p["account_id"]]["note"]
    assert "Call made by a person" in note and "Renamed from" in note and "Reversed" in note

def test_reversed_proposal_is_not_requeued_by_the_next_run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    db, crm = store.connect(), FakeCRM()
    props, matches = proposals_for(crm)
    store.save_run(db, [], crm.accounts(), props, matches)
    pid = db.execute("SELECT id FROM proposals WHERE kind='RENAME' LIMIT 1").fetchone()["id"]
    store.set_status(db, pid, "reversed", "test", "undo_applied")
    again = store.save_run(db, [], crm.accounts(), props, matches)
    assert again["new"] == 0
    assert db.execute("SELECT status FROM proposals WHERE id=?", (pid,)).fetchone()["status"] == "reversed"

def test_server_enforces_two_steps_a_reason_and_a_typed_confirmation(tmp_path, monkeypatch):
    import app as webapp
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    crm = FakeCRM()
    monkeypatch.setattr(webapp, "CRM", lambda: crm)
    props, matches = proposals_for(crm)
    store.save_run(store.connect(), load("locations.json"), crm.accounts(), props, matches)
    c = webapp.app.test_client()
    green = next(p for p in c.get("/api/state").get_json()["open"] if p["verdict"] == "green" and p["kind"] == "RENAME")
    pid = green["id"]
    original = crm.a[green["accounts"][0]["account"]["account_id"]]["name"]

    # cannot undo something that was never approved
    assert c.post("/api/proposals/%d/undo/request" % pid, json={"reason": "a long enough reason"}).status_code == 409
    assert c.post("/api/proposals/%d/approve" % pid, json={}).get_json()["ok"]
    writes = crm.writes

    # step 2 cannot be used first, and step 1 needs a real reason
    assert c.post("/api/proposals/%d/undo/confirm" % pid, json={"confirm_text": "UNDO", "ack": True}).status_code == 409
    assert c.post("/api/proposals/%d/undo/request" % pid, json={"reason": "no"}).status_code == 409
    assert crm.writes == writes

    # step 1: filed, but nothing is written yet
    assert c.post("/api/proposals/%d/undo/request" % pid, json={"reason": "Wrong facility: confirmed with the owner"}).get_json()["ok"]
    assert crm.writes == writes
    item = next(p for p in c.get("/api/state").get_json()["decided"] if p["id"] == pid)
    assert item["status"] == "undo_requested" and "Wrong facility" in item["undo"]["reason"]

    # step 2 needs the typed word and the tick
    assert c.post("/api/proposals/%d/undo/confirm" % pid, json={"confirm_text": "yes", "ack": True}).status_code == 409
    assert c.post("/api/proposals/%d/undo/confirm" % pid, json={"confirm_text": "UNDO", "ack": False}).status_code == 409
    assert crm.writes == writes
    assert c.post("/api/proposals/%d/undo/confirm" % pid, json={"confirm_text": "UNDO", "ack": True}).get_json()["ok"]
    assert crm.a[green["accounts"][0]["account"]["account_id"]]["name"] == original

    state = c.get("/api/state").get_json()
    assert next(p for p in state["decided"] if p["id"] == pid)["status"] == "reversed"
    assert [a["event"] for a in reversed(state["audit"]) if a["proposal_id"] == pid][-3:] == ["applied", "undo_requested", "undo_applied"]

    # reversed items can go back to review, and a cancelled request leaves the change alone
    assert c.post("/api/proposals/%d/reopen" % pid, json={}).get_json()["ok"]
    assert c.post("/api/proposals/%d/approve" % pid, json={}).get_json()["ok"]
    assert c.post("/api/proposals/%d/undo/request" % pid, json={"reason": "second thoughts about this"}).get_json()["ok"]
    assert c.post("/api/proposals/%d/undo/cancel" % pid, json={}).get_json()["ok"]
    assert next(p for p in c.get("/api/state").get_json()["decided"] if p["id"] == pid)["status"] == "applied"
