# HANDOFF

## Done
- All four phases built. `python -m harness.run` provisions, runs the steps
  extracted from `lab/sqs-retry/lab.md`, asserts, tears down, verifies, and
  records. Passed twice against real AWS (453s and 492s), all 11 checks green
- Phase 3: `harness/extract.py` reads the lab document and refuses any document
  that would weaken the test. The hardcoded step list is gone
- Phase 4: `lab-health.yml` runs nightly at 09:17 UTC via OIDC, commits the
  record back, and tears down in a safety step if the process is killed. The CI
  role now has two scoped policies; both account-wide grants carry a comment
  saying why they cannot be narrower
- README health figures are generated from the record; CI fails if they are
  stale. 98 tests pass with no credentials

## Failed / open
- **The nightly workflow has never run.** Push and fire it by hand
  (`gh workflow run lab-health.yml`) before trusting it. A failure there is
  most likely a missing IAM permission; the error names the action
- Redrive timing is still advisory: a handful of observations cannot set a
  tolerance. Promoting it is what the scheduled runs are for
- The receive count across a redrive is **not determinate**: 5 by hand, then 4
  and 4. The advisory was retired rather than promoted; the floor gates
- The tag query is an eventually-consistent index, so every ARN is resolved
  against its owning service before anything counts as a leak
- Both failed runs predate the fix that keeps partial measurements, so that fix
  is unit-tested but never exercised by a real failure
- Not built, deliberately: account vending, a second lab, a web dashboard, LMS
  integration, multi-region. See `README.md`

## Next
Fire the workflow once by hand. Then let a week accumulate and promote the
redrive tolerance from what the record says rather than from arithmetic.

## Why
The scheduled run is the only part that cannot be hurried. Everything else
proves the lab works once; this proves whether it keeps working, and records
the answer whether or not anyone is watching.
