"""Rewrite only the content between <!-- name:start --> / <!-- name:end --> markers in the README."""

import json
from html import escape
import sys

from render import BIO, BRIEF, COMMENDATIONS, FEATURED, LINKS, README, REPORTS, STACK, STATS, TITLE_LINE, ops


def img(name, alt, width="100%"):
    # Percent widths: every piece scales by the same factor when the column is narrower than 840px.
    return f'<img src="./assets/{name}" alt="{escape(alt)}" width="{width}" align="top">'


def pairs(items):
    """Half-width pieces two per row. They must touch: whitespace between them shows as a gap."""
    return ["".join(items[i:i + 2]) for i in range(0, len(items), 2)]


def linked(url, image):
    return f'<a href="{url}">{image}</a>' if url else image


def brief(stats):
    org = BRIEF["kind"] == "org"
    links = "".join(linked(url, img(f"{name}.svg", label, f"{100 / len(LINKS):g}%")) for name, label, url in LINKS)
    cards = [linked(url, img(f"op-{i + 1}.svg", f"OP: {title}. {desc}", "50%")) for i, (title, desc, _, url) in enumerate(ops(stats))]
    reports = [linked(url, img(f"report-{i + 1}.svg", f"{title} ({source})", "50%")) for i, (title, source, url) in enumerate(REPORTS)]
    record = (f"{stats['repos_public']:,} public repos, {stats['stars']:,} stars, "
              f"{stats['contributions_all_time']:,} commits in the last 52 weeks") if org else (
              f"{stats['followers']:,} followers, {stats['stars']:,} stars, "
              f"{stats['prs_merged']:,} PRs merged, {stats['contributions_all_time']:,} contributions")
    rows = [
        '<div align="center">',
        img("header.svg", "Mission Brief: " + ", ".join(BRIEF["tag"])),
        links,
        img("situation.svg", f"{TITLE_LINE}. {BIO}"),
    ]
    if "unit" in BRIEF:
        u = BRIEF["unit"]
        rows.append(img("unit.svg", f"{u['title']}: " + ", ".join(f"{v} {label.lower()}" for v, label in u["tiles"])))
    rows += [
        img("record.svg", f"Service record: {record}"),
        img("city.svg", f"Mission Log: {'commit' if org else 'contribution'} city for the last 53 weeks"),
        img("operations.svg", "Operations"),
        *pairs(cards),
    ]
    if STACK:
        rows.append(img("stack.svg", "Tech stack: " + "; ".join(f"{k}: {v}" for k, v in STACK)))
    if COMMENDATIONS:
        rows.append(img("commendations.svg", "Commendations: " + "; ".join(COMMENDATIONS)
                        + (f". Featured in: {FEATURED}" if FEATURED else "")))
    if REPORTS:
        rows += [img("reports.svg", "Field reports"), *pairs(reports)]
    rows += [
        img("footer.svg", f"{BRIEF['motto']} End of brief."),
        # ponytail: 30.95 + 38.1 + 30.95 = 100; sides are 260/840, the 320px GIF row is 240 tall
        img("footer-left.svg", "", "30.95%") + img("vwc.gif", "Vets Who Code", "38.1%")
        + img("footer-right.svg", "", "30.95%"),
        img("footer-end.svg", ""),
        "</div>",
    ]
    return "\n".join(rows)


def replace_zone(text, name, content):
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if text.count(start) != 1 or text.count(end) != 1:
        sys.exit(f"{README.name} must contain exactly one {start} and one {end}")
    head, rest = text.split(start)
    _, tail = rest.split(end)
    return f"{head}{start}\n{content}\n{end}{tail}"


def main():
    stats = json.loads(STATS.read_text())
    README.write_text(replace_zone(README.read_text(), "brief", brief(stats)))


if __name__ == "__main__":
    main()
