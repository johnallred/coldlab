"""Publishing: versions by content, promotion on evidence, and the two failures."""

import json
import tempfile
import unittest
from pathlib import Path

from harness import publish

ROOT = Path(__file__).resolve().parents[2]


def lab_tree(root: Path, text: str = "# Lab\n") -> None:
    (root / "lab" / "demo").mkdir(parents=True)
    (root / "lab" / "demo" / "lab.md").write_text(text)
    (root / "lab" / "demo" / "expected.yaml").write_text("a: 1\n")
    (root / "infra" / "lambda" / "worker").mkdir(parents=True)
    (root / "infra" / "app.py").write_text("app\n")
    (root / "infra" / "lambda" / "worker" / "index.py").write_text("def h(): pass\n")


def run(day, version, passed):
    return {"started_at": f"2026-12-{day:02d}T09:17:00+00:00", "lab_version": version,
            "passed": passed}


class TestVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        lab_tree(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_editing_the_lab_document_changes_the_version(self):
        before = publish.lab_version(self.root, "demo")
        (self.root / "lab" / "demo" / "lab.md").write_text("# Lab, edited\n")
        self.assertNotEqual(before, publish.lab_version(self.root, "demo"))

    def test_editing_the_expectations_does_not(self):
        before = publish.lab_version(self.root, "demo")
        (self.root / "lab" / "demo" / "expected.yaml").write_text("a: 2\n")
        self.assertEqual(before, publish.lab_version(self.root, "demo"))

    def test_the_real_lab_has_a_version(self):
        self.assertRegex(publish.lab_version(ROOT, "sqs-retry"), r"^[0-9a-f]{12}$")


class TestPromotion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        lab_tree(self.root)
        self.v = publish.lab_version(self.root, "demo")

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_waits_for_passes_on_this_exact_content(self):
        records = [run(1, "older", True), run(2, "older", True), run(3, self.v, True)]
        done, lines = publish.promote(self.root, "demo", records, now="2026-12-04")
        self.assertFalse(done)
        self.assertIn("1 of 3", lines[-1])

    def test_a_failure_resets_the_count(self):
        records = [run(1, self.v, True), run(2, self.v, False), run(3, self.v, True),
                   run(4, self.v, True)]
        self.assertFalse(publish.promote(self.root, "demo", records)[0])

    def test_three_passes_promote_a_frozen_copy(self):
        records = [run(d, self.v, True) for d in (1, 2, 3)]
        done, _ = publish.promote(self.root, "demo", records, now="2026-12-04T00:00:00+00:00")
        self.assertTrue(done)
        copy = self.root / "published" / "demo" / self.v / "lab" / "demo" / "lab.md"
        self.assertEqual(copy.read_text(), "# Lab\n")
        self.assertFalse((self.root / "published" / "demo" / self.v / "lab" / "demo"
                          / "expected.yaml").exists())
        channels = json.loads((self.root / "published" / "demo" / "channels.json").read_text())
        self.assertEqual(channels["prod"]["version"], self.v)
        self.assertEqual(len(channels["prod"]["evidence"]), 3)
        # The lab then changes on main, and learners keep the published copy.
        (self.root / "lab" / "demo" / "lab.md").write_text("# Lab, edited\n")
        self.assertEqual(copy.read_text(), "# Lab\n")

    def test_a_published_version_that_starts_failing_means_fix_forward(self):
        records = [run(d, self.v, True) for d in (1, 2, 3)]
        publish.promote(self.root, "demo", records, now="2026-12-04T00:00:00+00:00")
        records += [run(5, self.v, False), run(6, self.v, False)]
        state = publish.assess(records, publish.load_channels(self.root, "demo"), self.v)
        self.assertEqual(state["prod_failing"], 2)
        self.assertTrue(state["advice"].startswith("fix forward"))

    def test_rollback_returns_to_the_previous_published_version(self):
        records = [run(d, self.v, True) for d in (1, 2, 3)]
        publish.promote(self.root, "demo", records, now="2026-12-04T00:00:00+00:00")
        (self.root / "lab" / "demo" / "lab.md").write_text("# Lab v2\n")
        v2 = publish.lab_version(self.root, "demo")
        records += [run(d, v2, True) for d in (5, 6, 7)]
        publish.promote(self.root, "demo", records, now="2026-12-08T00:00:00+00:00")
        done, _ = publish.rollback(self.root, "demo", "learners report step 4", now="2026-12-09")
        self.assertTrue(done)
        channels = publish.load_channels(self.root, "demo")
        self.assertEqual(channels["prod"]["version"], self.v)
        self.assertIn("rollback from", channels["prod"]["reason"])


if __name__ == "__main__":
    unittest.main()
