"""The public health page. Every figure on it must come from the record."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from harness import report, site

ROOT = Path(__file__).resolve().parents[2]


def record(day, passed, seconds, error=None, redrive=None, **checks):
    return {
        "started_at": f"2026-11-{day:02d}T09:17:00+00:00",
        "seconds": seconds,
        "passed": passed,
        "error": error,
        "measurements": {"redrive_seconds": redrive} if redrive else {},
        "checks": [{"name": n, "ok": ok, "gating": not n.startswith("adv_")}
                   for n, ok in checks.items()],
    }


def text(page: str) -> str:
    """The visible text, so assertions are about what a reader sees."""
    page = re.sub(r"<style>.*?</style>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


class TestRender(unittest.TestCase):
    def setUp(self):
        self.records = [
            record(1, False, 19, error="RuntimeError: deploy refused\nmore detail"),
            record(2, False, 400, run_completed=False),
            record(3, True, 480, redrive=140, run_completed=True, adv_exact=False),
            record(4, True, 460, redrive=120, run_completed=True, adv_exact=True),
        ]
        self.page = site.render(self.records)
        self.seen = text(self.page)

    def test_the_headline_figures_are_the_summary_figures(self):
        summary = report.summarize(self.records)
        self.assertIn(f"Runs recorded {summary['runs']}", self.seen)
        self.assertIn(f"Pass rate {summary['pass_rate'] * 100:.0f}%", self.seen)
        self.assertIn(f"Median duration {summary['median_seconds']:.0f}s", self.seen)

    def test_flaky_checks_are_named(self):
        self.assertIn("run_completed : 1 of 3 runs failed (gating)", self.seen)
        self.assertIn("adv_exact : 1 of 2 runs failed (advisory)", self.seen)

    def test_a_run_that_stopped_early_says_so(self):
        self.assertIn("none; it stopped before the lab's checks ran", self.seen)
        self.assertIn("RuntimeError: deploy refused", self.seen)
        self.assertNotIn("more detail", self.seen)

    def test_meaning_never_rests_on_colour(self):
        self.assertIn("failed", self.seen)
        self.assertIn("not run", self.seen)

    def test_error_text_is_escaped(self):
        page = site.render([record(1, False, 5, error="<script>alert(1)</script>")])
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_no_records(self):
        self.assertIn("No runs recorded yet.", text(site.render([])))

    def test_the_grid_is_capped_to_recent_runs(self):
        many = [record(1 + i % 28, True, 400, run_completed=True) for i in range(40)]
        header = re.search(r"<thead><tr><th scope=col>Check</th>(.*?)</tr>",
                           site.render(many)).group(1)
        self.assertEqual(header.count("<th"), site.GRID_RUNS)


class TestBuildFromTheRealRecord(unittest.TestCase):
    def test_it_builds_and_quotes_the_generated_summary(self):
        records = report.load_records(ROOT / "health" / "health.jsonl")
        with tempfile.TemporaryDirectory() as out:
            page = site.build(records, out).read_text(encoding="utf-8")
        summary = report.summarize(records)
        self.assertIn(f"Runs recorded {summary['runs']}", text(page))
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertNotIn("<script", page)


if __name__ == "__main__":
    unittest.main()
