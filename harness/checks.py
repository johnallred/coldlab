"""The assertions, as pure functions over measured observations.

Separated from the AWS calls on purpose: these are the part worth testing, and
they test without credentials, a deployed stack, or a network.

Two kinds of check. A **gating** check decides the exit code. An **advisory**
check is evaluated, printed and recorded every run, but does not fail the run
yet, because its stability has not been measured over enough runs to gate on.
Each advisory carries the criterion for promoting it. An advisory check is not
a check that cannot fail: it fails loudly in the report and in health.jsonl,
and the only thing it does not do is set the exit code.
"""

from __future__ import annotations

from dataclasses import dataclass


#: What would have to be true to make `timing.redrive_within_tolerance` a
#: gating check. Written as data rather than as a note saying "use a figure
#: taken from recorded runs", because a note that defers to judgment is a note
#: nobody actions, and because the numbers then live in exactly one place.
#:
#: The thresholds are a judgment and not a measurement, which is worth saying
#: plainly. Ten observations across seven distinct days is enough spread to
#: see day-to-day variation rather than one afternoon's; the first three
#: observations all came from a two-hour window on one machine, so a band
#: drawn from them would describe that window. The margins are chosen to
#: absorb the spread seen so far plus a cold-start outlier.
#:
#: What makes the criterion honest is not the numbers but the last two keys. A
#: band that fires without a real cause may be widened once, and that widening
#: is recorded. If it fires spuriously again the check is retired rather than
#: widened a second time, because a gate widened repeatedly is a gate nobody
#: reads. Retirement is a real outcome here and not a failure: the receive
#: count advisory was retired by evidence, and this one may go the same way if
#: the spread stays near 21% of the median or turns out to drift by weekday.
#:
#: `min_observations` counts observations, not nights. A run that aborts before
#: the redrive records none, which is why five runs have produced three.
REDRIVE_PROMOTION = {
    "min_observations": 10,
    "min_distinct_days": 7,
    # The band is computed from the record: low = factor x the minimum
    # observed, high = factor x the maximum observed. Never a multiple of the
    # derived nominal, which is what the current advisory band is and why it
    # is six times wider than the observed spread.
    "band_low_factor": 0.6,
    "band_high_factor": 1.6,
    # Above this, the timing is not determinate enough to assert at all and
    # the check is retired rather than promoted, the way the receive count
    # was. (max - min) / median, so the first three observations sit at 0.21.
    # The threshold is a judgment like the rest; what it buys is that the
    # retire outcome is decided by the record rather than by whoever looks.
    "max_relative_spread": 0.5,
    "widenings_allowed": 1,
    "after_a_second_spurious_failure": "retire",
}


@dataclass
class Check:
    name: str
    ok: bool
    expected: object
    actual: object
    gating: bool = True
    note: str = ""

    def line(self) -> str:
        mark = "PASS" if self.ok else ("FAIL" if self.gating else "warn")
        tail = "" if self.ok else f"  expected {self.expected!r}, got {self.actual!r}"
        return f"[{mark}] {self.name}{tail}"


def failure_path(expected: dict, obs: dict) -> list[Check]:
    spec = expected["failure_path"]
    dlq = spec["dead_letter_queue"]
    max_receive = expected["measured_against"]["max_receive_count"]
    checks = []

    checks.append(Check(
        "dlq.depth",
        obs["dlq_depth"] == dlq["depth_increases_by"],
        dlq["depth_increases_by"], obs["dlq_depth"],
        note="Depth from get-queue-attributes, never a count of what a "
             "receive returned.",
    ))

    # Gating form. At-least-once delivery means an extra receive is legal, so
    # the floor is what the semantics guarantee and the exact value is
    # advisory below.
    floor = max_receive + 1
    checks.append(Check(
        "dlq.receive_count_at_least_max_plus_one",
        obs["receive_count"] >= floor,
        f">= {floor}", obs["receive_count"],
        note="Redrive fires on the receive that exceeds maxReceiveCount, so "
             "arrival is maxReceiveCount + 1. The harness's own read is one "
             "more.",
    ))

    # This started life as an exact-value check with a note promising to
    # promote it to gating after twenty agreeing runs. The second observation
    # disagreed with the first, 5 by hand and 4 from the harness, so the exact
    # value is not an expectation and never was. It is now a drift detector:
    # it fires on a value never seen before, which is worth a look, and it
    # must not gate. The floor above is what gates.
    observed = dlq.get("receive_count_observed") or [dlq["receive_count_on_first_read"]]
    checks.append(Check(
        "dlq.receive_count_in_observed_set",
        obs["receive_count"] in observed,
        f"one of {observed}", obs["receive_count"],
        gating=False,
        note="Advisory, and deliberately never to be promoted: two runs of "
             "the same lab produced different counts, so SQS does not promise "
             "this. Only true on the first read of a message, so the harness "
             "must read each dead-letter message exactly once per run.",
    ))

    # SentTimestamp survives the redrive, so it should still be the moment the
    # harness sent the message rather than the moment SQS gave up on it.
    skew_ms = abs(obs["sent_timestamp_ms"] - obs["sent_at_ms"])
    checks.append(Check(
        "dlq.sent_timestamp_preserved",
        skew_ms < 10_000,
        "within 10s of the original send", f"{skew_ms}ms skew",
        note="A DLQ message's age is measured from its first send, not from "
             "when it was given up on.",
    ))

    failing_file = spec.get("file") or "invoice-8812.csv"
    checks.append(Check(
        "bucket.failing_file_absent",
        failing_file not in obs["bucket_keys"],
        f"{failing_file} absent", obs["bucket_keys"],
    ))

    nominal = spec["redrive_after_seconds"]
    observed = obs["redrive_seconds"]
    checks.append(Check(
        "timing.redrive_within_tolerance",
        0.5 * nominal <= observed <= 3.0 * nominal,
        f"{0.5 * nominal:.0f}-{3.0 * nominal:.0f}s", round(observed, 1),
        gating=False,
        note="Advisory, and wide on purpose: Lambda cold start and SQS "
             "polling both add variance. The criterion for promoting it is "
             "REDRIVE_PROMOTION in this module, as data rather than as "
             "judgment: 10 observations over 7 distinct days, the band "
             "computed from the record, one widening permitted and recorded, "
             "then retirement rather than a second widening.",
    ))

    return checks


def success_path(expected: dict, obs: dict) -> list[Check]:
    spec = expected["success_path"]
    key = spec["bucket_key"].split("/")[-1]
    return [Check(
        "bucket.success_file_present",
        key in obs["bucket_keys"],
        f"{key} present", obs["bucket_keys"],
    )]


def teardown(expected: dict, obs: dict) -> list[Check]:
    """obs['tagged'] is a list of {'arn', 'status'} with status in
    {'gone', 'leak', 'unresolved'}."""
    checks = [Check(
        "teardown.stack_deleted",
        obs["stack_exists"] is False,
        "stack absent", "present" if obs["stack_exists"] else "absent",
    )]

    tagged = obs.get("tagged") or []
    leaks = [t["arn"] for t in tagged if t["status"] == "leak"]
    unresolved = [t["arn"] for t in tagged if t["status"] == "unresolved"]

    checks.append(Check(
        "teardown.no_leaks",
        not leaks,
        "no surviving tagged resources", leaks,
        note="A resource the owning service still describes. This is the one "
             "that costs money.",
    ))

    checks.append(Check(
        "teardown.all_tagged_resolved",
        not unresolved,
        "every tagged ARN resolvable", unresolved,
        note="An ARN no resolver in harness/arns.py understands. Counted as a "
             "failure because 'I could not check' is not 'it is gone'. Fix by "
             "adding a resolver, not by lowering the bar.",
    ))

    return checks


def verdict(checks: list[Check]) -> tuple[bool, list[Check]]:
    """(passed, failures). Only gating checks decide the exit code."""
    failures = [c for c in checks if not c.ok]
    passed = not any(c.gating for c in failures)
    return passed, failures
