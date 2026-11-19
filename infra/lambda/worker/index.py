"""Downloads one file per message and deletes the message only on success.

The whole lesson is in what this does NOT do. There is no retry loop, no
attempt counter, and no schedule. A failure returns the message to the queue by
declining to delete it, and the queue's redrive policy decides when to give up.
"""

import base64
import json
import os

import boto3

s3 = boto3.client("s3")
lam = boto3.client("lambda")
sqs = boto3.client("sqs")

BUCKET = os.environ["LANDING_BUCKET"]
PARTNER = os.environ["PARTNER_FUNCTION"]
QUEUE_URL = os.environ["QUEUE_URL"]

BASE_BACKOFF = int(os.environ.get("BASE_BACKOFF_SECONDS", "15"))
CEILING = 3_600  # the API ceiling is 43,200; this lab never needs it


def backoff_seconds(receive_count: int) -> int:
    """Exponential, capped. No jitter, because a lab wants a predictable wait."""
    return min(CEILING, BASE_BACKOFF * 2 ** max(0, receive_count - 1))


def handler(event, context):
    failures = []

    for record in event["Records"]:
        message_id = record["messageId"]
        # SQS maintains this. It is the attempt counter you would otherwise
        # have built a table for.
        attempt = int(record["attributes"]["ApproximateReceiveCount"])
        body = json.loads(record["body"])

        try:
            result = lam.invoke(
                FunctionName=PARTNER,
                Payload=json.dumps(
                    {
                        "file": body["file"],
                        "fail_until": body.get("fail_until", 3),
                        "attempt": attempt,
                    }
                ).encode(),
            )
            payload = json.loads(result["Payload"].read())
            if "FunctionError" in result:
                raise RuntimeError(payload.get("errorMessage", "partner failed"))

            s3.put_object(
                Bucket=BUCKET,
                # Deterministic key: a duplicate delivery overwrites rather
                # than making a second copy. At-least-once is the contract.
                Key=f"landed/{body['file']}",
                Body=base64.b64decode(payload["body_b64"]),
            )
            print(f"ok {body['file']} on attempt {attempt}")

        except Exception as error:  # noqa: BLE001 - the lab retries everything
            wait = backoff_seconds(attempt)
            print(f"attempt {attempt} failed for {body['file']}: {error}; waiting {wait}s")
            # Setting the visibility timeout is what turns redelivery into
            # backoff. SQS does not grow it on its own.
            sqs.change_message_visibility(
                QueueUrl=QUEUE_URL,
                ReceiptHandle=record["receiptHandle"],
                VisibilityTimeout=wait,
            )
            failures.append({"itemIdentifier": message_id})

    # Only the named messages come back. Without this, one bad file drags the
    # whole batch back and inflates every receive count toward the DLQ.
    return {"batchItemFailures": failures}
