"""The whole loop, against a fake AWS.

No credentials, no network, no cost, and it still exercises provisioning,
the step order, the observations, the verdict, teardown and the health record.

The test that matters most here is `test_teardown_runs_when_the_steps_fail`. A
harness that leaks resources when it fails leaks them exactly when nobody is
watching.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import report, run as runner
from harness.shell import Result

OUTPUTS = {"Stacks": [{"Outputs": [
    {"OutputKey": "QueueUrl", "OutputValue": "https://sqs/downloads"},
    {"OutputKey": "DeadLetterUrl", "OutputValue": "https://sqs/deadletters"},
    {"OutputKey": "LandingBucket", "OutputValue": "coldlab-landing"},
]}]}

DLQ_MESSAGE = {"Messages": [{
    "MessageId": "8b2487d2",
    "Body": '{"file":"invoice-8812.csv","fail_until":99}',
    "Attributes": {
        "ApproximateReceiveCount": "5",
        "SentTimestamp": "1795126728511",
        "ApproximateFirstReceiveTimestamp": "1795126728517",
    },
}]}

STALE_TAG = {"ResourceTagMappingList": [
    {"ResourceARN": "arn:aws:lambda:us-east-2:1:event-source-mapping:9372aab3"}
]}


class FakeAws:
    """Dispatches on the command text, the way the real CLI would."""

    def __init__(self, *, dlq_message=DLQ_MESSAGE, tagged=STALE_TAG,
                 probe_ok=False, destroy_ok=True, deploy_ok=True):
        self.commands = []
        self.calls = []
        self.deploy_ok = deploy_ok
        self.destroyed = False
        self.success_landed = False
        self.dlq_message = dlq_message
        self.tagged = tagged
        self.probe_ok = probe_ok
        self.destroy_ok = destroy_ok

    def __call__(self, command, cwd=None, env=None, timeout=600, check=False):
        self.commands.append(command)
        self.calls.append((command, env or {}))

        def ok(stdout=""):
            return Result(command, 0, stdout, "")

        def fail(stderr="does not exist"):
            result = Result(command, 254, "", stderr)
            if check:
                raise RuntimeError(f"command failed: {command}")
            return result

        if command.startswith("cdk deploy"):
            return ok() if self.deploy_ok else fail("bootstrap version check failed")
        if command.startswith("cdk destroy"):
            self.destroyed = True
            return ok() if self.destroy_ok else fail("destroy failed")
        if "describe-stacks" in command:
            return fail() if self.destroyed else ok(json.dumps(OUTPUTS))
        if "send-message" in command:
            if "9001" in command:
                self.success_landed = True
            return ok(json.dumps({"MessageId": "x"}))
        if "get-queue-attributes" in command:
            return ok(json.dumps({"Attributes": {"ApproximateNumberOfMessages": "1"}}))
        if "receive-message" in command:
            return ok(json.dumps(self.dlq_message))
        if "s3 ls" in command:
            listing = ("2026-11-19 14:31:21         57 invoice-9001.csv\n"
                       if self.success_landed else "")
            return ok(listing)
        if "resourcegroupstaggingapi" in command:
            return ok(json.dumps(self.tagged))
        if "get-event-source-mapping" in command:
            return ok(json.dumps({"UUID": "x"})) if self.probe_ok else fail()
        raise AssertionError(f"unexpected command: {command}")


class HarnessCase(unittest.TestCase):
    def go(self, fake, extra_args=()):
        """Run main() against a fake, in a throwaway health directory."""
        with tempfile.TemporaryDirectory() as tmp:
            # A controlled clock, so redrive_seconds lands near the measured
            # 105s instead of the zero a fake run would otherwise produce.
            clock = iter([1795126728000] + [1795126728000 + 106_000] * 50)
            with mock.patch.object(runner, "run", fake), \
                 mock.patch.object(runner, "now_ms", lambda: next(clock)):
                code = runner.main(["--health-dir", tmp, *extra_args])
            records = report.load_records(Path(tmp) / "health.jsonl")
            return code, records, (Path(tmp) / "HEALTH.md").read_text(encoding="utf-8")


class TestGreenRun(HarnessCase):
    def test_exits_zero(self):
        code, records, health = self.go(FakeAws())
        self.assertEqual(code, 0, [c for c in records[0]["checks"] if not c["ok"]])

    def test_records_run_completed(self):
        _, records, _ = self.go(FakeAws())
        completed = next(c for c in records[0]["checks"]
                         if c["name"] == "run.completed")
        self.assertTrue(completed["ok"])

    def test_records_one_passing_run(self):
        _, records, health = self.go(FakeAws())
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["passed"])
        self.assertIn("Pass rate: **100%**", health)

    def test_measures_what_the_hand_run_measured(self):
        _, records, _ = self.go(FakeAws())
        measurements = records[0]["measurements"]
        self.assertEqual(measurements["receive_count"], 5)
        self.assertEqual(measurements["dlq_depth"], 1)
        self.assertEqual(measurements["sent_timestamp_ms"], 1795126728511)

    def test_runs_the_steps_in_order(self):
        fake = FakeAws()
        self.go(fake)
        sends = [c for c in fake.commands if "send-message" in c]
        self.assertIn("8812", sends[0])
        self.assertIn("9001", sends[1])

    def test_reads_the_dead_letter_queue_exactly_once(self):
        # The receive count is only the arrival value on the first read.
        fake = FakeAws()
        self.go(fake)
        self.assertEqual(
            sum(1 for c in fake.commands if "receive-message" in c), 1)

    def test_long_polls_the_dead_letter_queue(self):
        fake = FakeAws()
        self.go(fake)
        receive = next(c for c in fake.commands if "receive-message" in c)
        self.assertIn("--wait-time-seconds", receive)

    def test_resolves_the_stale_tag_rather_than_reporting_a_leak(self):
        fake = FakeAws()
        code, records, _ = self.go(fake)
        self.assertTrue(any("get-event-source-mapping" in c for c in fake.commands))
        self.assertEqual(code, 0)


class TestRegionIsPinned(HarnessCase):
    """The harness must not assert against one region and deploy to another.

    `app.py` reads COLDLAB_REGION. If the harness does not set it, the CDK CLI
    supplies CDK_DEFAULT_REGION from whatever the credentials resolve to, and
    the stack follows the credentials instead of the lab. That put a real
    deploy into us-east-1, where an Organizations policy denied it.
    """

    def cdk_env(self, fake, verb):
        command, env = next((c, e) for c, e in fake.calls if c.startswith(verb))
        return env

    def test_deploy_gets_the_region(self):
        fake = FakeAws()
        self.go(fake, ["--region", "us-east-2"])
        env = self.cdk_env(fake, "cdk deploy")
        self.assertEqual(env.get("COLDLAB_REGION"), "us-east-2")
        self.assertEqual(env.get("AWS_DEFAULT_REGION"), "us-east-2")

    def test_destroy_gets_the_same_region(self):
        fake = FakeAws()
        self.go(fake, ["--region", "us-east-2"])
        self.assertEqual(
            self.cdk_env(fake, "cdk destroy").get("COLDLAB_REGION"), "us-east-2")

    def test_a_non_default_region_reaches_cdk(self):
        fake = FakeAws()
        self.go(fake, ["--region", "eu-west-1"])
        self.assertEqual(
            self.cdk_env(fake, "cdk deploy").get("COLDLAB_REGION"), "eu-west-1")


class TestFailedProvision(HarnessCase):
    def test_records_a_gating_failure_rather_than_three_green_lines(self):
        fake = FakeAws(deploy_ok=False)
        code, records, _ = self.go(fake)
        self.assertEqual(code, 1)
        completed = next(c for c in records[0]["checks"]
                         if c["name"] == "run.completed")
        self.assertFalse(completed["ok"])
        self.assertTrue(completed["gating"])

    def test_still_attempts_teardown(self):
        fake = FakeAws(deploy_ok=False)
        self.go(fake)
        self.assertTrue(fake.destroyed)


class TestTeardown(HarnessCase):
    def test_teardown_runs_when_the_steps_fail(self):
        # The long poll finds nothing despite a non-zero depth, which aborts
        # the run. Teardown must still happen.
        fake = FakeAws(dlq_message={"Messages": []})
        code, records, _ = self.go(fake)
        self.assertEqual(code, 1)
        self.assertTrue(fake.destroyed, "a failed run must still tear down")
        self.assertIn("long poll returned no message", records[0]["error"])

    def test_teardown_is_verified_even_when_destroy_exits_nonzero(self):
        fake = FakeAws(destroy_ok=False)
        code, records, _ = self.go(fake)
        names = [c["name"] for c in records[0]["checks"]]
        self.assertIn("teardown.stack_deleted", names)
        self.assertEqual(code, 0)

    def test_a_real_leak_fails_the_run(self):
        # The probe succeeds, so the tagged resource genuinely survived.
        fake = FakeAws(probe_ok=True)
        code, records, _ = self.go(fake)
        self.assertEqual(code, 1)
        leak = next(c for c in records[0]["checks"] if c["name"] == "teardown.no_leaks")
        self.assertFalse(leak["ok"])

    def test_an_unresolvable_tagged_arn_fails_the_run(self):
        fake = FakeAws(tagged={"ResourceTagMappingList": [
            {"ResourceARN": "arn:aws:kinesis:us-east-2:1:stream/mystery"}]})
        code, records, _ = self.go(fake)
        self.assertEqual(code, 1)
        unresolved = next(c for c in records[0]["checks"]
                          if c["name"] == "teardown.all_tagged_resolved")
        self.assertFalse(unresolved["ok"])

    def test_keep_skips_teardown_and_says_so(self):
        fake = FakeAws()
        code, records, _ = self.go(fake, ["--keep"])
        self.assertFalse(fake.destroyed)
        names = [c["name"] for c in records[0]["checks"]]
        self.assertNotIn("teardown.stack_deleted", names)


if __name__ == "__main__":
    unittest.main()
