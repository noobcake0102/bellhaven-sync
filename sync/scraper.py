"""Step 1. Pull every Bellhaven location from the public website.

Things the site does that a naive scraper gets wrong:
  * The directory is paginated, and the same community can appear on two pages.
  * Asking for a page past the end returns the last page again (so "loop until
    empty" never stops, and "loop to page N" double counts).
  * At least one community is only linked from the home page, not the directory.
So: follow the real "Next" link, also read the home and about pages, and
de-duplicate on the community URL slug.
"""
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import config

COMMUNITY_PATH = re.compile(r"^/communities/([a-z0-9-]+)$")
CITY_STATE_ZIP = re.compile(r"^(.*),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?$")


def _get(session, url):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _slugs(soup):
    out = []
    for a in soup.find_all("a", href=True):
        m = COMMUNITY_PATH.match(urlparse(a["href"]).path)
        if m:
            out.append(m.group(1))
    return out


def discover_slugs(session):
    """Return the unique community slugs, in first-seen order."""
    slugs, seen_pages = [], set()

    for path in ("/", "/about"):  # pages outside the directory that may link to communities
        slugs += _slugs(_get(session, config.SITE_BASE + path))

    url = config.SITE_BASE + "/communities"
    while url and url not in seen_pages:  # seen_pages guards against a pager loop
        seen_pages.add(url)
        soup = _get(session, url)
        slugs += _slugs(soup)
        nxt = next((a for a in soup.select(".pager a") if "Next" in a.get_text()), None)
        url = urljoin(url, nxt["href"]) if nxt else None

    return list(dict.fromkeys(slugs))  # de-dupe, keep order


def parse_detail(soup, slug):
    """Turn one community page into a plain dict."""
    fields = {}
    for dt in soup.select("dl.detail dt"):
        fields[dt.get_text(strip=True)] = dt.find_next_sibling("dd")

    addr_lines = list(fields["Address"].stripped_strings)  # ["210 Orchard Lane", "Maplewood, OH 44280"]
    m = CITY_STATE_ZIP.match(addr_lines[-1])
    if not m:
        raise ValueError("Unrecognised address format on %s: %r" % (slug, addr_lines))

    care_site = [b.get_text(strip=True) for b in fields["Care Offerings"].select(".badge")]
    return {
        "slug": slug,
        "url": "%s/communities/%s" % (config.SITE_BASE, slug),
        "name": soup.find("h1").get_text(strip=True),
        "street": " ".join(addr_lines[:-1]),
        "city": m.group(1).strip(),
        "state": m.group(2),
        "zip": m.group(3),
        "care_site": care_site,                                   # website wording
        "care_crm": [config.CARE_MAP.get(c, c) for c in care_site],  # CRM wording
        "administrator": fields["Administrator"].get_text(strip=True) if "Administrator" in fields else "",
        "phone": fields["Phone"].get_text(strip=True) if "Phone" in fields else "",
    }


def scrape():
    session = requests.Session()
    session.headers["User-Agent"] = "bellhaven-sync/1.0"
    locations = [parse_detail(_get(session, "%s/communities/%s" % (config.SITE_BASE, s)), s)
                 for s in discover_slugs(session)]
    return sorted(locations, key=lambda l: l["name"])


if __name__ == "__main__":
    import json
    locs = scrape()
    print(json.dumps(locs, indent=2))
    print("%d locations" % len(locs))
