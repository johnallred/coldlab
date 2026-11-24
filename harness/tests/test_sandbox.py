"""The learner sandbox: the requirement list, the role template, and the check."""

import fnmatch
import unittest
from pathlib import Path

import yaml

from harness import sandbox

ROOT = Path(__file__).resolve().parents[2]
VALUES = {"partition": "aws", "region": "us-east-2", "account": "111122223333",
          "stack": "ColdlabSqsRetry", "bucket": "coldlabsqsretry", "qualifier": "hnb659fds"}


def template() -> dict:
    """learner-role.yaml with !Sub and !Ref resolved for the values above."""
    class Loader(yaml.SafeLoader):
        pass

    subs = {"AWS::Partition": "aws", "AWS::Region": "us-east-2",
            "AWS::AccountId": "111122223333", "LabStackName": "ColdlabSqsRetry",
            "LabBucketPrefix": "coldlabsqsretry", "CdkQualifier": "hnb659fds"}

    def sub(loader, node):
        text = loader.construct_scalar(node)
        for key, value in subs.items():
            text = text.replace("${" + key + "}", value)
        return text

    Loader.add_constructor("!Sub", sub)
    Loader.add_constructor("!Ref", lambda l, n: subs.get(l.construct_scalar(n), "REF"))
    Loader.add_constructor("!GetAtt", lambda l, n: "GETATT")
    return yaml.load((ROOT / "bootstrap" / "learner-role.yaml").read_text(), Loader=Loader)


def allows(statements, action, resource) -> bool:
    """Whether any Allow statement names this action on this resource."""
    for s in statements:
        if s["Effect"] != "Allow":
            continue
        actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
        resources = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
        if any(fnmatch.fnmatchcase(action, a) for a in actions) and \
                any(fnmatch.fnmatchcase(resource, r) for r in resources):
            return True
    return False


class TestTheTemplateCoversTheList(unittest.TestCase):
    """Offline: the cheap half of the check, which needs no AWS."""

    def setUp(self):
        resources = template()["Resources"]
        self.boundary = resources["LearnerBoundary"]["Properties"]["PolicyDocument"]["Statement"]
        self.identity = resources["LearnerRole"]["Properties"]["Policies"][0][
            "PolicyDocument"]["Statement"]
        self.reqs = sandbox.requirements("sqs-retry", VALUES)

    def test_every_lab_step_is_granted_and_inside_the_boundary(self):
        for req in (r for r in self.reqs if r["expected"] == "allowed"):
            with self.subTest(req["why"]):
                self.assertTrue(allows(self.identity, req["action"], req["resource"]))
                self.assertTrue(allows(self.boundary, req["action"], req["resource"]))

    def test_nothing_forbidden_is_granted_by_both_layers(self):
        for req in (r for r in self.reqs if r["expected"] == "denied"):
            with self.subTest(req["why"]):
                self.assertFalse(allows(self.identity, req["action"], req["resource"])
                                 and allows(self.boundary, req["action"], req["resource"]))

    def test_the_boundary_is_attached(self):
        role = template()["Resources"]["LearnerRole"]["Properties"]
        self.assertIn("PermissionsBoundary", role)


class FakeAWS:
    def __init__(self, decisions, exec_policies=("AdministratorAccess",)):
        self.decisions, self.exec_policies, self.calls = decisions, exec_policies, []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["sts", "get-caller-identity"]:
            return {"Account": "111122223333",
                    "Arn": "arn:aws:iam::111122223333:user/instructor"}
        if args[:2] == ["iam", "list-attached-role-policies"]:
            return {"AttachedPolicies": [{"PolicyName": n} for n in self.exec_policies]}
        key = (args[args.index("--action-names") + 1], args[args.index("--resource-arns") + 1])
        return {"EvaluationResults": [{"EvalDecision": self.decisions.get(key, "implicitDeny")}]}


class TestTheCheck(unittest.TestCase):
    def needed(self):
        return {(r["action"], r["resource"]): "allowed"
                for r in sandbox.requirements("sqs-retry", VALUES) if r["expected"] == "allowed"}

    def test_a_correct_sandbox_passes_and_reports_the_deployer(self):
        fake = FakeAWS(self.needed())
        self.assertEqual(sandbox.main([], run=fake), 0)
        self.assertEqual(sandbox.main(["--strict"], run=fake), 1)

    def test_a_missing_permission_fails(self):
        decisions = self.needed()
        key = next(k for k in decisions if k[0] == "logs:FilterLogEvents")
        decisions[key] = "implicitDeny"
        self.assertEqual(sandbox.main([], run=FakeAWS(decisions)), 1)

    def test_an_escalation_fails(self):
        decisions = self.needed()
        decisions[("iam:PassRole", "arn:aws:iam::111122223333:role/coldlab-ci-coldlab")] = "allowed"
        self.assertEqual(sandbox.main([], run=FakeAWS(decisions)), 1)

    def test_no_deployer_finding_when_the_execution_role_is_scoped(self):
        fake = FakeAWS(self.needed(), exec_policies=("coldlab-cfn-exec",))
        self.assertEqual(sandbox.main(["--strict"], run=fake), 0)

    def test_each_request_carries_the_region_it_would_go_to(self):
        fake = FakeAWS(self.needed())
        sandbox.main([], run=fake)
        regions = {c[c.index("--resource-arns") + 1]: c[c.index("--context-entries") + 1]
                   for c in fake.calls if "--resource-arns" in c}
        other = [k for k in regions if ":us-east-1:" in k and ":sqs:" in k][0]
        self.assertIn("ContextKeyValues=us-east-1", regions[other])
        bucket = [k for k in regions if k.startswith("arn:aws:s3:::coldlab")][0]
        self.assertIn("ContextKeyValues=us-east-2", regions[bucket])


if __name__ == "__main__":
    unittest.main()
