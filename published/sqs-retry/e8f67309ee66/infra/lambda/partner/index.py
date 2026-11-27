"""Stands in for the partner endpoint the lab downloads from.

Deterministic on purpose. The worker passes the SQS receive count, and this
fails while that count is below the message's `fail_until`. No stored state, so
two runs of the lab behave identically, which is what makes the result
something a student can be told in advance.
"""

import base64


class PartnerUnavailable(Exception):
    """A transient failure. The worker is meant to retry this one."""


def handler(event, context):
    attempt = int(event.get("attempt", 1))
    fail_until = int(event.get("fail_until", 3))
    name = event.get("file", "unknown.csv")

    if attempt < fail_until:
        raise PartnerUnavailable(
            f"503 Service Unavailable on attempt {attempt} of {name}; "
            f"this endpoint succeeds from attempt {fail_until}"
        )

    body = f"id,amount\n1,42.00\n# {name} served on attempt {attempt}\n".encode()
    return {"file": name, "attempt": attempt, "body_b64": base64.b64encode(body).decode()}
