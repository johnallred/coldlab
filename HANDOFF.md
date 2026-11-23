# HANDOFF

## Done
- Phases 0 to 2 complete. `python -m harness.run` passed end to end on
  2026-11-23: provision, both lab paths, assertions, teardown, verification,
  health record. 492s. Nothing is live in 111122223333 / us-east-2
- 67 tests pass with no credentials; CI runs them on every pull request
- `health/health.jsonl` has 3 real runs (1 pass, 2 failures that found bugs)

## Failed / open
Eight things measured that reading the code or the templates got wrong. Full
detail in RUNBOOK troubleshooting, `lab/sqs-retry/expected.yaml` and the README
table. The ones that still shape the design:
- The exact receive count across a redrive is **not determinate**: 5 by hand,
  4 from the harness, same lab. The advisory was retired rather than promoted;
  the floor `maxReceiveCount + 1` gates
- The tag query is an eventually-consistent index, so every ARN is resolved
  against its owning service before anything counts as a leak
- A default that can never fire is worse than none: `CDK_DEFAULT_REGION` is
  always set, so app.py's `"us-east-2"` fallback was dead code and a deploy
  went to us-east-1
- A fake kinder than the real tool tests nothing: the fake `aws s3 ls` exited 0
  where the real one exits 1, so 63 tests passed through two live bugs
- Redrive timing is still advisory; observed 115s and 146s against a nominal
  105s. Needs more runs before a tolerance can be set honestly

## Next
Phase 3: replace `harness/steps.py` with `extract.py` reading
`lab/sqs-retry/lab.md`, including its `# exits N:` directives. `run.py` must
not change. Writing that lab document is most of the work.

## Why
Every one of the eight came from printing what the system did rather than
re-reading what it was configured to do.
