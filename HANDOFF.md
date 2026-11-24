# HANDOFF

## Done
- All five phases done, derived not typed: `harness/phases.py` checks each
  against the repo and the record, and CI fails if the README block is stale
- `python -m harness.run` provisions, runs the steps extracted from `lab.md`,
  asserts, tears down, verifies, records. Three real passes, one from CI
- Cost measured: AWS ~$0.00003 a run against $0.051 of CI time. The constraint
  is wall clock, not cloud resources
- `python -m harness.tolerance` answers the one open decision from the record;
  its verdict lands in HEALTH.md and the README every run
- Identifiers scrubbed on write, swept repo-wide, gone from history. 163 tests
- Public health page: `harness/site.py` generates it from the record;
  `.github/workflows/pages.yml` publishes it after each Lab health run

## Failed / open
- Waiting on runs: 3 observations on 1 day, criterion wants 10 across 7. A
  scheduled task on 2026-11-30 reports promote, retire or wait
- Receive count across a redrive is not determinate (5 by hand, then 4, 4, 4);
  that advisory was retired, not promoted, and the floor gates
- No cold-start test of this repo, the one thing it preaches and skips
- Warm stack would cut the dominant cost and delete the teardown check that
  found the stale tag index. Named in the README, deliberately unresolved

## Next
Turn on Pages (Settings > Pages > Source: GitHub Actions), then run Health page
by hand once. Let the nightly accumulate; the 2026-11-30 task decides.

## Why
Seven claims rotted in a day: a phase status, a figure list, a prompt, two
medians, a workflow comment, a hand scrub. Each is now generated or deleted.
