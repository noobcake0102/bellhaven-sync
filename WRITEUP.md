# Writeup (draft — edit into your own words before submitting)

**Matching approach.** Ownership and names are exactly the things that change in this problem, so I
did not use them as identity. A facility is identified by its normalised street address (suffix and
directional abbreviations collapsed) in the same state, with zip or city agreeing. Name similarity,
phone and the administrator contact are evidence and tie-breakers. A similar name at a different
street is treated as a different facility (Amberly Manor in Colorado, Union Square Senior Living on
Market St, New Carlisle OH vs Carlisle PA). The website is the source of truth for a location's
current name and for whether Bellhaven operates it.

**Choices worth explaining.**
- *Billing SOP.* Any move to a different parent checks revenue and AR. Marietta and Tiffin have both,
  so the old account is untouched, a new one is created under Bellhaven, and the old one's
  `chow_current_account` points to it. The check runs again at approval time, so AR that appears
  between proposal and approval blocks the write.
- *Sandusky.* Still under Bellhaven in the CRM but gone from the website, and Millstone already has an
  account at that address. It has revenue and AR, so I pointed `chow_current_account` at the existing
  Millstone account rather than creating a second one.
- *Duplicates.* When several accounts share a building, the survivor is the one already under
  Bellhaven, then the one corroborated by the website phone or administrator. Losers get
  `duplicate_of_account` and `Inactive`. Kettering had three copies and no signal separating them; the
  tool picks deterministically and flags it medium confidence.
- *Off the website with no successor* (Alliance, Coldwater): `Needs Review` plus a note. I do not know
  the new owner, so I did not guess a parent.
- *Out of scope on purpose:* phone numbers and contacts are shown as evidence but not written.
  Cosmetic street spellings are not rewritten. A PO Box billing address is left alone.

**Review safety.** Each proposal is scored red, yellow or green from a single rules file. Every data
point is coloured website vs CRM, and seven safety rules decide the verdict. Green approves in one
click, yellow needs a confirmation, red needs an override with a written reason that is audited. The
server enforces this, not just the screen. Kettering is the one red case: three records, no signal
to pick a survivor.

**How I used AI.** I used Claude to explore the site and API, write the code, and write the tests,
then checked its work: read the 30 proposals against the raw data by hand, ran an end-to-end test on
a fake CRM (approve everything, re-run, expect zero proposals and 35 clean matches), and reviewed
every proposal in the app before approving. [Add: what you changed, questioned, or rejected.]

**What I'd build next.** Postgres instead of a SQLite file so the scheduler and reviewers share state;
Slack/email digest when the queue is non-empty; let the reviewer pick the survivor on a duplicate;
contact sync (administrator changes); a second ownership source such as CMS change-of-ownership data
so "off the website" can be resolved to a named buyer; auto-approval for a narrow class of
high-confidence, reversible changes once reject rates are known.
