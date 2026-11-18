# bellhaven-sync

Keeps the CRM's picture of **Bellhaven Senior Living** in line with Bellhaven's public website:
which facilities exist, what they are called, and which parent account owns them.

```
website ──scrape──┐
                  ├──► matcher ──► proposals (SQLite queue) ──► review app ──approve──► CRM API
CRM API ──read────┘                                                  └─reject──► remembered, never re-proposed
```

Nothing is written to the CRM without a reviewer clicking **Approve**.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # then paste your CRM token into .env

python -m pytest -q          # 12 tests, no network needed
python pipeline.py --dry-run # print proposals, save nothing
python pipeline.py           # queue proposals
python app.py                # review at http://127.0.0.1:5000
```

The review screen is a React app that is already built into `static/dist`, so Python is all you
need to run it. To change the screen itself: `cd frontend && npm install && npm run build`.

## Layout

| File | Job |
|---|---|
| `sync/scraper.py` | Crawl the website; return one dict per location |
| `sync/crm.py` | The only code that talks to the CRM API |
| `sync/matcher.py` | Pure logic: locations + accounts in, proposals out |
| `sync/store.py` | SQLite queue, decisions, audit log; makes re-runs safe |
| `sync/apply.py` | Writes one approved proposal, with precondition and verify checks |
| `sync/undo.py` | Builds the reverse of an approved change from what it recorded writing |
| `pipeline.py` | The daily job (read-only against the CRM) |
| `sync/checks.py` | The red / yellow / green rules. One place to change a rule |
| `app.py` | Review app: JSON API, and the server-side approval gate |
| `frontend/` | React source for the review screen (21st.dev components: Status, Alert Dialog, Animated Tabs, Stat Card) |
| `static/dist/` | The built screen that Flask serves |
| `crontab.txt`, `.github/workflows/daily-sync.yml` | Schedule |
| `tests/` | Unit tests plus an end-to-end run against a fake CRM |

## How matching works

A facility's name and owner change; its building does not. Identity is therefore the
**normalised street address** (`1250 Northwest Franklin St` = `1250 NW Franklin Street`) in the same
state, with zip or city agreeing. Name similarity, phone and the administrator contact are supporting
evidence and tie-breakers. A similar name at a different street is explicitly *not* a match.

| Finding | Proposal | Write on approval |
|---|---|---|
| Location has no account at its address | `CREATE` | New account under Bellhaven |
| Matched, wrong parent, no (revenue AND AR) | `REPARENT` | `parent_id` → Bellhaven |
| Matched, wrong parent, revenue AND AR > 0 | `CHOW` | Old account untouched; new account created; old `chow_current_account` → new id |
| Matched, name differs from website | `RENAME` | `name`, old name kept in `note` |
| Matched, zip/city wrong | `FIX_ADDRESS` | corrected field |
| Several accounts at one address | `DUPLICATE` | losers: `duplicate_of_account` → survivor, `Inactive` |
| Under Bellhaven, off the website, new owner's account exists | `CHOW_LINK` or `DUPLICATE` | pointer to the new owner's account (which one depends on the billing SOP) |
| Under Bellhaven, off the website, no successor | `OFF_WEBSITE` | `Needs Review` + note |

## Red, yellow, green

Every proposal is scored by `sync/checks.py` before a reviewer can approve it.

- **Data point checks** colour each field, website vs CRM: street, city, state, zip, name, care type,
  phone, administrator, parent, status. A different zip or city is red; a street that matches after
  tidying is green.
- **Safety rules** judge the change as a whole: same building, second signal, one record per building,
  billing SOP, no look-alike account, evidence of ownership, can be undone.

The verdict is the worst colour among the safety rules. A red data point alone does not block a
change, because it is often the thing being fixed (a wrong zip, an old name).

| Verdict | Meaning | To approve |
|---|---|---|
| Green | Every safety rule passed | One click |
| Yellow | At least one caution | Confirm in a dialog that lists each caution and the exact write |
| Red | A rule advises against it | Tick an override and type a reason, which is saved to the audit log |

The gate is enforced in `app.py` on the server, so it cannot be skipped from the browser. The Rules
tab in the app shows the full rule table, read from the same file.

## Why re-runs are safe

### Undoing an approved change

Approved items in the **Decided** tab have an **Undo this change** button. It is two steps, enforced by the server:

1. **Request**: a written reason (10+ characters). Nothing is written to the CRM.
2. **Confirm**: a separate request with the word `UNDO` typed and an acknowledgement. This is the write.

The reversal is built from what the approval recorded writing, so nothing is guessed. Fields go back to their old values;
an account the change *created* is set Inactive (the API has no delete); notes are never overwritten, a dated "Reversed"
note is added. If anyone changed the fields since, the app refuses and writes nothing. A reversed item is not proposed
again on its own; **Send back to review** puts it in the queue to decide again. Every step is in the audit log.

---

1. Every proposal has a fingerprint of *what is being decided*; the column is UNIQUE. Approved and
   rejected fingerprints are never queued again.
2. Approved changes fix the CRM, so the next run simply no longer finds the problem.
3. Accounts already marked duplicate or CHOW'd are excluded from matching.
4. At approval time the app re-reads the account. If it changed since the proposal (including revenue
   or AR on a re-parent), nothing is written and the next run re-evaluates.
5. A create first checks for an existing account at that address under that parent.
6. If a scrape returns under 70% of the previous run's locations, the run aborts.
