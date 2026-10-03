"""Fetch GitHub profile data into data/stats.json.

Fail-safe: starts from the existing stats.json and only overwrites what fetched
successfully. Exits nonzero only if every source fails.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BRIEF = json.loads((Path(__file__).parent / "brief.json").read_text())
LOGIN = BRIEF["login"]
STATS = Path(__file__).parent / "data" / "stats.json"
TOKEN = os.environ.get("PROFILE_TOKEN") or os.environ.get("GITHUB_TOKEN")

# ponytail: first 100 repos by stars; repos past #100 add ~0 stars. Paginate if that changes.
# Operations cards, in display order: brief.json "ops" = [{"repo": "owner/name", "brief": ...,
# optional "title"/"url" to show a live site instead of the repo}]. Keep the card count even.
OPS = BRIEF["ops"]

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    login name createdAt
    followers { totalCount }
    pullRequests { totalCount }
    merged: pullRequests(states: MERGED) { totalCount }
    contributionsCollection { contributionYears }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC,
                 orderBy: {field: STARGAZERS, direction: DESC}) {
      nodes {
        name description url stargazerCount forkCount
        languages(first: 5, orderBy: {field: SIZE, direction: DESC}) { nodes { name } }
      }
    }
  }
}"""


def graphql(query, variables=None):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "User-Agent": "hashflagify"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def repo(r):
    return {
        "name": r["name"],
        "description": r["description"] or "",
        "url": r["url"],
        "stars": r["stargazerCount"],
        "forks": r["forkCount"],
        "languages": [lang["name"] for lang in r["languages"]["nodes"]],
    }


def fetch_profile():
    u = graphql(PROFILE_QUERY, {"login": LOGIN})["user"]
    repos = [repo(r) for r in u["repositories"]["nodes"]]
    return {
        "login": u["login"],
        "name": u["name"],
        "created_at": u["createdAt"],
        "followers": u["followers"]["totalCount"],
        "prs_total": u["pullRequests"]["totalCount"],
        "prs_merged": u["merged"]["totalCount"],
        "years": sorted(u["contributionsCollection"]["contributionYears"]),
        "stars": sum(r["stars"] for r in repos),
        "repos": repos,
    }


def rest(path):
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"Authorization": f"bearer {TOKEN}", "User-Agent": "hashflagify"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.status, json.loads(resp.read() or "null")  # 204 (empty repo) has no body


def fetch_org():
    # REST, not GraphQL: org fields over GraphQL need read:org on classic tokens; these are public.
    o = rest(f"orgs/{LOGIN}")[1]
    # ponytail: one page of 100 repos; paginate if the org passes 100 public repos
    repos = [r for r in rest(f"orgs/{LOGIN}/repos?type=sources&per_page=100")[1] if not r["private"]]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=372)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # ponytail: first 100 contributors per repo; paginate if a repo passes 100
    people = {c["login"] for r in repos for c in rest(f"repos/{LOGIN}/{r['name']}/contributors?per_page=100")[1] or []
              if c.get("type") == "User"}
    return {
        "login": o["login"],
        "name": o["name"],
        "created_at": o["created_at"],
        "repos_public": o["public_repos"],
        "stars": sum(r["stargazers_count"] for r in repos),
        "forks": sum(r["forks_count"] for r in repos),
        "contributors": len(people),
        "prs_merged": rest(f"search/issues?q=org:{LOGIN}+is:pr+is:merged&per_page=1")[1]["total_count"],
        # .github is excluded: its commits are this workflow's daily refreshes, not the org's work.
        "active_repos": sorted(r["name"] for r in repos
                               if not r["archived"] and r["pushed_at"] > cutoff and r["name"] != ".github"),
    }


def commit_activity(name):
    """Last 52 weeks of default-branch commits for one repo. GitHub answers 202 while it computes."""
    for _ in range(6):
        status, body = rest(f"repos/{LOGIN}/{name}/stats/commit_activity")
        if status == 200:
            return body or []
        time.sleep(5)
    raise RuntimeError(f"commit stats for {name} not ready")


def fetch_org_calendar(repos):
    """Org stand-in for a contribution calendar: daily commits summed across active public repos."""
    days = {}
    for name in repos:
        for week in commit_activity(name):
            sunday = datetime.fromtimestamp(week["week"], timezone.utc).date()
            for i, n in enumerate(week["days"]):
                key = (sunday + timedelta(days=i)).isoformat()
                days[key] = days.get(key, 0) + n
    today = date.today().isoformat()
    return {k: v for k, v in days.items() if k <= today}


def fetch_ops():
    fields = "name description url stargazerCount forkCount languages(first: 3, orderBy: {field: SIZE, direction: DESC}) { nodes { name } }"
    aliases = "\n".join(
        f'r{i}: repository(owner: "{o["repo"].split("/")[0]}", name: "{o["repo"].split("/")[1]}") {{ {fields} }}'
        for i, o in enumerate(OPS))
    data = graphql(f"query {{ {aliases} }}")
    ops = [repo(data[f"r{i}"]) for i in range(len(OPS))]
    for r, o in zip(ops, OPS):
        r["description"] = o["brief"]
        if "url" in o:
            r["title"], r["url"] = o["title"], o["url"]
    return ops


def fetch_calendar(years):
    aliases = "\n".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y}-12-31T23:59:59Z") '
        "{ contributionCalendar { weeks { contributionDays { date contributionCount } } } }"
        for y in years
    )
    u = graphql(f"query($login: String!) {{ user(login: $login) {{ {aliases} }} }}", {"login": LOGIN})["user"]
    today = date.today().isoformat()
    return {
        d["date"]: d["contributionCount"]
        for c in u.values()
        for w in c["contributionCalendar"]["weeks"]
        for d in w["contributionDays"]
        if d["date"] <= today
    }


def streaks(days, today):
    """(current, longest). Current may end yesterday if today has no contributions yet."""
    day = today if days.get(today.isoformat(), 0) else today - timedelta(days=1)
    current = 0
    while days.get(day.isoformat(), 0):
        current += 1
        day -= timedelta(days=1)
    longest = run = 0
    prev = None
    for d in sorted(k for k, v in days.items() if v):
        cur = date.fromisoformat(d)
        run = run + 1 if prev and cur - prev == timedelta(days=1) else 1
        longest = max(longest, run)
        prev = cur
    return current, longest


def main():
    stats = json.loads(STATS.read_text()) if STATS.exists() else {}
    ok = 0

    try:
        stats.update(fetch_org() if BRIEF["kind"] == "org" else fetch_profile())
        ok += 1
    except Exception as e:
        print(f"profile fetch failed, keeping previous: {e}", file=sys.stderr)

    try:
        stats["ops"] = fetch_ops()
        ok += 1
    except Exception as e:
        print(f"ops fetch failed, keeping previous: {e}", file=sys.stderr)

    if stats.get("years") or stats.get("active_repos"):
        try:
            days = fetch_org_calendar(stats["active_repos"]) if BRIEF["kind"] == "org" else fetch_calendar(stats["years"])
            today = date.today()
            current, longest = streaks(days, today)
            stats.update(
                contributions=dict(sorted(days.items())),
                contributions_all_time=sum(days.values()),
                contributions_this_year=sum(v for k, v in days.items() if k.startswith(str(today.year))),
                streak_current=current,
                streak_longest=longest,
            )
            ok += 1
        except Exception as e:
            print(f"calendar fetch failed, keeping previous: {e}", file=sys.stderr)

    if not ok:
        sys.exit("all sources failed")
    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
