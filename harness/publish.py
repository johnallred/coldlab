"""Publishing the lab to learners: immutable versions, promoted on evidence.

    python -m harness.publish status          # what is published, what is waiting
    python -m harness.publish promote         # promote the current version if it has earned it
    python -m harness.publish rollback REASON # put the previous published version back

The nightly run tests whatever is on `main`. Learners should not get that. They
get the *published* version: a frozen copy of the learner-facing files, taken
only once the record holds enough passing runs against that exact content.
So an edit to the lab is tested every night from the moment it lands, and
reaches learners only when it has passed, which is the beta and prod channels
of a lab publishing pipeline with the nightly run as beta.

A version is a hash of the files a learner uses: the lab document and the
infrastructure it deploys. `expected.yaml` and the harness are not part of it,
because changing a test does not change the lab. Every run records the version
it tested (`lab_version` in health/health.jsonl), so evidence is counted per
version, never per lab: three passes of last week's content say nothing about
today's.

Published copies live under `published/<lab>/<version>/` and are never edited.
`published/<lab>/channels.json` says which one is current and keeps the
history, so a rollback is a pointer change to a copy that already passed.

When the published version starts failing, the record separates the two causes
the lab-publishing concept page describes. Promotion requires passing runs on
the exact content, so a published version that fails has, by construction,
passed before with the same content: the environment changed, rolling back
cannot help, and the advice is to fix forward. That is the payoff of promoting
on evidence: an edit that breaks the lab fails while it is still on `main` and
never reaches learners, so a rollback is the rare case, kept for a version
whose failures began with its promotion and whose predecessor still passes.
The nightly run tests `main`, so the published version is observed directly
only while `main` holds the same content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness import report

ROOT = Path(__file__).resolve().parents[1]

#: Consecutive passing runs, against one version, before it reaches learners.
PROMOTE_AFTER = 3
#: Consecutive failures of the published version before the status says so.
FAILING_AFTER = 2


def learner_files(root: Path, lab: str) -> list[Path]:
    """What a learner uses: the lab document and the stack it deploys."""
    files = [root / "lab" / lab / "lab.md", root / "infra" / "app.py",
             root / "infra" / "lab_stack.py", root / "infra" / "cdk.json",
             root / "infra" / "requirements.txt"]
    files += sorted((root / "infra" / "lambda").rglob("*.py"))
    return [f for f in files if f.is_file() and "__pycache__" not in f.parts]


def lab_version(root: Path = ROOT, lab: str = "sqs-retry") -> str:
    """Twelve hex digits of a hash over the learner files, paths included."""
    digest = hashlib.sha256()
    for path in learner_files(root, lab):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def channels_path(root: Path, lab: str) -> Path:
    return root / "published" / lab / "channels.json"


def load_channels(root: Path, lab: str) -> dict:
    path = channels_path(root, lab)
    if not path.exists():
        return {"lab": lab, "prod": None, "history": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_channels(root: Path, lab: str, channels: dict) -> None:
    path = channels_path(root, lab)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(channels, indent=2) + "\n", encoding="utf-8")


def runs_for(records: list[dict], version: str) -> list[dict]:
    return sorted((r for r in records if r.get("lab_version") == version),
                  key=lambda r: r["started_at"])


def trailing(runs: list[dict], passed: bool) -> list[dict]:
    """The unbroken run of passes (or failures) at the end, oldest first."""
    out: list[dict] = []
    for run in reversed(runs):
        if bool(run.get("passed")) != passed:
            break
        out.insert(0, run)
    return out


def assess(records: list[dict], channels: dict, current: str) -> dict:
    """What the record says about the current and the published version."""
    prod = (channels.get("prod") or {}).get("version")
    passes = trailing(runs_for(records, current), True)
    state = {
        "current": current,
        "prod": prod,
        "current_passes": len(passes),
        "evidence": [r["started_at"] for r in passes[-PROMOTE_AFTER:]],
        "ready": current != prod and len(passes) >= PROMOTE_AFTER,
        "prod_failing": 0,
        "advice": None,
    }
    if prod:
        prod_runs = runs_for(records, prod)
        failing = trailing(prod_runs, False)
        state["prod_failing"] = len(failing)
        if len(failing) >= FAILING_AFTER:
            history = channels.get("history", [])
            previous = history[-2]["version"] if len(history) >= 2 else None
            passed_before = any(r.get("passed") for r in prod_runs[: len(prod_runs) - len(failing)])
            if passed_before:
                state["advice"] = ("fix forward: the published version passed and then "
                                   "failed with unchanged content, so the environment "
                                   "changed and rolling back cannot help")
            elif previous and trailing(runs_for(records, previous), True):
                state["advice"] = (f"roll back to {previous}: it still passes, and the "
                                   f"failures began with the promotion of {prod}")
            else:
                state["advice"] = ("pull the lab: the published version has never passed "
                                   "and there is no passing version to return to")
    return state


def describe(state: dict) -> list[str]:
    lines = [f"current version on main: {state['current']}",
             f"published to learners:   {state['prod'] or 'nothing yet'}"]
    if state["current"] == state["prod"]:
        lines.append("main and the published version are the same content")
    elif state["ready"]:
        lines.append(f"ready to promote: {state['current_passes']} consecutive passing runs "
                     f"on this exact content")
    else:
        lines.append(f"waiting: {state['current_passes']} of {PROMOTE_AFTER} consecutive "
                     "passing runs on this exact content")
    if state["advice"]:
        lines.append(f"published version failing {state['prod_failing']} runs running: "
                     f"{state['advice']}")
    return lines


def promote(root: Path, lab: str, records: list[dict], now: str | None = None) -> tuple[bool, list[str]]:
    channels = load_channels(root, lab)
    current = lab_version(root, lab)
    state = assess(records, channels, current)
    if not state["ready"]:
        return False, describe(state)
    target = root / "published" / lab / current
    if not target.exists():
        for path in learner_files(root, lab):
            copy = target / path.relative_to(root)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copy)
    entry = {"version": current,
             "promoted_at": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "evidence": state["evidence"],
             "reason": f"{PROMOTE_AFTER} consecutive passing runs"}
    channels["prod"] = entry
    channels.setdefault("history", []).append(entry)
    save_channels(root, lab, channels)
    return True, [f"promoted {current} to learners on {len(state['evidence'])} passing runs"]


def rollback(root: Path, lab: str, reason: str, now: str | None = None) -> tuple[bool, list[str]]:
    channels = load_channels(root, lab)
    history = channels.get("history", [])
    current = (channels.get("prod") or {}).get("version")
    previous = next((h for h in reversed(history) if h["version"] != current), None)
    if previous is None:
        return False, ["nothing to roll back to: no earlier published version"]
    entry = dict(previous, promoted_at=now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 reason=f"rollback from {current}: {reason}")
    channels["prod"] = entry
    history.append(entry)
    save_channels(root, lab, channels)
    return True, [f"rolled back to {previous['version']}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["status", "promote", "rollback", "version"])
    parser.add_argument("reason", nargs="?", default="")
    parser.add_argument("--lab", default="sqs-retry")
    parser.add_argument("--record", default=str(ROOT / "health" / "health.jsonl"))
    parser.add_argument("--quiet-if-waiting", action="store_true",
                        help="exit 0 when promote has nothing to do (for the nightly run)")
    args = parser.parse_args(argv)

    if args.command == "version":
        print(lab_version(ROOT, args.lab))
        return 0
    records = report.load_records(args.record)
    if args.command == "status":
        state = assess(records, load_channels(ROOT, args.lab), lab_version(ROOT, args.lab))
        print("\n".join(describe(state)))
        return 0
    if args.command == "promote":
        done, lines = promote(ROOT, args.lab, records)
        print("\n".join(lines))
        return 0 if done or args.quiet_if_waiting else 1
    if not args.reason:
        parser.error("rollback needs a reason")
    done, lines = rollback(ROOT, args.lab, args.reason)
    print("\n".join(lines))
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
