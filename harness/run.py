"""One command that provisions the lab, runs it, asserts it, and tears it down.

    python -m harness.run

Exits non-zero if any gating check fails. Teardown runs in a `finally` block,
so a failed assertion, a timeout, or a crash still destroys the stack: a
harness that leaks cost when it fails is worse than no harness, because it
fails exactly when nobody is watching.

Needs the `aws` and `cdk` CLIs on PATH and working credentials.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import yaml

from harness import arns, checks, parse, report
from harness.shell import Timeout, poll_until, run
from harness.steps import lab_steps

ROOT = Path(__file__).resolve().parents[1]


def now_ms() -> int:
    return int(time.time() * 1000)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# --- observations -----------------------------------------------------------

def stack_outputs(stack: str, region: str) -> dict:
    result = run(f"aws cloudformation describe-stacks --stack-name {stack} "
                 f"--region {region}", check=True)
    return parse.stack_outputs(result.json())


def stack_exists(stack: str, region: str) -> bool:
    return run(f"aws cloudformation describe-stacks --stack-name {stack} "
               f"--region {region}").ok


def queue_depth(queue_url: str, region: str) -> int:
    result = run(f"aws sqs get-queue-attributes --region {region} "
                 f'--queue-url "{queue_url}" '
                 "--attribute-names ApproximateNumberOfMessages", check=True)
    return parse.queue_depth(result.json())


def bucket_keys(bucket: str) -> list[str]:
    # An empty prefix exits 1 on some CLI versions, which is not an error here.
    result = run(f'aws s3 ls "s3://{bucket}/landed/"')
    return parse.bucket_keys(result.stdout)


def resolve_tagged(region: str, tag_key: str) -> list[dict]:
    """Every tagged ARN, resolved against the service that owns it.

    The tagging API is an eventually-consistent index. An ARN it returns is a
    question, and this answers it.
    """
    result = run(f"aws resourcegroupstaggingapi get-resources --region {region} "
                 f"--tag-filters Key={tag_key},Values=true", check=True)
    resolved = []
    for arn in parse.tagged_arns(result.json()):
        command = arns.resolve_command(arn, region)
        if command is None:
            resolved.append({"arn": arn, "status": "unresolved", "via": None})
            continue
        probe = run(command)
        resolved.append({
            "arn": arn,
            "status": "leak" if probe.ok else "gone",
            "via": command,
        })
    return resolved


# --- the loop ---------------------------------------------------------------

def execute_steps(steps, env, region, outputs, log) -> dict:
    """Run the lab's steps in order, returning what was measured."""
    measured: dict = {"bucket_keys": []}
    queue_url, dlq_url = outputs["QueueUrl"], outputs["DeadLetterUrl"]
    bucket = outputs["LandingBucket"]
    success_key = "invoice-9001.csv"

    conditions = {
        "dlq_has_message": lambda: queue_depth(dlq_url, region) or False,
        "success_file_present": lambda: (
            success_key in bucket_keys(bucket) or False),
    }

    for step in steps:
        if step.wait_for:
            log(f"  waiting: {step.name}")
            poll = poll_until(conditions[step.wait_for], timeout=step.timeout,
                              interval=15, description=step.wait_for)
            if step.wait_for == "dlq_has_message":
                measured["dlq_depth"] = poll.value
                measured["redrive_seconds"] = now_ms() / 1000 - measured["sent_at_ms"] / 1000
            log(f"    true after {poll.seconds:.0f}s ({poll.attempts} polls)")
            continue

        log(f"  step: {step.name}")
        if "send-message" in step.command and "8812" in step.command:
            measured["sent_at_ms"] = now_ms()
        result = run(step.command, env=env, check=True)

        if "receive-message" in step.command:
            message = parse.first_message(result.json())
            if message is None:
                raise RuntimeError(
                    "long poll returned no message although the queue had "
                    f"depth {measured.get('dlq_depth')}. This is the only "
                    "read of this message, so the run cannot continue."
                )
            measured["receive_count"] = parse.receive_count(message)
            measured["sent_timestamp_ms"] = parse.sent_timestamp_ms(message)
            measured["dlq_body"] = message["Body"]
        elif "s3 ls" in step.command:
            measured["bucket_keys"] = parse.bucket_keys(result.stdout)

    return measured


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lab", default="sqs-retry")
    ap.add_argument("--stack", default="ColdlabSqsRetry")
    ap.add_argument("--region", default="us-east-2")
    ap.add_argument("--tag-key", default="coldlab:managed")
    ap.add_argument("--no-provision", action="store_true",
                    help="assume the stack is already deployed (debugging only; "
                         "a fresh stack is what keeps queues empty between runs)")
    ap.add_argument("--keep", action="store_true",
                    help="skip teardown. Leaves resources running; the next run "
                         "will not be clean and the account will cost money.")
    ap.add_argument("--health-dir", default=str(ROOT / "health"))
    args = ap.parse_args(argv)

    expected = yaml.safe_load(
        (ROOT / "lab" / args.lab / "expected.yaml").read_text(encoding="utf-8"))

    started_at, started = utc_now(), time.monotonic()
    run_id = started_at.replace(":", "").replace("-", "")
    infra = str(ROOT / "infra")

    def log(message):
        print(message, flush=True)

    log(f"coldlab run {run_id}  lab={args.lab} region={args.region}")

    all_checks: list[checks.Check] = []
    measured: dict = {}
    error = None

    # The CDK app reads COLDLAB_REGION. Setting it here is what stops the
    # harness asserting against one region while deploying to another: the CDK
    # CLI would otherwise take the region from whatever the credentials
    # resolve to, which is how a deploy ended up in us-east-1.
    cdk_env = {
        "COLDLAB_REGION": args.region,
        "AWS_REGION": args.region,
        "AWS_DEFAULT_REGION": args.region,
    }

    try:
        if not args.no_provision:
            log(f"  provisioning (cdk deploy) into {args.region}")
            run("cdk deploy --require-approval never", cwd=infra,
                env=cdk_env, timeout=1800, check=True)

        outputs = stack_outputs(args.stack, args.region)
        missing = {"QueueUrl", "DeadLetterUrl", "LandingBucket"} - set(outputs)
        if missing:
            raise RuntimeError(f"stack outputs missing: {sorted(missing)}")

        env = {"Q": outputs["QueueUrl"], "DLQ": outputs["DeadLetterUrl"],
               "BUCKET": outputs["LandingBucket"]}

        measured = execute_steps(lab_steps(args.region), env, args.region,
                                 outputs, log)

        failure_obs = {**measured, "bucket_keys": measured["bucket_keys"]}
        all_checks += checks.failure_path(expected, failure_obs)
        all_checks += checks.success_path(expected, measured)

    except (Timeout, RuntimeError, KeyError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        log(f"  ERROR {error}")

    finally:
        if args.keep:
            log("  teardown SKIPPED (--keep). Resources are still running.")
        else:
            log("  tearing down (cdk destroy)")
            destroy = run("cdk destroy --force", cwd=infra, env=cdk_env,
                          timeout=1800)
            if not destroy.ok:
                log(f"    cdk destroy exited {destroy.returncode}; "
                    "verifying anyway")
            teardown_obs = {
                "stack_exists": stack_exists(args.stack, args.region),
                "tagged": resolve_tagged(args.region, args.tag_key),
            }
            measured["teardown"] = teardown_obs
            all_checks += checks.teardown(expected, teardown_obs)

    # An error is a failed check, not a separate channel. Otherwise a run that
    # never provisioned prints three green teardown lines and "0 failing
    # checks" while having tested nothing, and the health record has no row
    # saying so.
    all_checks.insert(0, checks.Check(
        "run.completed",
        error is None,
        "every step ran",
        error or "yes",
        note="Set when the run aborted before its assertions. The teardown "
             "checks below may still pass, but they are not evidence of a "
             "verified teardown when nothing was provisioned.",
    ))

    passed, failures = checks.verdict(all_checks)

    log("")
    for check in all_checks:
        log("  " + check.line())

    seconds = time.monotonic() - started
    record = {
        "run_id": run_id,
        "started_at": started_at,
        "seconds": round(seconds, 1),
        "passed": passed,
        "lab": args.lab,
        "region": args.region,
        "error": error,
        "measurements": {k: v for k, v in measured.items() if k != "teardown"},
        "checks": [{"name": c.name, "ok": c.ok, "gating": c.gating,
                    "expected": str(c.expected), "actual": str(c.actual)}
                   for c in all_checks],
    }

    health = Path(args.health_dir)
    report.append_record(health / "health.jsonl", record)
    summary = report.regenerate(health / "health.jsonl", health / "HEALTH.md")

    log("")
    log(f"  {'PASS' if passed else 'FAIL'} in {seconds:.0f}s  "
        f"({len(failures)} failing check(s), "
        f"{sum(1 for c in failures if c.gating)} gating)")
    log(f"  health: {summary['runs']} runs, "
        f"{summary['pass_rate'] * 100:.0f}% pass rate")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
