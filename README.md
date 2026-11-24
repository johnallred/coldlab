# coldlab

Cold-start testing for AWS lab environments: provision a lab with CDK, run the
exact steps a student is told to run, assert the result the lab promises, tear
it down, and verify nothing survived.

**Start here: [RUNBOOK.md](RUNBOOK.md).**

**Status: all four phases built.** `python -m harness.run` provisions the lab,
runs the steps extracted from `lab/sqs-retry/lab.md`, asserts them, tears down
and verifies, in about eight minutes. It has passed twice against real AWS. The
nightly workflow is written and the CI role has the permissions to run it; what
is missing is runs, which only time supplies. See `HANDOFF.md`.

This README states only what exists. Claims get added when the thing they
describe does.

## Lab health

<!-- health:start -->
- Runs: **5**
- Pass rate: **60%** (3 of 5)
- Median duration: **453s**
- Checks that have both passed and failed: `run.completed`

Generated from [`health/health.jsonl`](health/health.jsonl) by `python -m harness.report`. Full table in [`health/HEALTH.md`](health/HEALTH.md).
<!-- health:end -->

Every figure above is generated from the record by `python -m harness.report`,
which the harness calls at the end of each run. None of it is typed in, so a
number here cannot drift from the runs it describes, and CI fails if the
generated block is stale.

The figure worth attention is not the pass rate. It is whether a check has both
passed and failed, because a lab that fails one run in twenty is a worse
problem than one that fails every time: the second gets fixed and the first
gets blamed on the student.

## What exists now

| Path | What it is |
|---|---|
| `bootstrap/oidc-role.yaml` | CloudFormation: GitHub OIDC provider and a CI role with no permissions yet |
| `bootstrap/budget.yaml` | CloudFormation: a monthly cost budget and email notification |
| `infra/` | CDK stack: the queue, dead-letter queue, worker and failing partner |
| `lab/sqs-retry/lab.md` | The student-facing lab. The harness runs these commands, it does not hold a copy |
| `lab/sqs-retry/expected.yaml` | The observable results, every value tagged `measured` or `derived` |
| `harness/` | Provision, run the lab's steps, assert, tear down, verify, record |
| `health/` | One JSON record per run, and a generated table |
| `.github/workflows/oidc-smoke.yml` | Proves CI can assume the role without stored credentials |
| `.github/workflows/harness-tests.yml` | The harness's tests, on every pull request, with no AWS |
| `.github/workflows/lab-health.yml` | The nightly run against real AWS, which appends to the record |

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

python -m unittest discover -s harness/tests -t .   # 98 tests, no AWS needed
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

Two checks are advisory today, and one of them has already changed shape
because of what the runs said.

The receive count across a redrive started as an exact-value check with a note
promising to promote it once twenty runs agreed. The second observation
disagreed with the first: 5 measured by hand, 4 from the first passing harness
run, same lab and same `maxReceiveCount`. So the exact value is not an
expectation and never was, and had it been gating that run would have failed
for no reason. It is now a drift detector over the set of values ever observed,
marked never to be promoted, and the floor of `maxReceiveCount + 1` is what
gates. **An advisory check retired by evidence is the mechanism working, not a
climbdown.**

The redrive timing is still advisory because its tolerance is a guess rather
than a figure taken from recorded runs. Every observation is recorded in
`lab/sqs-retry/expected.yaml` under `redrive_observed_seconds`, and a handful
of runs is too thin a basis for a band. That is the concrete reason the
scheduled run matters: it is what turns a guessed tolerance into a measured
one.

## The lab document is the step list

The harness holds no copy of the lab's commands. `harness/extract.py` reads
`lab/sqs-retry/lab.md` and runs the commands a student is told to type, so the
document and the thing being tested cannot drift apart. A lab that quietly
stops matching its instructions still passes every test you would normally
write, and that is the failure this prevents.

Four directives, written as shell comments so they run harmlessly if a student
copies a whole block. Each requires a reason, because a directive without one
is how an exception becomes permanent.

| Directive | Effect |
|---|---|
| `# step: <name>` | Names the step. The nearest heading is used otherwise |
| `# exits <n>: <why>` | This exit code also means success. Repeatable |
| `# not run by the harness: <why>` | Skip the block, for what a student does that the harness does differently |
| `# harness waits for: <cond> (timeout <n>s)` | Replace this block's `sleep` with a poll of a named condition |

That last one is the only deliberate difference between what a student does and
what the harness does. A student sleeps; the harness polls, because a fixed
sleep either wastes time or reports a failure that was merely early.

**Extraction refuses to run a document that would weaken the test.** It rejects
a second dead-letter read, since the receive count is only the arrival value on
the first one. It rejects a `receive-message` without `--wait-time-seconds`,
since a short poll's empty result proves nothing. It rejects a bare `sleep` in a
runnable step, a wait on a condition the runner cannot poll, and a runnable
block holding more than one command. Every one of those rules encodes something
a real run measured, so each exists to stop a plausible edit to `lab.md` from
quietly testing less than it claims.

The migration was also the test of Phase 2's step model: the extracted steps
have the same names, order, exit codes and wait conditions as the hardcoded
list, and `run.py` needed two lines changed, both to pass `REGION` into the
environment the lab's commands read.

## What does not exist yet

**Phase 4, scheduling.** No nightly run, so `health/HEALTH.md` holds three runs
rather than a week of them, and the flake rate the whole design is pointed at is
still barely measured.
