# bounty-radar

Find open-source bounties on GitHub that **nobody is working on yet**.

Most bounty issues are swarmed within hours. Before you spend an evening on one,
bounty-radar checks each issue and drops it if:

- it is already **rewarded** (`💰 Rewarded`, `paid`, …) or **assigned**
- an **open pull request** already references it
- someone has posted a claim (`/attempt`, `/claim`, `/opire try`)
- the repo is a **fork** or **archived** (forks often copy bounty labels from the original issue)
- it has **conflicting `$` labels** (a common sign of label-stuffed farm repos)
- no dollar amount can be found (from labels, title, body, or an Algora-style bot comment)

What's left is sorted by amount, then by repository stars.

Example output (illustrative):

```
$ bounty-radar -n 100
  $1,000  ★812    2026-10-02  Fix race in websocket reconnect
          https://github.com/example/project/issues/123
     $75  ★96     2026-10-04  Add --json flag to export command
          https://github.com/example/tool/issues/45

Skipped: 54 claimed by someone, 40 open PR already exists, 27 fork repository, ...
```

## Install

Requires Python 3.9+ and an authenticated [GitHub CLI](https://cli.github.com/) (`gh auth login`).
No other dependencies.

```sh
pipx install git+https://github.com/TheRWX/bounty-radar
# or just run the single file
python3 bounty_radar.py
```

## Usage

```sh
bounty-radar                                  # default Algora + "bounty" label searches
bounty-radar --min-amount 100                 # only $100+
bounty-radar -q 'label:"💎 Bounty" is:open language:rust'   # your own search (repeatable)
bounty-radar --include-attempted              # keep issues with claims but no PR yet
bounty-radar --include-unpriced               # keep bounties with no amount found
bounty-radar --json > bounties.json           # machine-readable output
```

`-q` takes any [GitHub issue search query](https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests).
Each inspected issue costs one API call (plus one per new repo), so large `-n` values take a while.

## Before you start work

bounty-radar filters out competition. It **cannot tell whether a bounty will actually be paid.**
Some repos post large bounties on a brand-new project to attract free work. Before investing time:

- check that the bounty is funded on the platform it names (Algora, Opire, IssueHunt, …)
- look for past `💰 Rewarded` issues and merged PRs from outside contributors
- read the project's contributing rules and comment before starting if they ask you to

bounty-radar is read-only: it never comments, forks, or opens PRs for you.

## Development

```sh
python3 -m unittest discover -s tests -t .
```

## License

MIT
