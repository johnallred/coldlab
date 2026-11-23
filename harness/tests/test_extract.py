"""Extraction: the lab document is the step list.

Two kinds of test. The first reads the real `lab/sqs-retry/lab.md` and freezes
what it produces, so an edit to the lab cannot silently change what the harness
runs: the snapshot fails and somebody confirms the change was meant. The second
feeds synthetic documents to prove the directives parse and, more importantly,
that a document which would weaken the test is rejected rather than accepted.
"""

import tempfile
import unittest
from pathlib import Path

from harness import extract
from harness.steps import KNOWN_CONDITIONS, lab_document

# Exactly the steps Phase 2 hardcoded, in order. The names are byte-identical
# to the hardcoded ones; the commands differ in one intended way, which
# `test_region_comes_from_the_environment` below pins down.
EXPECTED_ORDER = [
    "send the message that always fails",
    "wait for the redrive to the dead-letter queue",
    "read the dead-letter queue",
    "confirm the failing file never landed",
    "send the message that recovers on the third attempt",
    "wait for the file to land",
    "confirm the file landed",
]

EXPECTED_COMMANDS = {
    "send the message that always fails":
        'aws sqs send-message --region "$REGION" --queue-url "$Q" '
        '--message-body \'{"file":"invoice-8812.csv","fail_until":99}\'',
    "read the dead-letter queue":
        'aws sqs receive-message --region "$REGION" --queue-url "$DLQ" '
        "--attribute-names All --wait-time-seconds 20 --max-number-of-messages 1",
    "confirm the failing file never landed":
        'aws s3 ls "s3://$BUCKET/landed/"',
    "send the message that recovers on the third attempt":
        'aws sqs send-message --region "$REGION" --queue-url "$Q" '
        '--message-body \'{"file":"invoice-9001.csv","fail_until":3}\'',
    "confirm the file landed":
        'aws s3 ls "s3://$BUCKET/landed/"',
}


class TestTheRealLabDocument(unittest.TestCase):
    def setUp(self):
        self.steps = extract.extract(lab_document())
        self.by_name = {s.name: s for s in self.steps}

    def test_names_and_order(self):
        self.assertEqual([s.name for s in self.steps], EXPECTED_ORDER)

    def test_commands_are_what_they_were(self):
        for name, command in EXPECTED_COMMANDS.items():
            self.assertEqual(self.by_name[name].command, command, name)

    def test_exit_codes(self):
        # The only step permitted a non-zero exit is the one checking an empty
        # prefix. The final listing must exit 0: by then the file is there.
        self.assertEqual(
            self.by_name["confirm the failing file never landed"].expect_exit,
            (0, 1))
        self.assertEqual(self.by_name["confirm the file landed"].expect_exit, (0,))

    def test_waits(self):
        redrive = self.by_name["wait for the redrive to the dead-letter queue"]
        self.assertEqual(redrive.wait_for, "dlq_has_message")
        self.assertEqual(redrive.timeout, 420)
        self.assertIsNone(redrive.command)

        landing = self.by_name["wait for the file to land"]
        self.assertEqual(landing.wait_for, "success_file_present")
        self.assertEqual(landing.timeout, 300)

    def test_region_comes_from_the_environment(self):
        # The one intended change from Phase 2's hardcoded commands. The lab
        # reads "$REGION" the way a student's shell does, which is what lets
        # the harness pin the region instead of inheriting whatever the
        # credentials resolve to. A deploy went to us-east-1 for want of this.
        for step in self.steps:
            if step.command and "--region" in step.command:
                self.assertIn('--region "$REGION"', step.command, step.name)
                self.assertNotIn("us-east-2", step.command, step.name)

    def test_the_document_validates_clean(self):
        self.assertEqual(extract.validate(self.steps), [])

    def test_the_student_only_parts_are_skipped(self):
        # Provisioning, exporting the stack outputs, tailing logs, reading the
        # queue depth, and tearing down are things a student does that the
        # harness does differently. Each is marked, with a reason.
        found = extract.blocks(lab_document().read_text(encoding="utf-8"))
        skipped = [b for b in found if b.skip_reason]
        self.assertEqual(len(found), 12)
        self.assertEqual(len(skipped), 5)
        for block in skipped:
            self.assertTrue(block.skip_reason.strip(),
                            f"{block.where} skipped with no reason")

    def test_only_conditions_the_runner_knows(self):
        for step in self.steps:
            if step.wait_for:
                self.assertIn(step.wait_for, KNOWN_CONDITIONS)


def document(*bodies: str) -> Path:
    """A minimal valid lab, plus whatever blocks a test appends."""
    head = (
        "# Synthetic lab\n\n"
        "## Send\n\n```bash\n# step: send\n"
        'aws sqs send-message --queue-url "$Q" --message-body \'{}\'\n```\n\n'
        "## Read\n\n```bash\n# step: read\n"
        'aws sqs receive-message --queue-url "$DLQ" --wait-time-seconds 20\n```\n'
    )
    path = Path(tempfile.mkdtemp()) / "lab.md"
    path.write_text(head + "\n" + "\n".join(bodies), encoding="utf-8")
    return path


class TestDirectives(unittest.TestCase):
    def test_not_run_blocks_are_skipped(self):
        steps = extract.extract(document(
            "## Setup\n\n```bash\n# not run by the harness: the harness does this\n"
            "cdk deploy\n```\n"))
        self.assertEqual([s.name for s in steps], ["send", "read"])

    def test_exits_accumulates(self):
        steps = extract.extract(document(
            "## List\n\n```bash\n# step: list\n# exits 1: empty prefix\n"
            "# exits 2: also fine here\n"
            'aws s3 ls "s3://$BUCKET/"\n```\n'))
        self.assertEqual(
            next(s for s in steps if s.name == "list").expect_exit, (0, 1, 2))

    def test_a_block_with_no_exits_directive_requires_zero(self):
        steps = extract.extract(document(
            "## Plain\n\n```bash\n# step: plain\naws sts get-caller-identity\n```\n"))
        self.assertEqual(
            next(s for s in steps if s.name == "plain").expect_exit, (0,))

    def test_heading_names_a_block_without_a_step_directive(self):
        steps = extract.extract(document(
            "## Check the thing\n\n```bash\naws sts get-caller-identity\n```\n"))
        self.assertIn("Check the thing", [s.name for s in steps])

    def test_repeated_heading_names_get_an_ordinal(self):
        steps = extract.extract(document(
            "## Twice\n\n```bash\naws sts get-caller-identity\n```\n\n"
            "```bash\naws sts get-caller-identity\n```\n"))
        names = [s.name for s in steps]
        self.assertIn("Twice", names)
        self.assertIn("Twice (2)", names)

    def test_wait_timeout_is_read(self):
        steps = extract.extract(document(
            "## Hold\n\n```bash\n# step: hold\n"
            "# harness waits for: dlq_has_message (timeout 99s)\nsleep 10\n```\n"))
        self.assertEqual(next(s for s in steps if s.name == "hold").timeout, 99)

    def test_wait_without_a_timeout_uses_the_default(self):
        steps = extract.extract(document(
            "## Hold\n\n```bash\n# step: hold\n"
            "# harness waits for: dlq_has_message\nsleep 10\n```\n"))
        self.assertEqual(next(s for s in steps if s.name == "hold").timeout,
                         extract.DEFAULT_WAIT_TIMEOUT)

    def test_non_bash_fences_are_ignored(self):
        steps = extract.extract(document(
            '## Output\n\n```json\n{"not": "a command"}\n```\n'))
        self.assertEqual([s.name for s in steps], ["send", "read"])


class TestRejections(unittest.TestCase):
    """A document that would weaken the test must not run at all."""

    def assertRejected(self, path, fragment):
        with self.assertRaises(extract.ExtractionError) as caught:
            extract.extract(path)
        self.assertIn(fragment, str(caught.exception))

    def test_two_commands_in_one_runnable_block(self):
        self.assertRejected(document(
            "## Both\n\n```bash\n# step: both\naws sts get-caller-identity\n"
            "aws s3 ls\n```\n"), "exactly one command")

    def test_unclosed_fence(self):
        path = Path(tempfile.mkdtemp()) / "lab.md"
        path.write_text("# Lab\n\n```bash\naws s3 ls\n", encoding="utf-8")
        self.assertRejected(path, "unclosed")

    def test_a_second_dead_letter_read(self):
        # The receive count is only the arrival value on the first read.
        self.assertRejected(document(
            "## Again\n\n```bash\n# step: again\n"
            'aws sqs receive-message --queue-url "$DLQ" --wait-time-seconds 20\n```\n'),
            "exactly one receive-message")

    def test_a_short_poll_is_rejected(self):
        path = Path(tempfile.mkdtemp()) / "lab.md"
        path.write_text(
            "# Lab\n\n## Send\n\n```bash\n# step: send\n"
            'aws sqs send-message --queue-url "$Q" --message-body \'{}\'\n```\n\n'
            "## Read\n\n```bash\n# step: read\n"
            'aws sqs receive-message --queue-url "$DLQ"\n```\n',
            encoding="utf-8")
        self.assertRejected(path, "does not long poll")

    def test_a_bare_sleep_in_a_runnable_step(self):
        self.assertRejected(document(
            "## Nap\n\n```bash\n# step: nap\nsleep 150\n```\n"),
            "bare sleep")

    def test_a_condition_the_runner_cannot_poll(self):
        self.assertRejected(document(
            "## Hold\n\n```bash\n# step: hold\n"
            "# harness waits for: the_vibes_are_right\nsleep 10\n```\n"),
            "cannot poll")

    def test_a_wait_block_may_not_hold_other_commands(self):
        self.assertRejected(document(
            "## Hold\n\n```bash\n# step: hold\n"
            "# harness waits for: dlq_has_message\naws s3 ls\n```\n"),
            "may only contain")

    def test_a_lab_that_never_sends_anything(self):
        path = Path(tempfile.mkdtemp()) / "lab.md"
        path.write_text(
            "# Lab\n\n## Read\n\n```bash\n# step: read\n"
            'aws sqs receive-message --queue-url "$DLQ" --wait-time-seconds 20\n```\n',
            encoding="utf-8")
        self.assertRejected(path, "never starts anything")

    def test_a_document_with_no_runnable_blocks(self):
        path = Path(tempfile.mkdtemp()) / "lab.md"
        path.write_text("# Lab\n\nAll prose, no commands.\n", encoding="utf-8")
        self.assertRejected(path, "no runnable steps")


if __name__ == "__main__":
    unittest.main()
