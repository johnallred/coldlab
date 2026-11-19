# HANDOFF

## Done
- Phase 0: budget + OIDC role deployed; CI assumes the role with no stored key
- Phase 1: `ColdlabSqsRetry` deployed, both paths run by hand, torn down,
  teardown verified. Nothing is live in 111122223333 / us-east-2 now
- `lab/sqs-retry/expected.yaml`: every value measured or derived, never read off
  the template. It is what Phase 2 asserts against

## Failed / open
Five things measured that the templates did not predict; details in RUNBOOK
troubleshooting and expected.yaml.
- OIDC twice: immutable subject claim with ids appended, then
  `CreateOIDCProvider=no` deleting the provider the stack owned
- Redrive is at ~t=105 on the worker's own 15/30/60 backoff, not the queue's
  180s visibility timeout, which is only the initial lease
- A short-poll `receive-message` returns nothing from a 1-2 message queue; a
  long poll with max 10 still returned 1 of 2. Read depth, never counts
- Receive count carries across the redrive: arrival 4, first DLQ read 5. True
  once per message only
- The tag query is an eventually-consistent index and reported a leak that was
  not there. Resolve every ARN against its owning service before believing it

## Next
Phase 2, the harness for Step 9. Four measured constraints: long poll, read
depth, read each DLQ message once, resolve tag ARNs before reporting a leak.

## Why
Every correction came from printing what the system did, not re-reading what it
was configured to do. Three rounds against a correct-looking trust policy found
nothing; one diagnostic step found it in a minute.
