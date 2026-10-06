import unittest

import bounty_radar as br


def issue(number, labels=(), title="Fix it", body="", repo="o/r", assignee=None):
    return {
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "number": number,
        "title": title,
        "body": body,
        "labels": [{"name": name} for name in labels],
        "assignee": assignee,
        "assignees": [assignee] if assignee else [],
        "updated_at": "2026-10-01T00:00:00Z",
        "state": "open",
    }


def open_pr(state="open"):
    return {
        "event": "cross-referenced",
        "source": {"issue": {"pull_request": {}, "state": state,
                             "html_url": "https://github.com/o/r/pull/9"}},
    }


class FakeGitHub:
    def __init__(self, items, timelines=None, repos=None):
        self.items = items
        self.timelines = timelines or {}
        self.repos = repos or {}

    def __call__(self, path, params=None, paginate=False):
        if path == "search/issues":
            start = (params["page"] - 1) * 100
            return {"items": self.items[start:start + params["per_page"]]}
        if path.endswith("/timeline"):
            number = int(path.split("/")[-2])
            return self.timelines.get(number, [])
        return self.repos.get(path.removeprefix("repos/"), {"stargazers_count": 5})


class AmountTests(unittest.TestCase):
    def test_parses_plain_and_k_suffix(self):
        self.assertEqual(br.parse_amount("$1,500 bounty"), 1500)
        self.assertEqual(br.parse_amount("$1.2k"), 1200)
        self.assertIsNone(br.parse_amount("no money"))

    def test_label_beats_title(self):
        self.assertEqual(br.bounty_amount(issue(1, ["$300"], title="$50"))[0], 300)

    def test_title_then_body(self):
        self.assertEqual(br.bounty_amount(issue(1, title="Fix [$75]"))[0], 75)
        self.assertEqual(br.bounty_amount(issue(1, body="Reward: $40"))[0], 40)

    def test_conflicting_labels_flagged(self):
        self.assertEqual(br.bounty_amount(issue(1, ["$780", "$1k"])),
                         (None, "conflicting $ labels"))


class ScanTests(unittest.TestCase):
    def run_scan(self, gh, **kwargs):
        kwargs.setdefault("include_unpriced", True)
        return br.scan(["q"], 30, fetch=gh, **kwargs)

    def test_keeps_uncontested_bounty(self):
        results, skipped = self.run_scan(FakeGitHub([issue(1, ["💎 Bounty", "$200"])]))
        self.assertEqual([r["amount"] for r in results], [200])
        self.assertEqual(skipped, {})

    def test_skips_open_pr_but_not_closed_pr(self):
        gh = FakeGitHub([issue(1), issue(2)],
                        timelines={1: [open_pr()], 2: [open_pr("closed")]})
        results, skipped = self.run_scan(gh)
        self.assertEqual([r["url"][-1] for r in results], ["2"])
        self.assertEqual(skipped, {"open PR already exists": 1})

    def test_skips_rewarded_assigned_fork_and_archived(self):
        gh = FakeGitHub(
            [issue(1, ["💰 Rewarded"]), issue(2, assignee={"login": "x"}),
             issue(3, repo="f/r"), issue(4, repo="a/r")],
            repos={"f/r": {"fork": True}, "a/r": {"archived": True}},
        )
        results, skipped = self.run_scan(gh)
        self.assertEqual(results, [])
        self.assertEqual(skipped, {"already rewarded": 1, "assigned": 1,
                                   "fork repository": 1, "archived repository": 1})

    def test_attempt_claims(self):
        gh = FakeGitHub([issue(1)],
                        timelines={1: [{"event": "commented", "body": "/attempt #1"}]})
        self.assertEqual(self.run_scan(gh)[0], [])
        kept, _ = self.run_scan(gh, include_attempted=True)
        self.assertEqual(kept[0]["attempts"], 1)
        for claim in ("/claim #1", "/opire try", "  /Attempt"):
            gh.timelines[1] = [{"event": "commented", "body": claim}]
            self.assertEqual(self.run_scan(gh)[1], {"claimed by someone": 1})

    def test_min_amount_dedupe_and_sort(self):
        items = [issue(1, ["$50"]), issue(2, ["$500"]), issue(2, ["$500"]), issue(3)]
        results, skipped = self.run_scan(FakeGitHub(items), min_amount=60)
        self.assertEqual([r["amount"] for r in results], [500, None])
        self.assertEqual(skipped, {"below minimum amount": 1})

    def test_amount_from_bot_comment(self):
        comment = {"event": "commented", "actor": {"type": "Bot"},
                   "body": "## 💎 $250 bounty • Acme"}
        spoof = {"event": "commented", "actor": {"type": "User"},
                 "body": "I'd do this bounty for $9999"}
        gh = FakeGitHub([issue(1)], timelines={1: [spoof, comment]})
        results, _ = self.run_scan(gh, include_unpriced=False)
        self.assertEqual([r["amount"] for r in results], [250])

    def test_search_pages_past_100(self):
        items = [issue(n, ["$10"]) for n in range(1, 151)]
        results, _ = br.scan(["q"], 120, fetch=FakeGitHub(items))
        self.assertEqual(len(results), 120)

    def test_skips_closed_issues_and_prs(self):
        closed = issue(1, ["$100"])
        closed["state"] = "closed"
        pr = issue(2, ["$100"])
        pr["pull_request"] = {}
        results, skipped = self.run_scan(FakeGitHub([closed, pr]))
        self.assertEqual(results, [])
        self.assertEqual(skipped, {"closed or not an issue": 2})

    def test_zero_label_not_overridden_by_bot(self):
        bot = {"event": "commented", "actor": {"type": "Bot"}, "body": "$500 bounty"}
        gh = FakeGitHub([issue(1, ["$0"])], timelines={1: [bot]})
        results, skipped = self.run_scan(gh, min_amount=100)
        self.assertEqual(results, [])
        self.assertEqual(skipped, {"below minimum amount": 1})

    def test_unpriced_skipped_by_default(self):
        results, skipped = self.run_scan(FakeGitHub([issue(1)]), include_unpriced=False)
        self.assertEqual(results, [])
        self.assertEqual(skipped, {"no dollar amount": 1})


if __name__ == "__main__":
    unittest.main()
