# HANDOFF

## Done
- Phase 0 scaffolded: budget + OIDC role templates, smoke workflow, .gitignore
- Region pinned to us-east-2; account 111122223333 recorded in bootstrap/README
- Phase 1 written: CDK stack for the SQS retry lab, synthesizes clean
- Verified in the template: DLQ 14d, source queue 180s visibility,
  maxReceiveCount 3, event source batch 1 with ReportBatchItemFailures

## Failed / open
- Nothing is deployed. The Cowork VM has no aws CLI, no cdk, no gh, and no
  access to credentials, so every deploy step below is yours to run.
- Teardown verification by tag is incomplete: 8 of 15 resources carry the lab
  tags; the other 7 are CDK-generated policies and the S3 auto-delete provider,
  which take no tags. Verify teardown twice: stack DELETE_COMPLETE *and* a tag
  query returning nothing.
- The account has not been cdk-bootstrapped for us-east-2 yet.
- The .venv created while verifying the stack held Linux binaries and was
  deleted. RUNBOOK step 6 creates a macOS one.

## Next
Follow RUNBOOK.md, steps 0 to 10. It is written to be worked top to bottom and
every step says what success looks like. Nothing in it can be run for you: it
all needs AWS credentials.

After step 8 deploys, Phase 2 is the harness that automates step 9.

## Why
The stack is written before anything is deployed because synthesis catches
structural mistakes without costing anything or touching the account. The
failure path is proved before the success path for the same reason it is in
the lab itself: the retry behaviour is the thing being taught.
