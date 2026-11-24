"""Phase status, computed from evidence rather than written by hand.

This module exists because of a bug in the README. The status line was updated
when the nightly workflow landed and the "What does not exist yet" section was
not, so for an hour the README asserted there was no nightly run while the run
sat in the health record. Nothing mechanical catches that: a prose claim about
an absence has no referent to check.

So the claim stops being prose. Each phase declares what would have to be true
for it to be done, every condition is checked against the repository or the
health record, and the README's status block is generated from the result. A
phase cannot be marked done here by anyone's opinion.

What this honestly cannot check is stated with the phases rather than hidden:
no test can reach AWS, so whether the bootstrap stacks are deployed is taken
on the evidence that runs happened at all.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PHASES_START = "<!-- phases:start -->"
PHASES_END = "<!-- phases:end -->"


@dataclass
class Condition:
    description: str
    ok: bool


@dataclass
class Phase:
    number: int
    name: str
    done_when: str
    conditions: list[Condition] = field(default_factory=list)
    #: Things no file and no record can establish.
    unverifiable: list[str] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return bool(self.conditions) and all(c.ok for c in self.conditions)


def _text(root: Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _records(root: Path) -> list[dict]:
    raw = _text(root, "health/health.jsonl")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def assess(root: Path | None = None) -> list[Phase]:
    root = root or ROOT
    records = _records(root)
    passing = [r for r in records if r.get("passed")]

    def teardown_verified(record: dict) -> bool:
        names = {c["name"] for c in record.get("checks", []) if c["ok"]}
        return {"teardown.stack_deleted", "teardown.no_leaks",
                "teardown.all_tagged_resolved"} <= names

    return [
        Phase(
            0, "Account hygiene",
            "a budget alarm, and a CI role assumable with no stored key",
            [
                Condition("the OIDC role template carries its CI policies",
                          "AssumeCdkBootstrapRoles" in
                          _text(root, "bootstrap/oidc-role.yaml")),
                Condition("a budget template exists",
                          bool(_text(root, "bootstrap/budget.yaml"))),
                Condition("the smoke workflow exists",
                          bool(_text(root, ".github/workflows/oidc-smoke.yml"))),
            ],
            ["whether those two stacks are deployed: no test here can reach AWS"],
        ),
        Phase(
            1, "The stack, by hand",
            "deploy then destroy leaves nothing carrying the lab tag, proved "
            "by querying rather than by looking at the console",
            [
                Condition("the CDK stack is defined",
                          bool(_text(root, "infra/lab_stack.py"))),
                Condition("at least one run verified teardown against a real "
                          "deployment",
                          any(teardown_verified(r) for r in records)),
            ],
        ),
        Phase(
            2, "The harness",
            "one command runs the whole loop and exits non-zero if an "
            "assertion fails",
            [
                Condition("the runner exists",
                          bool(_text(root, "harness/run.py"))),
                Condition("at least one run passed end to end",
                          bool(passing)),
                Condition("a failed run is recorded as a failure, not "
                          "silently",
                          any(not r.get("passed") for r in records)),
            ],
        ),
        Phase(
            3, "Extraction",
            "editing a command in the lab document changes what the harness "
            "runs, without touching harness code",
            [
                Condition("the lab document exists",
                          bool(_text(root, "lab/sqs-retry/lab.md"))),
                Condition("it yields runnable steps", _extracts(root)),
                Condition("no lab commands are left in harness code",
                          "aws sqs" not in _text(root, "harness/steps.py")),
            ],
        ),
        Phase(
            4, "Scheduling and the record",
            "the record grows on a schedule, and the README quotes it rather "
            "than restating it",
            [
                Condition("the scheduled workflow exists",
                          bool(_text(root, ".github/workflows/lab-health.yml"))),
                Condition("at least one recorded run came from CI",
                          any(r.get("ci") for r in records)),
                Condition("the README's figures are generated",
                          "<!-- health:start -->" in _text(root, "README.md")),
            ],
            ["whether a week of runs has accumulated, which is what the "
             "redrive tolerance needs before it can gate"],
        ),
    ]


def _extracts(root: Path) -> bool:
    """True when the lab document parses into at least one step."""
    try:
        from harness.extract import extract
        return bool(extract(root / "lab" / "sqs-retry" / "lab.md"))
    except Exception:
        return False


def render(phases: list[Phase]) -> str:
    done = sum(1 for p in phases if p.done)
    lines = [
        f"**{done} of {len(phases)} phases done.** Each line is checked "
        "against the repository and `health/health.jsonl`, not asserted.",
        "",
        "| Phase | Done when | Status |",
        "|---|---|---|",
    ]
    for phase in phases:
        failed = [c.description for c in phase.conditions if not c.ok]
        status = ("yes" if phase.done
                  else "not yet: " + "; ".join(failed))
        lines.append(f"| **{phase.number}. {phase.name}** | "
                     f"{phase.done_when} | {status} |")

    unverifiable = [(p, note) for p in phases for note in p.unverifiable]
    if unverifiable:
        lines += ["", "Not checkable here, and so not claimed:", ""]
        lines += [f"- Phase {p.number}: {note}" for p, note in unverifiable]

    lines += [
        "",
        "Generated by `python -m harness.phases`. A phase cannot be marked "
        "done by editing this table: the conditions are in "
        "[`harness/phases.py`](harness/phases.py), and CI fails if "
        "regenerating this block changes anything.",
    ]
    return "\n".join(lines)


def update_readme(path: str | Path, phases: list[Phase]) -> bool:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if PHASES_START not in text or PHASES_END not in text:
        raise ValueError(
            f"{path} has no {PHASES_START} / {PHASES_END} markers, so phase "
            "status cannot be generated into it. Add them, rather than "
            "writing a status line by hand."
        )
    before, _, rest = text.partition(PHASES_START)
    _, _, after = rest.partition(PHASES_END)
    updated = f"{before}{PHASES_START}\n{render(phases)}\n{PHASES_END}{after}"
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


if __name__ == "__main__":
    found = assess()
    update_readme(ROOT / "README.md", found)
    done = sum(1 for p in found if p.done)
    print(f"README phase block regenerated: {done} of {len(found)} phases done")
