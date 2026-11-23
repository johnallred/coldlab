"""Resolving a tagged ARN against the service that owns it. Pure, no AWS.

The whole reason this module exists: on the first real teardown of this lab,
`resourcegroupstaggingapi get-resources` listed a Lambda event source mapping
after CloudFormation had reported the stack gone. Asked directly, Lambda said
the resource did not exist. The index was stale.

A leak detector that reports leaks which are not there gets ignored within a
week, and then the one real leak is ignored with it. So every ARN the tag
query returns is a question, and this module says how to ask it.
"""

from __future__ import annotations

# An ARN that nothing here knows how to resolve is reported as UNRESOLVED
# rather than as clean. When you cannot check, the honest answer is "I could
# not confirm this is gone", never "it is gone".
UNRESOLVED = None


def parse(arn: str) -> dict:
    """arn:partition:service:region:account:resource..."""
    parts = arn.split(":", 5)
    if len(parts) < 6 or parts[0] != "arn":
        return {}
    return {
        "partition": parts[1],
        "service": parts[2],
        "region": parts[3],
        "account": parts[4],
        "resource": parts[5],
    }


def resolve_command(arn: str, region: str) -> str | None:
    """The command that answers "does this still exist?", or None.

    A command that exits non-zero means the resource is gone and the tag index
    is stale. A command that exits zero means a real leak.
    """
    bits = parse(arn)
    service, resource = bits.get("service"), bits.get("resource", "")

    if service == "sqs":
        # sqs ARNs carry the bare queue name as the resource.
        return f"aws sqs get-queue-url --queue-name {resource} --region {region}"

    if service == "lambda":
        kind, _, name = resource.partition(":")
        if kind == "function":
            return f"aws lambda get-function --function-name {name} --region {region}"
        if kind == "event-source-mapping":
            return f"aws lambda get-event-source-mapping --uuid {name} --region {region}"
        return UNRESOLVED

    if service == "s3":
        return f"aws s3api head-bucket --bucket {resource}"

    if service == "logs":
        kind, _, name = resource.partition(":")
        if kind == "log-group":
            return (
                f"aws logs describe-log-groups --region {region} "
                f"--log-group-name-prefix {name} "
                f"--query \"logGroups[?logGroupName=='{name}'] | [0].logGroupName\" "
                f"--output text"
            )
        return UNRESOLVED

    if service == "iam":
        kind, _, name = resource.partition("/")
        if kind == "role":
            return f"aws iam get-role --role-name {name}"
        if kind == "policy":
            return f"aws iam get-policy --policy-arn {arn}"
        return UNRESOLVED

    return UNRESOLVED
