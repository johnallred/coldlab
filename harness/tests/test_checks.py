"""The assertions, against the real measured run and against broken variants.

These tests read `lab/sqs-retry/expected.yaml`, so they are also a contract
test between that file and the code: editing one without the other fails here.

Phase 2's definition of done asks for the failure path to be proved by setting
`maxReceiveCount` wrong on purpose. These prove it deterministically, with no
deployment and no cost, which is strictly better than proving it once by hand.
"""

import unittest
from pathlib import Path

import yaml

from harness import checks

EXPECTED = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "lab/sqs-retry/expected.yaml")
    .read_text(encoding="utf-8")
)

# Exactly what the 2026-11-19 hand run measured.
MEASURED_FAILURE = {
    "dlq_depth": 1,
    "receive_count": 5,
    "sent_timestamp_ms": 1795126728511,
    "sent_at_ms": 1795126728000,
    "redrive_seconds": 106.0,
    "bucket_keys": [],
}
MEASURED_SUCCESS = {"bucket_keys": ["invoice-9001.csv"]}
MEASURED_TEARDOWN = {
    "stack_exists": False,
    # The event source mapping the tag query listed, resolved against Lambda
    # and found absent.
    "tagged": [{"arn": "arn:aws:lambda:us-east-2:1:event-source-mapping:9372aab3",
                "status": "gone"}],
}


def gating_failures(results):
    return [c.name for c in results if not c.ok and c.gating]


class TestTheMeasuredRunPasses(unittest.TestCase):
    def test_failure_path(self):
        results = checks.failure_path(EXPECTED, MEASURED_FAILURE)
        self.assertEqual(gating_failures(results), [])

    def test_failure_path_advisories_also_pass(self):
        results = checks.failure_path(EXPECTED, MEASURED_FAILURE)
        self.assertEqual([c.name for c in results if not c.ok], [])

    def test_success_path(self):
        self.assertEqual(
            gating_failures(checks.success_path(EXPECTED, MEASURED_SUCCESS)), [])

    def test_teardown(self):
        self.assertEqual(
            gating_failures(checks.teardown(EXPECTED, MEASURED_TEARDOWN)), [])

    def test_whole_run_verdict_is_pass(self):
        all_checks = (checks.failure_path(EXPECTED, MEASURED_FAILURE)
                      + checks.success_path(EXPECTED, MEASURED_SUCCESS)
                      + checks.teardown(EXPECTED, MEASURED_TEARDOWN))
        passed, failures = checks.verdict(all_checks)
        self.assertTrue(passed)
        self.assertEqual(failures, [])


class TestBrokenRunsFail(unittest.TestCase):
    def test_wrong_max_receive_count_fails(self):
        # The exact scenario Phase 2 asks to prove: maxReceiveCount set wrong,
        # so the message is redriven after one receive instead of three.
        obs = {**MEASURED_FAILURE, "receive_count": 2}
        self.assertIn("dlq.receive_count_at_least_max_plus_one",
                      gating_failures(checks.failure_path(EXPECTED, obs)))

    def test_message_never_reached_the_dlq(self):
        obs = {**MEASURED_FAILURE, "dlq_depth": 0}
        self.assertIn("dlq.depth", gating_failures(checks.failure_path(EXPECTED, obs)))

    def test_failing_file_landed_anyway(self):
        obs = {**MEASURED_FAILURE, "bucket_keys": ["invoice-8812.csv"]}
        self.assertIn("bucket.failing_file_absent",
                      gating_failures(checks.failure_path(EXPECTED, obs)))

    def test_sent_timestamp_reset_by_the_redrive(self):
        # If a future SQS change reset the timestamp on redrive, this catches
        # it, and the lab's claim about DLQ age would need rewriting.
        obs = {**MEASURED_FAILURE, "sent_timestamp_ms": 1795126728511 + 600_000}
        self.assertIn("dlq.sent_timestamp_preserved",
                      gating_failures(checks.failure_path(EXPECTED, obs)))

    def test_success_file_missing(self):
        self.assertIn("bucket.success_file_present",
                      gating_failures(checks.success_path(EXPECTED, {"bucket_keys": []})))

    def test_surviving_resource_is_a_leak(self):
        obs = {**MEASURED_TEARDOWN,
               "tagged": [{"arn": "arn:aws:sqs:us-east-2:1:q", "status": "leak"}]}
        self.assertIn("teardown.no_leaks", gating_failures(checks.teardown(EXPECTED, obs)))

    def test_unresolvable_arn_fails_rather_than_passing_quietly(self):
        obs = {**MEASURED_TEARDOWN,
               "tagged": [{"arn": "arn:aws:kinesis:us-east-2:1:stream/x",
                           "status": "unresolved"}]}
        self.assertIn("teardown.all_tagged_resolved",
                      gating_failures(checks.teardown(EXPECTED, obs)))

    def test_stack_still_there(self):
        obs = {**MEASURED_TEARDOWN, "stack_exists": True}
        self.assertIn("teardown.stack_deleted", gating_failures(checks.teardown(EXPECTED, obs)))


class TestAdvisoryChecksDoNotGate(unittest.TestCase):
    def test_an_unseen_receive_count_warns_but_does_not_fail_the_run(self):
        # 7 has never been observed, so the drift detector fires. It must not
        # fail the run: the floor is what gates.
        obs = {**MEASURED_FAILURE, "receive_count": 7}
        results = checks.failure_path(EXPECTED, obs)
        drift = next(c for c in results
                     if c.name == "dlq.receive_count_in_observed_set")
        self.assertFalse(drift.ok)
        self.assertFalse(drift.gating)
        self.assertEqual(gating_failures(results), [])

    def test_both_observed_counts_are_accepted(self):
        # 5 by hand on 2026-11-19, 4 from the first passing harness run.
        # Neither may fail the run, and an exact-value check would have failed
        # the second one for no reason.
        for count in (4, 5):
            obs = {**MEASURED_FAILURE, "receive_count": count}
            results = checks.failure_path(EXPECTED, obs)
            drift = next(c for c in results
                         if c.name == "dlq.receive_count_in_observed_set")
            self.assertTrue(drift.ok, f"count {count} should be accepted")
            self.assertEqual(gating_failures(results), [])

    def test_an_advisory_still_reports_as_failed(self):
        # An advisory is not a check that cannot fail. It fails in the record;
        # it just does not set the exit code.
        obs = {**MEASURED_FAILURE, "redrive_seconds": 5.0}
        results = checks.failure_path(EXPECTED, obs)
        timing = next(c for c in results if c.name == "timing.redrive_within_tolerance")
        self.assertFalse(timing.ok)
        passed, failures = checks.verdict(results)
        self.assertTrue(passed)
        self.assertIn(timing, failures)

    def test_every_advisory_names_its_promotion_criterion(self):
        results = checks.failure_path(EXPECTED, MEASURED_FAILURE)
        for check in results:
            if not check.gating:
                self.assertIn("romote", check.note,
                              f"{check.name} is advisory with no stated path to gating")


if __name__ == "__main__":
    unittest.main()
