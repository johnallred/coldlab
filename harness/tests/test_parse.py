"""Parsers against real AWS CLI output, copied from the first hand run."""

import unittest

from harness import parse


class TestStackOutputs(unittest.TestCase):
    def test_reads_outputs(self):
        payload = {"Stacks": [{"Outputs": [
            {"OutputKey": "QueueUrl", "OutputValue": "https://sqs/q"},
            {"OutputKey": "LandingBucket", "OutputValue": "bucket-x"},
        ]}]}
        self.assertEqual(
            parse.stack_outputs(payload),
            {"QueueUrl": "https://sqs/q", "LandingBucket": "bucket-x"},
        )

    def test_missing_stack_is_empty(self):
        self.assertEqual(parse.stack_outputs({}), {})


class TestQueueDepth(unittest.TestCase):
    def test_real_payload(self):
        self.assertEqual(
            parse.queue_depth({"Attributes": {"ApproximateNumberOfMessages": "2"}}),
            2,
        )

    def test_absent_is_zero(self):
        self.assertEqual(parse.queue_depth({}), 0)


class TestFirstMessage(unittest.TestCase):
    # Verbatim from the run on 2026-11-19, receipt handle shortened.
    REAL = {"Messages": [{
        "MessageId": "8b2487d2-6625-4318-a62e-3a1afea3a351",
        "ReceiptHandle": "AQEBFqm2",
        "Body": '{"file":"invoice-8812.csv","fail_until":99}',
        "Attributes": {
            # Redacted: the real value is an IAM unique id for this account.
            # No parser reads this field.
            "SenderId": "AIDAEXAMPLEPRINCIPALID",
            "ApproximateFirstReceiveTimestamp": "1795126728517",
            "ApproximateReceiveCount": "5",
            "SentTimestamp": "1795126728511",
            "DeadLetterQueueSourceArn": "arn:aws:sqs:us-east-2:111122223333:q",
        },
    }]}

    def test_reads_the_measured_values(self):
        message = parse.first_message(self.REAL)
        self.assertEqual(parse.receive_count(message), 5)
        self.assertEqual(parse.sent_timestamp_ms(message), 1795126728511)

    def test_empty_poll_is_none_not_empty_queue(self):
        # A short poll that found nothing returns {}. This must be
        # distinguishable from an empty queue, which is what queue_depth is
        # for. Twenty minutes were lost to conflating the two.
        self.assertIsNone(parse.first_message({}))


class TestTaggedArns(unittest.TestCase):
    def test_reads_arns(self):
        payload = {"ResourceTagMappingList": [
            {"ResourceARN": "arn:aws:lambda:us-east-2:1:event-source-mapping:abc",
             "Tags": [{"Key": "coldlab:managed", "Value": "true"}]},
        ]}
        self.assertEqual(
            parse.tagged_arns(payload),
            ["arn:aws:lambda:us-east-2:1:event-source-mapping:abc"],
        )

    def test_clean_is_empty(self):
        self.assertEqual(parse.tagged_arns({"ResourceTagMappingList": []}), [])


class TestBucketKeys(unittest.TestCase):
    def test_real_output(self):
        stdout = "2026-11-19 14:31:21         57 invoice-9001.csv\n"
        self.assertEqual(parse.bucket_keys(stdout), ["invoice-9001.csv"])

    def test_skips_prefixes_and_blanks(self):
        stdout = ("                           PRE nested/\n"
                  "\n"
                  "2026-11-19 14:31:21         57 invoice-9001.csv\n")
        self.assertEqual(parse.bucket_keys(stdout), ["invoice-9001.csv"])

    def test_empty_listing(self):
        self.assertEqual(parse.bucket_keys(""), [])


if __name__ == "__main__":
    unittest.main()
