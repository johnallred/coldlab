"""The lab's steps, hardcoded. Phase 3 replaces this module with extraction.

Phase 2 hardcodes the steps; Phase 3 parses them out of `lab/sqs-retry/lab.md`
so that editing the lab document changes what the harness runs. The point of
this file is therefore its *shape*, not its contents: `extract.py` has to
produce exactly this list of `Step` objects and nothing in `run.py` may change.

One deliberate difference between what a student does and what the harness
does, and it is the only one. A student is told to `sleep`. The harness polls
instead, because a fixed sleep either wastes time or reports a failure that was
merely early. So a wait in the lab document becomes a `wait_for` condition
here, named rather than timed. Every other command is run verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Step:
    name: str
    #: A shell command, taken verbatim from the lab document.
    command: str | None = None
    #: A condition `run.py` knows how to poll, used in place of a `sleep`.
    wait_for: str | None = None
    #: How long to keep polling, seconds.
    timeout: int = 360


def lab_steps(region: str) -> list[Step]:
    """The SQS retry lab, in the order a student performs it."""
    return [
        Step(
            "send the message that always fails",
            command=(
                f'aws sqs send-message --region {region} --queue-url "$Q" '
                "--message-body "
                "'{\"file\":\"invoice-8812.csv\",\"fail_until\":99}'"
            ),
        ),
        Step(
            "wait for the redrive to the dead-letter queue",
            wait_for="dlq_has_message",
            timeout=420,
        ),
        Step(
            "read the dead-letter queue",
            # Long poll, and exactly once per run: the receive count is only
            # the arrival value on the first read, and reading again
            # increments it.
            command=(
                f'aws sqs receive-message --region {region} --queue-url "$DLQ" '
                "--attribute-names All --wait-time-seconds 20 "
                "--max-number-of-messages 1"
            ),
        ),
        Step(
            "confirm the failing file never landed",
            command='aws s3 ls "s3://$BUCKET/landed/"',
        ),
        Step(
            "send the message that recovers on the third attempt",
            command=(
                f'aws sqs send-message --region {region} --queue-url "$Q" '
                "--message-body "
                "'{\"file\":\"invoice-9001.csv\",\"fail_until\":3}'"
            ),
        ),
        Step(
            "wait for the file to land",
            wait_for="success_file_present",
            timeout=300,
        ),
        Step(
            "confirm the file landed",
            command='aws s3 ls "s3://$BUCKET/landed/"',
        ),
    ]
