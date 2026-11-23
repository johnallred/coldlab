# coldlab

Cold-start testing for AWS lab environments: provision a lab with CDK, run the
exact steps a student is told to run, assert the result the lab promises, tear
it down, and verify nothing survived.

**Start here: [RUNBOOK.md](RUNBOOK.md).**

**Status: Phase 2 of 4.** Phases 0 and 1 are deployed, run by hand, and torn
down. The harness is written and covered by 63 tests against a fake AWS; it has
not yet been run against a real deployment. See `HANDOFF.md`.

This README states only what exists. Claims get added when the thing they
describe does.

## What exists now

| Path | What it is |
|---|---|
| `bootstrap/oidc-role.yaml` | CloudFormation: GitHub OIDC provider and a CI role with no permissions yet |
| `bootstrap/budget.yaml` | CloudFormation: a monthly cost budget and email notification |
| `infra/` | CDK stack: the queue, dead-letter queue, worker and failing partner |
| `lab/sqs-retry/expected.yaml` | The observable results, every value tagged `measured` or `derived` |
| `harness/` | Provision, run the lab's steps, assert, tear down, verify, record |
| `health/` | One JSON record per run, and a generated table |
| `.github/workflows/oidc-smoke.yml` | Proves CI can assume the role without stored credentials |
| `.github/workflows/harness-tests.yml` | The harness's tests, on every pull request, with no AWS |

## The lab

One concept, one observable result. A message is delivered, the partner refuses
it until the receive count reaches the message's `fail_until`, and the student
watches either a successful download or a message landing in the dead-letter
queue after exactly three receives.

The failing partner is a Lambda the worker invokes directly rather than an HTTP
endpoint, so the lab needs no public URL, and the failure is driven by SQS's own
`ApproximateReceiveCount`. That is deliberate: the counter is the thing being
taught, so the lab should not hide it in a table of its own.

## Running the harness

```bash
pip install -r harness/requirements.txt

python -m harness.run              # provision, run, assert, tear down, record
python -m harness.run --keep       # leave it running, for debugging
python -m harness.report           # regenerate health/HEALTH.md

python -m unittest discover -s harness/tests -t .   # 63 tests, no AWS needed
```

`python -m harness.run` needs the `aws` and `cdk` CLIs and working
credentials. The tests need neither.

Teardown runs in a `finally` block. A failed assertion, a timeout or a crash
still destroys the stack, because a harness that leaks cost when it fails leaks
it exactly when nobody is watching.

## What the first hand run changed

Five behaviours were measured that reading the CDK stack would have got wrong.
They are why `expected.yaml` records how each value was obtained, and they are
the constraints the harness is built around.

| What looked true | What was measured |
|---|---|
| The queue's 180s visibility timeout drives the retry | The worker overrides it per attempt with its own 15/30/60 backoff, so redrive is at about t=105 |
| An empty `receive-message` means an empty queue | A default short poll samples a subset of servers and returned nothing from a queue holding two messages |
| A long poll returns everything | Asking for ten returned one of two. Depth comes from `get-queue-attributes` |
| The receive count resets on redrive | It carries over and keeps counting: arrival is `maxReceiveCount + 1`, the first read sees one more |
| A tag query proves teardown | The tagging API is an eventually-consistent index. It reported a resource that CloudFormation had already deleted |

The last one is the reason `harness/arns.py` exists. Every ARN the tag query
returns is resolved against the service that owns it before anything is called
a leak, and an ARN no resolver understands is reported as unresolved rather
than clean, because "I could not check" is not "it is gone".

## Gating and advisory checks

A gating check sets the exit code. An advisory check is evaluated, printed and
recorded every run but does not fail it yet, because its stability has not been
measured over enough runs to gate on. Each advisory states its own promotion
criterion in `harness/checks.py`, and an advisory that fails is still recorded
as a failure: the only thing it does not do is set the exit code.

Two checks are advisory today. The exact receive count, because at-least-once
delivery makes an extra receive legal. And the redrive timing, because its
tolerance is currently a guess rather than a figure taken from recorded runs.

## What does not exist yet

**Phase 3, extraction.** The harness's steps are hardcoded in
`harness/steps.py`, shaped so that `extract.py` can produce the same list from
`lab/sqs-retry/lab.md`. Until then the lab document and the thing being tested
can still drift, which is the failure this project most wants to prevent.

**Phase 4, scheduling.** No nightly run, so `health/HEALTH.md` has no real runs
in it and the flake rate the whole design is pointed at is still unmeasured.
