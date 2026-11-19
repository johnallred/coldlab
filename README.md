# coldlab

Cold-start testing for AWS lab environments: provision a lab with CDK, run the
exact steps a student is told to run, assert the result the lab promises, tear
it down, and verify nothing survived.

**Start here: [RUNBOOK.md](RUNBOOK.md).**

**Status: Phase 1 of 4, written but not deployed.** The lab environment is
defined and synthesizes clean; nothing has been provisioned. See `HANDOFF.md`
for what is done and what is next.

This README states only what exists. Claims get added when the thing they
describe does.

## What exists now

| Path | What it is |
|---|---|
| `bootstrap/oidc-role.yaml` | CloudFormation: GitHub OIDC provider and a CI role with no permissions yet |
| `bootstrap/budget.yaml` | CloudFormation: a monthly cost budget and email notification |
| `.github/workflows/oidc-smoke.yml` | Proves CI can assume the role without stored credentials |
| `infra/` | CDK stack: the queue, dead-letter queue, worker and partner that make up the lab |

## The lab

One concept, one observable result. A message is delivered, the partner refuses
it until the receive count reaches the message's `fail_until`, and the student
watches either a successful download or a message landing in the dead-letter
queue after exactly three receives.

The failing partner is a Lambda the worker invokes directly rather than an HTTP
endpoint, so the lab needs no public URL, and the failure is driven by SQS's own
`ApproximateReceiveCount`. That is deliberate: the counter is the thing being
taught, so the lab should not hide it in a table of its own.

## What does not exist yet

The harness, the health record, and anything deployed. Phases 2 to 4.
