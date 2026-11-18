"""The daily job:  scrape website -> read CRM -> match -> queue proposals.

    python pipeline.py            # normal run
    python pipeline.py --dry-run  # print what it would propose, save nothing

It only READS the CRM. Writes happen exclusively in the review app, on approval.
"""
import sys
from datetime import date

from sync import config, store
from sync.crm import CRM
from sync.matcher import build_proposals
from sync.scraper import scrape


def run(dry_run=False):
    locations = scrape()
    crm = CRM()
    accounts, contacts = crm.accounts(), crm.contacts()

    db = store.connect()
    previous = store.last_location_count(db)
    if not locations or (previous and len(locations) < previous * config.MIN_SCRAPE_RATIO):
        raise SystemExit("ABORT: scraped %d locations (previous run: %s). The website or the parser "
                         "probably changed. Refusing to propose changes from a bad scrape." % (len(locations), previous))

    proposals, matches = build_proposals(locations, accounts, contacts, date.today().isoformat())

    if dry_run:
        for p in proposals:
            print("%-13s %-6s %s" % (p["kind"], p["confidence"], p["title"]))
        print("\n%d locations, %d accounts -> %d proposals, %d confident matches (dry run, nothing saved)"
              % (len(locations), len(accounts), len(proposals), len(matches)))
        return

    stats = store.save_run(db, locations, accounts, proposals, matches)
    print("run #%(run)d: %(new)d new proposals queued, %(skipped_decided)d already decided and skipped, "
          "%(matches)d confident matches" % stats)
    return stats


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
