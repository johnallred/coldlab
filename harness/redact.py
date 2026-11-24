"""Scrubbing identifiers out of anything the harness commits.

health/health.jsonl is committed to a public repository and holds the raw text
of whatever failed. That text is not ours: it is whatever AWS put in an error,
and AWS errors routinely name account ids, organization ids, policy ids and
principals.

The first recorded failure proved it. A CDK bootstrap error carried the
organization's management account id, its organization id and the id of the
service control policy that denied the call, none of which belong to this
account and all of which were committed to a public repo. The account id was
spotted and scrubbed by hand; the organization's three identifiers were not,
because a hand scrub finds what you thought to look for.

So redaction happens on the way in, not by remembering. Applied to string
values only: JSON numbers are left alone, so a measurement can never be
silently mangled by a pattern that happens to match it.
"""

from __future__ import annotations

import re

#: (pattern, replacement). Replacements are AWS's own documentation examples
#: where one exists, so a reader can tell a redaction from a real value.
RULES: list[tuple[re.Pattern, str]] = [
    # A 12-digit AWS account id. 111122223333 is AWS's documentation
    # placeholder, so it is also the replacement and is left unchanged.
    (re.compile(r"\b\d{12}\b"), "111122223333"),
    # Organizations ids, and the policy ids inside a service control policy
    # ARN. These identify the organization rather than this account.
    (re.compile(r"\bo-[a-z0-9]{10,34}\b"), "o-exampleorgid"),
    (re.compile(r"\bp-[a-z0-9]{8,}\b"), "p-examplepolicyid"),
    # Credentials, defensively. Nothing should ever put one here.
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "AKIAIOSFODNN7EXAMPLE"),
    # IAM unique ids, which appear as SenderId on an SQS message and as the
    # principal in some error text.
    (re.compile(r"\b(?:AIDA|AROA|AIPA|ANPA|AGPA)[A-Z0-9]{16,}\b"),
     "AIDAEXAMPLEPRINCIPALID"),
]


def scrub(text: str) -> str:
    for pattern, replacement in RULES:
        text = pattern.sub(replacement, text)
    return text


def scrub_record(value):
    """Recursively scrub every string in a record, leaving numbers alone."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {key: scrub_record(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_record(item) for item in value]
    return value
