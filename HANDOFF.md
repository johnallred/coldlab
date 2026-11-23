# HANDOFF

## Done
- Phase 0: budget + OIDC role deployed; CI assumes the role with no stored key
- Phase 1: `ColdlabSqsRetry` deployed, both paths run by hand, torn down,
  teardown verified. Nothing is live in 111122223333 / us-east-2
- `lab/sqs-retry/expected.yaml`: every value measured or derived, never read off
  the template
- Phase 2: `harness/` provisions, runs the lab's steps, asserts, tears down in a
  `finally`, resolves tagged ARNs, appends to `health/health.jsonl`. 57 tests
  pass against a fake AWS, including the deliberate-failure cases. CI runs them
  on every pull request with no credentials

## Failed / open
- **The harness has never completed against real AWS.** First attempt deployed
  into us-east-1 and was denied by an Organizations SCP. Cause: `app.py` read
  `region=os.environ.get("CDK_DEFAULT_REGION", "us-east-2")`, but the CDK CLI
  always sets that variable from the credentials' region, so the default could
  never fire and the stack followed the credentials. Now pinned to
  `COLDLAB_REGION`, which the harness sets from `--region`. A fallback that can
  never fire is worse than none, because it reads like a guarantee
- Five behaviours measured that the templates did not predict, all in
  expected.yaml and the README table: the worker's own 15/30/60 backoff rather
  than the queue's 180s timeout; short-poll receives reporting an empty queue
  that was not; a long poll returning 1 of 2; receive count carrying across the
  redrive; the tag query reporting a resource CloudFormation had deleted
- Two OIDC traps, in RUNBOOK troubleshooting: the immutable subject claim, and
  `CreateOIDCProvider=no` deleting the provider the stack owned
- A failed run used to print three green teardown lines and "0 failing checks".
  The abort is now a gating `run.completed` check, so the record says so
- Two checks are advisory, not gating: exact receive count and redrive timing.
  Promotion criteria are stated in `harness/checks.py`. Neither can be promoted
  honestly until there are recorded runs to set a tolerance from

## Next
Run Step 11 once and fix whatever the real AWS disagrees with. Then Phase 3:
replace `harness/steps.py` with `extract.py` reading `lab/sqs-retry/lab.md`,
which also means writing that lab document. `run.py` must not change.

## Why
The harness's logic is separated from its AWS calls so that the part worth
testing can be tested without credentials, a deployment, or cost. That is also
why the failure paths are proved in unit tests rather than by breaking a
deployed stack once: a failure proved once by hand is a story, and a failure
proved every pull request is a guarantee.
