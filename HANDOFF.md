# HANDOFF (coldlab)
DONE: all five phases, derived by harness/phases.py; CI fails if the README block is stale.
DONE: python -m harness.run provisions, runs lab.md steps, asserts, tears down, verifies, records. Three real passes, one from CI.
DONE: cost measured, AWS ~$0.00003 a run vs $0.051 of CI time; wall clock is the constraint.
DONE: health page (harness/site.py, pages.yml) with "What happened" notes from health/notes.json.
DONE: publishing by version (harness/publish.py): promote after 3 consecutive passes on that exact content, rollback recorded.
DONE: learner sandbox (learner-role.yaml, lab/sqs-retry/sandbox.yaml, harness/sandbox.py via the IAM policy simulator); RUNBOOK Step 13.
DONE: identifiers scrubbed from repo and history; account number is a placeholder; setup is portable (no Mac or personal paths).
OPEN: 3 observations on 1 day; criterion wants 10 across 7. A scheduled task on 2026-11-30 reports promote, retire or wait.
OPEN: receive count across a redrive is not determinate (5, then 4, 4, 4); advisory retired, the floor gates.
OPEN: no cold-start test of this repo, the thing it preaches.
OPEN: warm stack would cut the dominant cost but delete the teardown check that found the stale tag index; deliberately unresolved.
FINDING: CDK's CloudFormation execution role is AdministratorAccess; the learner boundary does not cover the deployer.
NEXT (John): push 59f1ad4 and d7c5678; confirm Pages is on (Source: GitHub Actions).
NEXT (John): deploy the coldlab-learner stack, then python -m harness.sandbox (RUNBOOK Step 13).
NEXT: first real promotion and sandbox run, then fieldguide marks lab-publishing and sandbox-guardrails full.
WHY: seven claims rotted in a day (phase status, figure list, prompt, two medians, a comment, a hand scrub); each is now generated or deleted.
WHY: deploy uses separate build/deploy jobs with per-attempt artifact names (actions/deploy-pages#451).
Commit messages: no Co-Authored-By or Claude-Session trailers.
