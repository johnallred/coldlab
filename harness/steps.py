"""The step model, and where the steps come from.

Phase 2 hardcoded the lab's commands in this module. Phase 3 deleted that list:
`lab_steps` now reads `lab/<lab>/lab.md` and extracts them, so editing the lab
document changes what the harness runs without touching harness code.

The shape of `Step` is the interface between the two halves. It did not change
during that migration, which was the test of whether Phase 2 got it right.

One deliberate difference between what a student does and what the harness
does, and only one. A student is told to `sleep`. The harness polls a named
condition instead, because a fixed sleep either wastes time or reports a
failure that was merely early. `KNOWN_CONDITIONS` is the contract: the lab
document may only name a condition the runner can actually poll, and
`extract.validate` rejects the document otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Conditions `run.py` knows how to poll. `run.py` asserts that its own
#: condition table matches this set exactly, so the two cannot drift.
KNOWN_CONDITIONS = frozenset({"dlq_has_message", "success_file_present"})


@dataclass
class Step:
    name: str
    #: A shell command, taken verbatim from the lab document.
    command: str | None = None
    #: A condition `run.py` knows how to poll, used in place of a `sleep`.
    wait_for: str | None = None
    #: How long to keep polling, seconds.
    timeout: int = 360
    #: Exit codes that mean this step worked.
    #:
    #: Not every useful command exits zero. `aws s3 ls` on a prefix with no
    #: objects exits 1, and in the middle of this lab an empty prefix is the
    #: correct state, so treating non-zero as failure fails the lab for
    #: behaving properly. The lab document says so with `# exits N: why`.
    expect_exit: tuple[int, ...] = (0,)


def lab_document(lab: str = "sqs-retry") -> Path:
    return ROOT / "lab" / lab / "lab.md"


def lab_steps(region: str | None = None, lab: str = "sqs-retry") -> list[Step]:
    """The lab's steps, read out of its own document.

    `region` is accepted and unused: the lab document reads `$REGION` from the
    environment like a student's shell does, and `run.py` sets it from
    `--region`. Keeping the parameter means `run.py` did not have to change
    when extraction replaced the hardcoded list.
    """
    from harness.extract import extract  # late, to avoid a circular import

    return extract(lab_document(lab))
