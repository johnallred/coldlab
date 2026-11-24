"""ARN resolution. The stale-index bug lives here."""

import unittest

from harness import arns

REGION = "us-east-2"


class TestResolveCommand(unittest.TestCase):
    def test_the_arn_that_caused_this_module(self):
        # Returned by the tag query after the stack was already deleted.
        arn = ("arn:aws:lambda:us-east-2:111122223333:"
               "event-source-mapping:9372aab3-5b57-45d7-ae15-e1ff60d6eb70")
        self.assertEqual(
            arns.resolve_command(arn, REGION),
            "aws lambda get-event-source-mapping "
            "--uuid 9372aab3-5b57-45d7-ae15-e1ff60d6eb70 --region us-east-2",
        )

    def test_sqs_uses_the_bare_queue_name(self):
        arn = "arn:aws:sqs:us-east-2:111122223333:ColdlabSqsRetry-Downloads22991465"
        self.assertIn("--queue-name ColdlabSqsRetry-Downloads22991465",
                      arns.resolve_command(arn, REGION))

    def test_lambda_function(self):
        arn = "arn:aws:lambda:us-east-2:1:function:ColdlabSqsRetry-Worker11F36D0F"
        self.assertIn("--function-name ColdlabSqsRetry-Worker11F36D0F",
                      arns.resolve_command(arn, REGION))

    def test_s3_bucket(self):
        arn = "arn:aws:s3:::coldlabsqsretry-landingexample"
        self.assertEqual(
            arns.resolve_command(arn, REGION),
            "aws s3api head-bucket --bucket coldlabsqsretry-landingexample",
        )

    def test_iam_role(self):
        arn = "arn:aws:iam::111122223333:role/coldlab-ci-coldlab"
        self.assertIn("--role-name coldlab-ci-coldlab",
                      arns.resolve_command(arn, REGION))

    def test_unknown_service_is_unresolved_not_clean(self):
        # The safe default when a resolver is missing is "I could not check",
        # which checks.teardown counts as a failure.
        arn = "arn:aws:kinesis:us-east-2:1:stream/whatever"
        self.assertIsNone(arns.resolve_command(arn, REGION))

    def test_unknown_lambda_subtype_is_unresolved(self):
        arn = "arn:aws:lambda:us-east-2:1:layer:thing"
        self.assertIsNone(arns.resolve_command(arn, REGION))

    def test_garbage_is_unresolved(self):
        self.assertIsNone(arns.resolve_command("not-an-arn", REGION))


if __name__ == "__main__":
    unittest.main()
