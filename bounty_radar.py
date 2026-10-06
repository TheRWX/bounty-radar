#!/usr/bin/env python3
"""Find open-source bounties that nobody is working on yet.

Uses the GitHub CLI (`gh`) for authenticated API calls. Read-only: it never
comments, forks or opens pull requests.
"""

import argparse
import json
import re
import subprocess
import sys

__version__ = "0.1.0"

DEFAULT_QUERIES = (
    'label:"💎 Bounty" is:issue is:open',
    "label:bounty is:issue is:open",
)
PAID_LABELS = {"💰 rewarded", "rewarded", "paid", "bounty paid"}
AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*([kK])?\b")
CLAIM_COMMANDS = ("/attempt", "/claim", "/opire try")
AMOUNT_LABEL = re.compile(r"^\s*\$\s?\d[\d,]*(?:\.\d+)?\s*[kK]?\s*$")


def gh_api(path, params=None, paginate=False):
    cmd = ["gh", "api", "-X", "GET", path]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    for key, value in (params or {}).items():
        cmd += ["-f", f"{key}={value}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api {path} failed: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    if paginate:
        return [item for page in data for item in page]
    return data


def parse_amount(text):
    match = AMOUNT.search(text or "")
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    return value * 1000 if match.group(2) else value


def bounty_amount(issue):
    """Return (amount, problem). Labels win over title, title over body."""
    label_amounts = {
        parse_amount(label["name"])
        for label in issue.get("labels", [])
        if AMOUNT_LABEL.match(label["name"])
    }
    if len(label_amounts) > 1:
        return None, "conflicting $ labels"
    if label_amounts:
        return label_amounts.pop(), None
    for text in (issue.get("title"), (issue.get("body") or "")[:4000]):
        amount = parse_amount(text)
        if amount:
            return amount, None
    return None, None


def repo_of(issue):
    return issue["repository_url"].split("/repos/", 1)[1]


def competition(issue, fetch):
    """Return (open PRs referencing the issue, claim comments, bot-posted amount)."""
    events = fetch(
        f"repos/{repo_of(issue)}/issues/{issue['number']}/timeline",
        {"per_page": 100},
        paginate=True,
    )
    prs, attempts, bot_amount = set(), 0, None
    for event in events:
        kind = event.get("event")
        if kind == "cross-referenced":
            source = event.get("source", {}).get("issue", {})
            if "pull_request" in source and source.get("state") == "open":
                prs.add(source["html_url"])
        elif kind == "commented":
            body = event.get("body") or ""
            if body.lstrip().lower().startswith(CLAIM_COMMANDS):
                attempts += 1
            # Algora and similar platforms announce the reward in a bot comment.
            actor = event.get("actor") or event.get("user") or {}
            if (bot_amount is None and actor.get("type") == "Bot"
                    and "bounty" in body.lower()):
                bot_amount = parse_amount(body)
    return len(prs), attempts, bot_amount


def search(query, limit, fetch):
    """Yield up to `limit` issues for a search query, newest first."""
    page, count = 1, 0
    while count < limit:
        data = fetch("search/issues", {"q": query, "per_page": min(limit - count, 100),
                                       "sort": "created", "order": "desc", "page": page})
        items = data.get("items", [])
        for issue in items[:limit - count]:
            count += 1
            yield issue
        if len(items) < 100:
            return
        page += 1


def scan(queries, limit, fetch=gh_api, include_attempted=False, min_amount=0,
         include_unpriced=False):
    seen, results, skipped = set(), [], {}
    repo_cache = {}

    def skip(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    for query in queries:
        for issue in search(query, limit, fetch):
            url = issue["html_url"]
            if url in seen:
                continue
            seen.add(url)
            if "pull_request" in issue or issue.get("state") != "open":
                skip("closed or not an issue")
                continue
            labels = {label["name"].strip().lower() for label in issue.get("labels", [])}
            if labels & PAID_LABELS:
                skip("already rewarded")
                continue
            if issue.get("assignee") or issue.get("assignees"):
                skip("assigned")
                continue
            amount, problem = bounty_amount(issue)
            if problem:
                skip(problem)
                continue
            repo = repo_of(issue)
            if repo not in repo_cache:
                repo_cache[repo] = fetch(f"repos/{repo}")
            info = repo_cache[repo]
            if info.get("fork"):
                skip("fork repository")
                continue
            if info.get("archived"):
                skip("archived repository")
                continue
            open_prs, attempts, bot_amount = competition(issue, fetch)
            if amount is None:
                amount = bot_amount
            if amount is None and not include_unpriced:
                skip("no dollar amount")
                continue
            if amount is not None and amount < min_amount:
                skip("below minimum amount")
                continue
            if open_prs:
                skip("open PR already exists")
                continue
            if attempts and not include_attempted:
                skip("claimed by someone")
                continue
            results.append({
                "url": url,
                "title": issue["title"],
                "repo": repo,
                "stars": info.get("stargazers_count", 0),
                "amount": amount,
                "attempts": attempts,
                "updated": issue.get("updated_at", "")[:10],
            })
    results.sort(key=lambda r: (r["amount"] or 0, r["stars"]), reverse=True)
    return results, skipped


def format_table(results):
    lines = []
    for r in results:
        amount = f"${r['amount']:,.0f}" if r["amount"] else "   ?"
        lines.append(f"{amount:>8}  ★{r['stars']:<6} {r['updated']}  {r['title'][:60]}")
        lines.append(f"{'':>8}  {r['url']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List open GitHub bounties with no competing open PRs."
    )
    parser.add_argument("-q", "--query", action="append",
                        help="GitHub issue search query (repeatable)")
    parser.add_argument("-n", "--limit", type=int, default=30,
                        help="max issues to inspect per query (default 30)")
    parser.add_argument("--min-amount", type=float, default=0,
                        help="skip bounties below this dollar amount")
    parser.add_argument("--include-attempted", action="store_true",
                        help="keep issues with /attempt or /claim comments but no PR")
    parser.add_argument("--include-unpriced", action="store_true",
                        help="keep bounties with no dollar amount found")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    try:
        results, skipped = scan(
            args.query or DEFAULT_QUERIES, args.limit,
            include_attempted=args.include_attempted, min_amount=args.min_amount,
            include_unpriced=args.include_unpriced,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"bounty-radar: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"results": results, "skipped": skipped}, indent=2))
    else:
        print(format_table(results) or "No uncontested bounties found.")
        if skipped:
            summary = ", ".join(f"{n} {why}" for why, n in sorted(skipped.items()))
            print(f"\nSkipped: {summary}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
