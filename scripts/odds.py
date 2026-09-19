#!/usr/bin/env python3
"""Scrape UFC.com event pages for fight odds and write odds.json.

Stdlib only. Run by the GitHub Action in .github/workflows/odds.yml.
Output shape (consumed by index.html):
  {"updated": "<iso utc>", "source": "ufc.com",
   "fights": [{"event": "<slug>", "a": "Anthony Hernandez", "b": "Gregory Rodrigues",
               "oa": -165, "ob": 140}, ...]}
"""
import html
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.ufc.com"
UA = "Mozilla/5.0 (compatible; ufc-fight-night-tracker; +https://github.com/petarceklic/ufc)"
MAX_EVENTS = 6  # current + next few; odds rarely exist further out


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (i + 1))
    raise last


def clean(s):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s))).strip()


def event_slugs(listing):
    out = []
    for m in re.finditer(r'href="(/event/[^"#?]+)"', listing):
        s = m.group(1)
        if s not in out:
            out.append(s)
    return out


def corner_name(blk, color):
    """Fighter name from one corner.

    ufc.com renders corners two ways: given-name + family-name spans for most
    fighters, and a single flat text node for others (ring names like
    "Patricio Pitbull", and some late additions). Take the whole corner div and
    strip tags, which covers both without caring which shape it is.
    """
    m = re.search(
        r'c-listing-fight__corner-name--%s">(.*?)</div>' % color, blk, re.S)
    return clean(m.group(1)) if m else ""


def parse_event(page, slug):
    fights = []
    seen = set()
    no_odds = 0
    blocks = re.split(r'<div class="c-listing-fight" data-fmid="', page)[1:]
    for blk in blocks:
        fmid = blk.split('"', 1)[0]
        if fmid in seen:
            continue
        seen.add(fmid)
        red = corner_name(blk, "red")
        blue = corner_name(blk, "blue")
        if not red or not blue:
            print(f"  {slug}: fmid {fmid} has no parsable names", file=sys.stderr)
            continue
        odds = re.findall(r'c-listing-fight__odds-amount">\s*([+-]?\d+)\s*<', blk)
        # Keep the fight even with no line posted (late bookings, pulled fights).
        # null tells the app "no odds yet"; dropping the row would hide the bout.
        if len(odds) < 2:
            no_odds += 1
            oa = ob = None
        else:
            oa, ob = int(odds[0]), int(odds[1])
        wc = re.search(r'c-listing-fight__class-text">(.*?)</div>', blk, re.S)
        fights.append({
            "event": slug.rsplit("/", 1)[-1],
            "a": red, "b": blue,
            "oa": oa, "ob": ob,
            "wc": clean(wc.group(1)) if wc else "",
        })
    if len(fights) < len(seen):
        print(f"  {slug}: parsed {len(fights)} of {len(seen)} fight blocks", file=sys.stderr)
    if no_odds:
        print(f"  {slug}: {no_odds} fight(s) have no line posted yet", file=sys.stderr)
    return fights


def main():
    listing = get(BASE + "/events")
    slugs = event_slugs(listing)[:MAX_EVENTS]
    if not slugs:
        print("no event links found on /events", file=sys.stderr)
        sys.exit(1)
    fights, events = [], []
    for slug in slugs:
        try:
            page = get(BASE + slug)
        except Exception as e:  # noqa: BLE001
            print(f"skip {slug}: {e}", file=sys.stderr)
            continue
        f = parse_event(page, slug)
        print(f"{slug}: {len(f)} fights", file=sys.stderr)
        events.append({"event": slug.rsplit("/", 1)[-1], "fights": len(f)})
        fights.extend(f)
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "ufc.com",
        "events": events,
        "fights": fights,
    }
    if not fights:
        # Keep the old file rather than publishing an empty one.
        print("no fights parsed; leaving odds.json untouched", file=sys.stderr)
        sys.exit(0)
    try:
        with open("odds.json") as fh:
            old = json.load(fh)
        if old.get("fights") == fights and old.get("events") == events:
            print("odds unchanged; not rewriting", file=sys.stderr)
            return
    except Exception:  # noqa: BLE001
        pass
    with open("odds.json", "w") as fh:
        json.dump(out, fh, separators=(",", ":"), ensure_ascii=False)
        fh.write("\n")
    print(f"wrote odds.json: {len(fights)} fights across {len(events)} events", file=sys.stderr)


if __name__ == "__main__":
    main()
