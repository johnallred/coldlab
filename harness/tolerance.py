"""Answering the redrive-tolerance question from the record.

    python -m harness.tolerance

The decision this automates is whether `timing.redrive_within_tolerance`
should become a gating check. It was going to be a judgment call a week later,
which in this project's experience means a judgment call nobody makes, or one
that comes out differently depending on who looks and what they remember.

So the criterion is data (`checks.REDRIVE_PROMOTION`) and this reads it against
the record. The numbers live in exactly one place: this module has no copy of
them, because a threshold kept in two places disagreed with itself within three
runs when it was the redrive observations.

What it does NOT decide, and says so in its own output: whether the
observations are bimodal, and whether they drift by weekday. Ten points cannot
settle either, and pretending otherwise would be the same mistake as writing
one observation into `expected.yaml` as though it were a fact. It prints every
observation so that a person can look.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path

from harness.checks import REDRIVE_PROMOTION
from harness.report import load_records

ROOT = Path(__file__).resolve().parents[1]

WAIT, PROMOTE, RETIRE = "wait", "promote", "retire"

#: The band the advisory check uses today, as factors of the derived nominal.
#: Stated here only so the report can say how much tighter the proposed band
#: would be; `checks.failure_path` remains the one place it is applied.
CURRENT_BAND_FACTORS = (0.5, 3.0)


@dataclass
class Observation:
    run_id: str
    day: str
    seconds: float
    ci: bool


@dataclass
class Assessment:
    observations: list[Observation] = field(default_factory=list)
    verdict: str = WAIT
    reasons: list[str] = field(default_factory=list)
    band: tuple[float, float] | None = None
    nominal: float | None = None

    @property
    def days(self) -> int:
        return len({o.day for o in self.observations})

    @property
    def values(self) -> list[float]:
        return [o.seconds for o in self.observations]


def observations(records: list[dict]) -> list[Observation]:
    """Every run that got far enough to time a redrive.

    A run that aborts earlier records none, which is why the criterion counts
    observations rather than nights.
    """
    found = []
    for record in records:
        seconds = (record.get("measurements") or {}).get("redrive_seconds")
        if seconds is None:
            continue
        found.append(Observation(
            run_id=record.get("run_id", "?"),
            day=str(record.get("started_at", ""))[:10],
            seconds=float(seconds),
            ci=bool(record.get("ci")),
        ))
    return found


def assess(records: list[dict], criterion: dict | None = None) -> Assessment:
    criterion = criterion or REDRIVE_PROMOTION
    found = observations(records)
    assessment = Assessment(observations=found)

    short_of = []
    if len(found) < criterion["min_observations"]:
        short_of.append(
            f"{len(found)} observations, {criterion['min_observations']} needed")
    if assessment.days < criterion["min_distinct_days"]:
        short_of.append(
            f"{assessment.days} distinct days, "
            f"{criterion['min_distinct_days']} needed")

    if short_of:
        assessment.verdict = WAIT
        assessment.reasons = short_of
        return assessment

    values = assessment.values
    low, high = min(values), max(values)
    median = statistics.median(values)
    spread = (high - low) / median if median else 0.0

    if spread > criterion["max_relative_spread"]:
        assessment.verdict = RETIRE
        assessment.reasons = [
            f"spread is {spread:.0%} of the median, over the "
            f"{criterion['max_relative_spread']:.0%} a band may absorb",
            "the timing is not determinate enough to assert; record it and "
            "let the floor checks gate, as the receive count does",
        ]
        return assessment

    assessment.verdict = PROMOTE
    assessment.band = (low * criterion["band_low_factor"],
                       high * criterion["band_high_factor"])
    assessment.reasons = [
        f"{len(found)} observations across {assessment.days} days",
        f"spread is {spread:.0%} of the median, within the "
        f"{criterion['max_relative_spread']:.0%} a band may absorb",
    ]
    return assessment


def render(assessment: Assessment, nominal: float | None = None) -> str:
    lines = [f"redrive tolerance: {assessment.verdict.upper()}", ""]

    for reason in assessment.reasons:
        lines.append(f"  {reason}")
    lines.append("")

    if assessment.observations:
        values = assessment.values
        lines.append("  observations")
        for o in sorted(assessment.observations, key=lambda o: o.run_id):
            lines.append(f"    {o.day}  {o.seconds:6.1f}s  "
                         f"{'ci' if o.ci else 'local'}  {o.run_id}")
        lines.append(f"    n={len(values)} days={assessment.days} "
                     f"min={min(values):.0f} max={max(values):.0f} "
                     f"median={statistics.median(values):.0f}")
        lines.append("")

    if assessment.band:
        low, high = assessment.band
        lines.append(f"  proposed band  {low:.0f}-{high:.0f}s")
        if nominal:
            was_low = CURRENT_BAND_FACTORS[0] * nominal
            was_high = CURRENT_BAND_FACTORS[1] * nominal
            tighter = (was_high - was_low) / (high - low)
            lines.append(f"  current band   {was_low:.0f}-{was_high:.0f}s "
                         f"({tighter:.1f}x wider)")
        outside = [o.run_id for o in assessment.observations
                   if not low <= o.seconds <= high]
        lines.append(f"  recorded runs outside it: {outside or 'none'}")
        lines.append("")
        lines.append("  To promote: set gating=True on "
                     "timing.redrive_within_tolerance in harness/checks.py "
                     "and use the band above in place of the nominal "
                     "multiples.")
        lines.append("")

    lines += [
        "  Not decided here, because this many points cannot settle it:",
        "    whether the observations are bimodal",
        "    whether they drift by weekday or by time of day",
        "  The schedule fires at one time of day, so the sample describes that",
        "  moment. Read the observations above before acting on the verdict.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import yaml

    records = load_records(ROOT / "health" / "health.jsonl")
    expected = yaml.safe_load(
        (ROOT / "lab" / "sqs-retry" / "expected.yaml").read_text(encoding="utf-8"))
    print(render(assess(records),
                 nominal=expected["failure_path"]["redrive_after_seconds"]))
