"""Running commands, and waiting for things to become true.

The harness runs the lab's own commands rather than reimplementing them with
an SDK. That is the whole contract: the thing under test is the text a student
is told to type, so if the lab document drifts from what works, the harness
fails. Reimplementing the steps in boto3 would test the harness's idea of the
lab instead of the lab.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field


@dataclass
class Result:
    command: str
    returncode: int
    stdout: str
    stderr: str
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def json(self):
        """Parsed stdout, or {} when the command printed nothing."""
        return json.loads(self.stdout) if self.stdout.strip() else {}


def run(command: str, cwd: str | None = None, env: dict | None = None,
        timeout: int = 600, check: bool = False) -> Result:
    """Run one shell command and capture everything.

    `shell=True` is deliberate. The commands come from the lab document and
    use shell variables, so they need a shell. Phase 3 extracts them verbatim
    and this function must keep running them unchanged.
    """
    merged = {**os.environ, **(env or {})}
    start = time.monotonic()
    proc = subprocess.run(
        command, shell=True, cwd=cwd, env=merged,
        capture_output=True, text=True, timeout=timeout,
    )
    result = Result(command, proc.returncode, proc.stdout, proc.stderr,
                    time.monotonic() - start)
    if check and not result.ok:
        raise RuntimeError(
            f"command failed ({result.returncode}): {command}\n"
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


class Timeout(Exception):
    """Raised when a polled condition never became true."""


@dataclass
class Poll:
    value: object = None
    seconds: float = 0.0
    attempts: int = 0
    observations: list = field(default_factory=list)


def poll_until(predicate, timeout: int, interval: int = 10,
               description: str = "condition") -> Poll:
    """Poll until `predicate()` returns something truthy.

    Polling rather than sleeping a fixed interval is a measured requirement,
    not a preference. A fixed sleep is either slower than it needs to be or
    reports a failure that was merely early, and the second kind of mistake is
    how a lab gets blamed on a student.
    """
    start = time.monotonic()
    deadline = start + timeout
    poll = Poll()
    while True:
        poll.attempts += 1
        poll.value = predicate()
        poll.observations.append(poll.value)
        poll.seconds = time.monotonic() - start
        if poll.value:
            return poll
        if time.monotonic() + interval > deadline:
            raise Timeout(
                f"{description}: never true within {timeout}s "
                f"({poll.attempts} attempts, last {poll.value!r})"
            )
        time.sleep(interval)
