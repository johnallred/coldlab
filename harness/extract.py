"""Pulling the harness's steps out of the lab document.

This is the whole argument of the project in one module. The harness does not
hold its own copy of the lab's commands: it reads the text a student is told to
type and runs that. So the lab document and the thing being tested cannot drift
apart, because they are the same text. A lab that quietly stops matching its
instructions still passes every test you would normally write, and that is the
failure this prevents.

Three directives, written as shell comments so they run harmlessly if a student
copies a whole block:

    # step: <name>
        Name this block's command. Optional; the nearest heading is used
        otherwise.

    # exits <n>: <why>
        This exit code also means success. Repeatable. `aws s3 ls` exits 1 on a
        prefix with no objects, and mid-lab an empty prefix is the correct
        state, so without this the lab fails for behaving properly.

    # not run by the harness: <why>
        Skip this block. For the parts a student does that the harness does
        differently: provisioning, reading stack outputs, tailing logs,
        tearing down.

    # harness waits for: <condition> (timeout <n>s)
        Replace this block's `sleep` with a poll of a named condition. The one
        deliberate difference between student and harness: a fixed sleep either
        wastes time or reports a failure that was merely early, and the second
        kind of mistake is how a lab gets blamed on a student.

The `why` on each directive is required, not decorative. A directive without a
reason is how an exception becomes permanent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from harness.steps import KNOWN_CONDITIONS, Step

FENCE_OPEN = re.compile(r"^```bash\s*$")
FENCE_CLOSE = re.compile(r"^```\s*$")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")

NOT_RUN = re.compile(r"^#\s*not run by the harness\s*:\s*(.+?)\s*$")
EXITS = re.compile(r"^#\s*exits\s+(\d+)\s*:\s*(.+?)\s*$")
WAITS = re.compile(
    r"^#\s*harness waits for\s*:\s*([a-z_]+)"
    r"\s*(?:\(\s*timeout\s+(\d+)\s*s?\s*\))?\s*$"
)
STEP_NAME = re.compile(r"^#\s*step\s*:\s*(.+?)\s*$")

DEFAULT_WAIT_TIMEOUT = 360


class ExtractionError(Exception):
    """The lab document cannot be turned into a runnable step list."""


@dataclass
class Block:
    heading: str
    line_number: int
    commands: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    name: str | None = None
    skip_reason: str | None = None
    exits: list[int] = field(default_factory=list)
    wait_for: str | None = None
    wait_timeout: int | None = None

    @property
    def where(self) -> str:
        return f"line {self.line_number} under {self.heading!r}"


def blocks(text: str) -> list[Block]:
    """Every ```bash block in the document, with its directives parsed."""
    found: list[Block] = []
    heading = "(no heading)"
    current: Block | None = None

    for number, line in enumerate(text.splitlines(), start=1):
        if current is None:
            match = HEADING.match(line)
            if match:
                heading = match.group(1)
            elif FENCE_OPEN.match(line):
                current = Block(heading=heading, line_number=number)
            continue

        if FENCE_CLOSE.match(line):
            found.append(current)
            current = None
            continue

        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("#"):
            current.comments.append(stripped)
            if match := NOT_RUN.match(stripped):
                current.skip_reason = match.group(1)
            elif match := EXITS.match(stripped):
                current.exits.append(int(match.group(1)))
            elif match := WAITS.match(stripped):
                current.wait_for = match.group(1)
                if match.group(2):
                    current.wait_timeout = int(match.group(2))
            elif match := STEP_NAME.match(stripped):
                current.name = match.group(1)
            continue

        current.commands.append(stripped)

    if current is not None:
        raise ExtractionError(
            f"unclosed ```bash block opened at line {current.line_number}")

    return found


def to_step(block: Block, seen: dict[str, int]) -> Step | None:
    """One block to one step, or None when the block is skipped."""
    if block.skip_reason:
        return None

    name = block.name or block.heading
    seen[name] = seen.get(name, 0) + 1
    if seen[name] > 1:
        name = f"{name} ({seen[name]})"

    if block.wait_for:
        if block.commands and not all(
                c.startswith("sleep") for c in block.commands):
            raise ExtractionError(
                f"{block.where}: a 'harness waits for' block may only contain "
                f"a sleep, found {block.commands!r}. Put the commands in their "
                "own block."
            )
        return Step(
            name=name,
            wait_for=block.wait_for,
            timeout=block.wait_timeout or DEFAULT_WAIT_TIMEOUT,
        )

    if len(block.commands) != 1:
        raise ExtractionError(
            f"{block.where}: a runnable block must hold exactly one command, "
            f"found {len(block.commands)}. Split it, or mark the block with "
            "'# not run by the harness: <why>'. The harness parses one "
            "command's output per step."
        )

    return Step(
        name=name,
        command=block.commands[0],
        expect_exit=tuple(sorted({0, *block.exits})),
    )


def validate(steps: list[Step]) -> list[str]:
    """Problems with the extracted steps. Empty means the document is sound.

    Every rule here encodes something a real run measured, so each one exists
    to stop a plausible edit to `lab.md` from silently weakening the test.
    """
    problems: list[str] = []
    runnable = [s for s in steps if s.command]

    reads = [s for s in runnable if "receive-message" in s.command]
    if len(reads) != 1:
        problems.append(
            f"expected exactly one receive-message step, found {len(reads)}. "
            "ApproximateReceiveCount is only the arrival value on the first "
            "read of a message, so a second read changes what the lab "
            "observes."
        )
    for step in reads:
        if "--wait-time-seconds" not in step.command:
            problems.append(
                f"the receive-message step {step.name!r} does not long poll. "
                "A default short poll samples a subset of the servers holding "
                "the queue and returns nothing from a queue holding one or "
                "two messages, so its empty result proves nothing."
            )

    for step in runnable:
        if re.search(r"\bsleep\b", step.command):
            problems.append(
                f"step {step.name!r} contains a bare sleep. Annotate the block "
                "with '# harness waits for: <condition> (timeout Ns)' so the "
                "harness polls instead of sleeping."
            )

    for step in steps:
        if step.wait_for and step.wait_for not in KNOWN_CONDITIONS:
            problems.append(
                f"step {step.name!r} waits for {step.wait_for!r}, which the "
                f"harness cannot poll. Known conditions: "
                f"{sorted(KNOWN_CONDITIONS)}."
            )

    if not any("send-message" in s.command for s in runnable):
        problems.append("no send-message step: the lab never starts anything.")

    names = [s.name for s in steps]
    if len(names) != len(set(names)):
        problems.append(f"duplicate step names: {names}")

    return problems


def extract(path: str | Path) -> list[Step]:
    """The lab document's steps, validated.

    Raises ExtractionError rather than returning a weakened step list, because
    a harness that silently tests less than it claims is worse than one that
    refuses to start.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    seen: dict[str, int] = {}
    steps = [step for step in
             (to_step(block, seen) for block in blocks(text))
             if step is not None]

    if not steps:
        raise ExtractionError(f"{path}: no runnable steps found")

    problems = validate(steps)
    if problems:
        listed = "\n  - ".join(problems)
        raise ExtractionError(f"{path} is not a runnable lab:\n  - {listed}")

    return steps
