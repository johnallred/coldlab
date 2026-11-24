"""Test the learner's sandbox: everything the lab needs, nothing it must not allow.

    python -m harness.sandbox                 # against the deployed coldlab-learner role
    python -m harness.sandbox --strict        # also fail on the deployer finding

Reads `lab/<lab>/sandbox.yaml`, a list of what a learner must be able to do and
what they must never be able to do, and asks AWS's policy simulator about each
line for the deployed `coldlab-learner` role. The simulator applies the role's
identity policy, its permissions boundary and any organisation policies, so a
line passes only if the three layers together give the answer the list
expects. Any disagreement fails the run, in either direction: a lab that
cannot do step 4 is as broken as one that can delete the trail.

It also reports one thing the simulator cannot see, because it is not a
permission the learner holds but one they borrow. `cdk deploy` works by
assuming the CDK bootstrap deploy role, and stacks are then created by the
CloudFormation execution role, which `cdk bootstrap` gives AdministratorAccess
unless told otherwise. A learner who can run `cdk deploy` can therefore deploy
anything a CDK app can describe, with administrator rights, whatever their own
policies say. The check reads the execution role's attached policies and says
so. With `--strict` that finding fails the run too.

Needs credentials allowed to call iam:SimulatePrincipalPolicy on the learner
role and iam:ListAttachedRolePolicies on the execution role.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
ADMIN = "AdministratorAccess"

Runner = Callable[[list[str]], dict]


def aws(args: list[str]) -> dict:
    result = subprocess.run(["aws", *args, "--output", "json"],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout or "{}")


def requirements(lab: str, values: dict) -> list[dict]:
    raw = yaml.safe_load((ROOT / "lab" / lab / "sandbox.yaml").read_text(encoding="utf-8"))
    out = []
    for expected, key in (("allowed", "must_allow"), ("denied", "must_deny")):
        for item in raw.get(key) or []:
            out.append({"why": item["why"], "action": item["action"],
                        "resource": item["resource"].format(**values),
                        "expected": expected})
    return out


def region_of(arn: str, default: str) -> str:
    """The region a request for this ARN goes to.

    IAM has one endpoint, in us-east-1. S3 bucket ARNs carry no region, and the
    learner's `aws s3 ls` goes to the lab's region, so they get the default.
    """
    parts = arn.split(":")
    if parts[2] == "iam":
        return "us-east-1"
    return parts[3] or default


def simulate(run: Runner, role_arn: str, req: dict, region: str) -> str:
    """allowed, explicitDeny or implicitDeny, as the simulator reports it."""
    context = (f"ContextKeyName=aws:RequestedRegion,"
               f"ContextKeyValues={region_of(req['resource'], region)},ContextKeyType=string")
    answer = run(["iam", "simulate-principal-policy", "--policy-source-arn", role_arn,
                  "--action-names", req["action"], "--resource-arns", req["resource"],
                  "--context-entries", context])
    return answer["EvaluationResults"][0]["EvalDecision"]


def deployer_finding(run: Runner, values: dict) -> str | None:
    role = f"cdk-{values['qualifier']}-cfn-exec-role-{values['account']}-{values['region']}"
    attached = run(["iam", "list-attached-role-policies", "--role-name", role])
    names = [p["PolicyName"] for p in attached.get("AttachedPolicies", [])]
    if ADMIN in names:
        return (f"{role} has {ADMIN}, and the learner may assume the CDK deploy role, "
                "so `cdk deploy` lets a learner create anything a CDK app describes with "
                "administrator rights. Re-bootstrap with --cloudformation-execution-policies "
                "scoped to the lab's services, or pre-provision the stack so learners never "
                "deploy.")
    return None


def check(run: Runner, lab: str, region: str, stack: str, bucket: str,
          qualifier: str) -> tuple[list[tuple[dict, str]], str | None, dict]:
    identity = run(["sts", "get-caller-identity"])
    partition = identity["Arn"].split(":")[1]
    values = {"partition": partition, "region": region, "account": identity["Account"],
              "stack": stack, "bucket": bucket, "qualifier": qualifier}
    role_arn = f"arn:{partition}:iam::{identity['Account']}:role/coldlab-learner"
    results = [(req, simulate(run, role_arn, req, region)) for req in requirements(lab, values)]
    return results, deployer_finding(run, values), values


def report(results: list[tuple[dict, str]], finding: str | None) -> list[str]:
    lines = []
    wrong = 0
    for req, decision in results:
        got = "allowed" if decision == "allowed" else "denied"
        ok = got == req["expected"]
        wrong += not ok
        mark = "ok  " if ok else "FAIL"
        lines.append(f"{mark} must be {req['expected']:<7} {decision:<13} "
                     f"{req['action']:<32} {req['why']}")
    lines.append("")
    lines.append(f"{len(results) - wrong} of {len(results)} requirements hold")
    if finding:
        lines.append(f"RISK deployer: {finding}")
    return lines


def main(argv: list[str] | None = None, run: Runner = aws) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lab", default="sqs-retry")
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--stack", default="ColdlabSqsRetry")
    parser.add_argument("--bucket", default="coldlabsqsretry")
    parser.add_argument("--qualifier", default="hnb659fds")
    parser.add_argument("--strict", action="store_true",
                        help="fail on the deployer finding as well")
    args = parser.parse_args(argv)
    results, finding, _ = check(run, args.lab, args.region, args.stack, args.bucket,
                                args.qualifier)
    print("\n".join(report(results, finding)))
    failed = any((d == "allowed") != (r["expected"] == "allowed") for r, d in results)
    return 1 if failed or (args.strict and finding) else 0


if __name__ == "__main__":
    sys.exit(main())
