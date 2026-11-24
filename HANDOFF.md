# HANDOFF

## Done
- All five phases done, and that claim is now derived rather than typed:
  `harness/phases.py` checks each phase's conditions against the repository and
  `health/health.jsonl`, and CI fails if the README's block is stale
- `python -m harness.run` provisions, runs the steps extracted from
  `lab/sqs-retry/lab.md`, asserts, tears down, verifies, records. Passed three
  times against real AWS, once from the scheduled workflow
- Cost measured: ~$0.00003 of AWS per run against $0.051 of CI runner time. The
  constraint is wall clock, not cloud resources. See the README
- `harness/redact.py` scrubs identifiers on the way into the record;
  `test_repo_hygiene.py` sweeps the repo for them. History was rewritten to
  remove the account, organization and principal ids
- 128 tests, no credentials needed

## Failed / open
- Runs. Five recorded, one from CI. The redrive tolerance stays advisory until
  the record can set a band, which is the only thing left that time alone fixes
- The receive count across a redrive is not determinate: 5 by hand, then 4, 4,
  4. The advisory was retired rather than promoted; the floor gates
- Both recorded failures predate the fix that keeps partial measurements, so
  that fix is unit-tested but never exercised by a real failure
- Not checkable from the repo, and so not claimed: whether the two bootstrap
  stacks are deployed. `harness/phases.py` says so in the generated block
- The warm-stack optimisation would cut the dominant cost and delete the
  teardown verification that found the stale tag index. Named as a trade in the
  README, deliberately unresolved

## Next
Let the nightly accumulate, then promote the redrive tolerance from the record.
Nothing else is outstanding against the scope.

## Why
Four separate claims rotted in one afternoon: a phase status, a figure list, a
prompt about a README section, and a hand scrub that missed what it was not
looking for. Each is now generated or swept. A claim maintained by hand beside
a system that already knows the answer rots at the speed the system runs.
