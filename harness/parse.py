"""Turning AWS CLI output into values. Pure functions, no AWS, no I/O.

Every parser here exists because the harness reads the same output a student
reads. They are separated from the commands so they can be tested without
credentials, which is most of what makes this harness testable at all.
"""

from __future__ import annotations


def stack_outputs(payload) -> dict:
    """{OutputKey: OutputValue} from `describe-stacks`."""
    stacks = payload.get("Stacks") or []
    if not stacks:
        return {}
    return {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}


def queue_depth(payload) -> int:
    """ApproximateNumberOfMessages from `get-queue-attributes`.

    Depth, not a count of what a receive returned. A long poll asking for ten
    messages returned one of the two actually in the queue during the first
    hand run of this lab, so counting receives undercounts.
    """
    attributes = payload.get("Attributes") or {}
    return int(attributes.get("ApproximateNumberOfMessages", 0))


def first_message(payload) -> dict | None:
    """The first message from `receive-message`, or None.

    None means this poll returned nothing, which is NOT the same as the queue
    being empty. A default short poll samples a subset of the servers holding
    the queue; ask `queue_depth` about emptiness.
    """
    messages = payload.get("Messages") or []
    return messages[0] if messages else None


def receive_count(message: dict) -> int:
    return int(message["Attributes"]["ApproximateReceiveCount"])


def sent_timestamp_ms(message: dict) -> int:
    return int(message["Attributes"]["SentTimestamp"])


def tagged_arns(payload) -> list[str]:
    """ARNs from `resourcegroupstaggingapi get-resources`.

    These are candidates for a leak, never a verdict. The tagging API is an
    eventually-consistent index: it listed a Lambda event source mapping after
    CloudFormation had already reported the stack deleted.
    """
    return [r["ResourceARN"] for r in payload.get("ResourceTagMappingList", [])]


def bucket_keys(stdout: str) -> list[str]:
    """Keys from `aws s3 ls s3://bucket/prefix/` text output.

    Lines look like `2026-11-19 14:31:21         57 invoice-9001.csv`, and
    `PRE subdir/` lines are directories rather than objects.
    """
    keys = []
    for line in stdout.splitlines():
        parts = line.split()
        if not parts or parts[0] == "PRE":
            continue
        if len(parts) >= 4:
            keys.append(parts[3])
    return keys
