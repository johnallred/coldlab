"""Phase status, which must be derivable and must refuse to flatter.

The bug this prevents: the README's status line was updated when the nightly
workflow landed and a nearby section was not, so the README asserted there was
no nightly run while the run sat in the record. A prose claim about an absence
has no referent to check, so the claim stopped being prose.

These tests check the derivation both ways. Against the real repository, every
phase is done. Against a repository missing a piece, the matching phase must
say so rather than being marked done anyway.
"""

import json
import tempfile
import unittest
from pathlib import Path

from harness import phases

ROOT = Path(__file__).resolve().parents[2]


def record(run_id="20261123T000000+0000", passed=True, ci=False,
           teardown=True):
    names = ["teardown.stack_deleted", "teardown.no_leaks",
             "teardown.all_tagged_resolved"]
    return {
        "run_id": run_id, "started_at": "2026-11-23T00:00:00+00:00",
        "seconds": 400.0, "passed": passed, "ci": ci,
        "checks": [{"name": n, "ok": teardown, "gating": True} for n in names],
    }


def fake_repo(tmp, *, records=None, omit=()):
    """A repository with every file phases.py looks for, minus `omit`."""
    root = Path(tmp)
    files = {
        "bootstrap/oidc-role.yaml": "Policies:\n  - PolicyName: AssumeCdkBootstrapRoles\n",
        "bootstrap/budget.yaml": "Resources: {}\n",
        ".github/workflows/oidc-smoke.yml": "name: OIDC smoke\n",
        ".github/workflows/lab-health.yml": "name: Lab health\n",
        "infra/lab_stack.py": "# the stack\n",
        "harness/run.py": "# the runner\n",
        "harness/steps.py": "# no lab commands here\n",
        "README.md": "# fake\n\n<!-- health:start -->\n<!-- health:end -->\n"
                     "<!-- phases:start -->\n<!-- phases:end -->\n",
    }
    for relative, content in files.items():
        if relative in omit:
            continue
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    # The real lab document, so extraction is exercised rather than faked.
    lab = root / "lab" / "sqs-retry"
    lab.mkdir(parents=True, exist_ok=True)
    if "lab/sqs-retry/lab.md" not in omit:
        lab.joinpath("lab.md").write_text(
            (ROOT / "lab" / "sqs-retry" / "lab.md").read_text(encoding="utf-8"),
            encoding="utf-8")

    health = root / "health"
    health.mkdir(parents=True, exist_ok=True)
    rows = records if records is not None else [
        record("a", passed=False), record("b"), record("c", ci=True)]
    health.joinpath("health.jsonl").write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8")
    return root


def by_number(found):
    return {p.number: p for p in found}


class TestTheRealRepository(unittest.TestCase):
    def test_every_phase_is_done(self):
        found = phases.assess(ROOT)
        not_done = [(p.number, [c.description for c in p.conditions if not c.ok])
                    for p in found if not p.done]
        self.assertEqual(not_done, [])

    def test_five_phases(self):
        self.assertEqual([p.number for p in phases.assess(ROOT)], [0, 1, 2, 3, 4])

    def test_the_readme_block_is_current(self):
        # The same staleness check CI runs, so it fails here first.
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(phases.render(phases.assess(ROOT)), text)

    def test_unverifiable_things_are_named(self):
        # A phase that quietly claims what it cannot check is the failure
        # this module exists to prevent.
        notes = [note for p in phases.assess(ROOT) for note in p.unverifiable]
        self.assertTrue(notes)
        self.assertTrue(any("reach AWS" in note for note in notes))


class TestDerivationRefusesToFlatter(unittest.TestCase):
    def test_a_complete_fake_repo_is_all_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = phases.assess(fake_repo(tmp))
            self.assertTrue(all(p.done for p in found),
                            [(p.number, p.done) for p in found])

    def test_no_ci_run_means_phase_4_is_not_done(self):
        # The exact claim the README once made wrongly.
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_repo(tmp, records=[record("a"), record("b")])
            self.assertFalse(by_number(phases.assess(root))[4].done)

    def test_a_missing_workflow_means_phase_4_is_not_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_repo(tmp, omit=(".github/workflows/lab-health.yml",))
            self.assertFalse(by_number(phases.assess(root))[4].done)

    def test_no_passing_run_means_phase_2_is_not_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_repo(tmp, records=[record("a", passed=False)])
            self.assertFalse(by_number(phases.assess(root))[2].done)

    def test_no_failing_run_means_phase_2_is_not_done(self):
        # A harness that has never recorded a failure has not shown it can.
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_repo(tmp, records=[record("a"), record("b", ci=True)])
            self.assertFalse(by_number(phases.assess(root))[2].done)

    def test_unverified_teardown_means_phase_1_is_not_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_repo(tmp, records=[
                record("a", passed=False, teardown=False),
                record("b", teardown=False), record("c", ci=True, teardown=False)])
            self.assertFalse(by_number(phases.assess(root))[1].done)

    def test_lab_commands_in_harness_code_mean_phase_3_is_not_done(self):
        # Extraction is only real while the commands live in the document.
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_repo(tmp)
            (root / "harness" / "steps.py").write_text(
                'STEPS = ["aws sqs send-message --queue-url $Q"]\n',
                encoding="utf-8")
            self.assertFalse(by_number(phases.assess(root))[3].done)

    def test_a_missing_lab_document_means_phase_3_is_not_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_repo(tmp, omit=("lab/sqs-retry/lab.md",))
            self.assertFalse(by_number(phases.assess(root))[3].done)

    def test_an_empty_repo_claims_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = phases.assess(Path(tmp))
            self.assertEqual([p.number for p in found if p.done], [])


class TestRender(unittest.TestCase):
    def test_names_what_is_missing_rather_than_just_saying_no(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_repo(tmp, records=[record("a"), record("b")])
            text = phases.render(phases.assess(root))
            self.assertIn("not yet: at least one recorded run came from CI", text)

    def test_says_the_table_cannot_be_edited_to_change_it(self):
        text = phases.render(phases.assess(ROOT))
        self.assertIn("harness/phases.py", text)

    def test_missing_markers_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "README.md"
            path.write_text("# no markers\n", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                phases.update_readme(path, phases.assess(ROOT))
            self.assertIn("phases:start", str(caught.exception))

    def test_update_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_repo(tmp)
            found = phases.assess(root)
            readme = root / "README.md"
            self.assertTrue(phases.update_readme(readme, found))
            self.assertFalse(phases.update_readme(readme, found))


if __name__ == "__main__":
    unittest.main()
