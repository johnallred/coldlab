"""The health record. The figure that matters is the flake rate."""

import json
import tempfile
import unittest
from pathlib import Path

from harness import report


def record(run_id, passed, seconds, **check_outcomes):
    return {
        "run_id": run_id,
        "started_at": f"2026-11-{run_id:02d}T00:00:00+00:00",
        "seconds": seconds,
        "passed": passed,
        "checks": [{"name": name, "ok": ok, "gating": True}
                   for name, ok in check_outcomes.items()],
    }


class TestSummarize(unittest.TestCase):
    def test_no_runs(self):
        summary = report.summarize([])
        self.assertEqual(summary["runs"], 0)
        self.assertIsNone(summary["pass_rate"])

    def test_pass_rate_and_median(self):
        records = [
            record(1, True, 100.0, a=True),
            record(2, True, 200.0, a=True),
            record(3, False, 300.0, a=False),
        ]
        summary = report.summarize(records)
        self.assertEqual(summary["runs"], 3)
        self.assertAlmostEqual(summary["pass_rate"], 2 / 3)
        self.assertEqual(summary["median_seconds"], 200.0)

    def test_flaky_is_both_outcomes_not_just_failure(self):
        records = [record(i, True, 10.0, sometimes=(i != 3), always=False, never=True)
                   for i in range(1, 6)]
        checks = report.summarize(records)["checks"]

        # Failed once in five: the dangerous kind.
        self.assertTrue(checks["sometimes"]["flaky"])
        self.assertAlmostEqual(checks["sometimes"]["failure_rate"], 1 / 5)

        # Fails every time. Broken, not flaky; it will get fixed.
        self.assertFalse(checks["always"]["flaky"])
        self.assertEqual(checks["always"]["failure_rate"], 1.0)

        # Never fails. Stable.
        self.assertFalse(checks["never"]["flaky"])
        self.assertEqual(checks["never"]["failure_rate"], 0.0)


class TestRoundTrip(unittest.TestCase):
    def test_append_then_load_then_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "health.jsonl"
            markdown = Path(tmp) / "HEALTH.md"

            report.append_record(jsonl, record(1, True, 120.0, a=True))
            report.append_record(jsonl, record(2, False, 140.0, a=False))

            self.assertEqual(len(report.load_records(jsonl)), 2)

            summary = report.regenerate(jsonl, markdown)
            text = markdown.read_text(encoding="utf-8")

            self.assertEqual(summary["runs"], 2)
            self.assertIn("Pass rate: **50%**", text)
            self.assertIn("`a`", text)
            self.assertIn("Flaky checks", text)

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "nested" / "deeper" / "health.jsonl"
            report.append_record(jsonl, record(1, True, 1.0, a=True))
            self.assertTrue(jsonl.exists())

    def test_records_are_one_json_object_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "health.jsonl"
            for i in (1, 2, 3):
                report.append_record(jsonl, record(i, True, 1.0, a=True))
            lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 3)
            for line in lines:
                json.loads(line)

    def test_empty_record_set_renders_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            markdown = Path(tmp) / "HEALTH.md"
            report.regenerate(Path(tmp) / "absent.jsonl", markdown)
            self.assertIn("No runs recorded yet", markdown.read_text(encoding="utf-8"))


class TestReadmeBlock(unittest.TestCase):
    """The README quotes the record rather than restating it."""

    def readme(self, tmp, body=""):
        path = Path(tmp) / "README.md"
        path.write_text(
            f"# Title\n\nprose above\n\n{report.README_START}\n{body}"
            f"{report.README_END}\n\nprose below\n", encoding="utf-8")
        return path

    def test_fills_the_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.readme(tmp)
            summary = report.summarize([record(1, True, 100.0, a=True),
                                        record(2, False, 200.0, a=False)])
            self.assertTrue(report.update_readme(path, summary))
            text = path.read_text(encoding="utf-8")
            self.assertIn("Pass rate: **50%**", text)
            self.assertIn("Runs: **2**", text)
            self.assertIn("prose above", text)
            self.assertIn("prose below", text)

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.readme(tmp)
            summary = report.summarize([record(1, True, 100.0, a=True)])
            self.assertTrue(report.update_readme(path, summary))
            # Second call changes nothing, which is what lets CI use
            # `git diff --exit-code` as a staleness check.
            self.assertFalse(report.update_readme(path, summary))

    def test_replaces_stale_content_rather_than_appending(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.readme(tmp, body="- Runs: **999**\n")
            summary = report.summarize([record(1, True, 100.0, a=True)])
            report.update_readme(path, summary)
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("999", text)
            self.assertEqual(text.count(report.README_START), 1)

    def test_missing_markers_raise_rather_than_doing_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "README.md"
            path.write_text("# Title\n\nno markers here\n", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                report.update_readme(path, report.summarize([]))
            self.assertIn("health:start", str(caught.exception))

    def test_names_the_checks_that_both_passed_and_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.readme(tmp)
            records = [record(i, True, 10.0, sometimes=(i != 3))
                       for i in range(1, 6)]
            report.update_readme(path, report.summarize(records))
            self.assertIn("`sometimes`", path.read_text(encoding="utf-8"))

    def test_no_runs_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.readme(tmp)
            report.update_readme(path, report.summarize([]))
            self.assertIn("No runs recorded yet",
                          path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
