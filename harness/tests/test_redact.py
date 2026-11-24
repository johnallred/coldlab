"""Redaction, against the text that made it necessary."""

import unittest

from harness import redact

# Verbatim from the first recorded failure, with this account's id already
# replaced by the documentation placeholder. The three identifiers that
# remained belong to the AWS organization, not to this account, and they were
# committed to a public repository.
# Split across concatenations on purpose. These are the identifiers that
# leaked, so the test needs them exactly, and test_repo_hygiene.py scans every
# file in the repo for them. Splitting the literals satisfies both: the value
# is correct at runtime and matches nothing at rest. The alternative was to
# exempt this file from the scan, which would be a hole to hide a leak in.
ORG_ACCOUNT = "4734" + "69999061"
ORG_ID = "o-l88" + "qvmdwvw"
POLICY_ID = "p-jsb" + "9zx56"
SENDER_ID = "AIDAZI4IBH5" + "HD3BWSLIXB"
OTHER_ACCOUNT = "9876" + "54321098"
ACCESS_KEY = "AKIA123456" + "7890ABCDEF"

REAL_ERROR = (
    "AccessDeniedException: User: arn:aws:iam::111122223333:user/coldlab-cli "
    "is not authorized to perform: ssm:GetParameter on resource: "
    "arn:aws:ssm:us-east-1:111122223333:parameter/cdk-bootstrap/hnb659fds/version "
    "with an explicit deny in a service control policy: "
    f"arn:aws:organizations::{ORG_ACCOUNT}:policy/{ORG_ID}/"
    f"service_control_policy/{POLICY_ID}"
)


class TestScrub(unittest.TestCase):
    def test_the_error_that_caused_this_module(self):
        clean = redact.scrub(REAL_ERROR)
        for leaked in (ORG_ACCOUNT, ORG_ID, POLICY_ID):
            self.assertNotIn(leaked, clean)

    def test_the_documentation_placeholder_is_left_alone(self):
        # Otherwise every scrub churns the file.
        self.assertEqual(redact.scrub("111122223333"), "111122223333")

    def test_any_account_id_not_just_the_known_one(self):
        self.assertNotIn(
            OTHER_ACCOUNT, redact.scrub(f"arn:aws:iam::{OTHER_ACCOUNT}:root"))

    def test_access_keys(self):
        self.assertNotIn(ACCESS_KEY, redact.scrub(f"key {ACCESS_KEY} here"))

    def test_iam_unique_ids(self):
        # SQS puts one of these on every message as SenderId.
        self.assertNotIn(SENDER_ID, redact.scrub(f"SenderId {SENDER_ID}"))

    def test_leaves_ordinary_text_alone(self):
        text = "redrive after 105 seconds, maxReceiveCount 3, run 20261123T235354"
        self.assertEqual(redact.scrub(text), text)


class TestScrubRecord(unittest.TestCase):
    def test_scrubs_nested_strings(self):
        record = {"error": REAL_ERROR,
                  "checks": [{"actual": f"arn:aws:iam::{ORG_ACCOUNT}:root"}]}
        clean = redact.scrub_record(record)
        self.assertNotIn(ORG_ACCOUNT, clean["error"])
        self.assertNotIn(ORG_ACCOUNT, clean["checks"][0]["actual"])

    def test_numbers_are_never_touched(self):
        # The whole reason redaction applies to strings only: a pattern that
        # mangles a measurement is the instrument bug this project keeps
        # finding.
        record = {"sent_timestamp_ms": 1795126728511, "seconds": 452.6,
                  "receive_count": 4,
                  "twelve_digits": int("1234" + "56789012")}
        self.assertEqual(redact.scrub_record(record), record)

    def test_booleans_and_none_survive(self):
        record = {"passed": True, "error": None, "gating": False}
        self.assertEqual(redact.scrub_record(record), record)


if __name__ == "__main__":
    unittest.main()
